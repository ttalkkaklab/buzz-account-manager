import datetime
import unittest
from unittest.mock import patch
import test_backend as fixture
b = fixture.b


class FallbackTests(unittest.TestCase):
    tearDown = fixture.ManagerTests.tearDown
    request = fixture.ManagerTests.request
    def setUp(self):
        fixture.ManagerTests.setUp(self)
        self.spare = self.manager.create_account('spare', 'codex')
        b.write_json(b.Path(self.spare['home']) / 'auth.json', {'auth_mode': 'chatgpt', 'tokens': {'access_token': 'test'}})

    def quota(self, remaining, **extra):
        return dict(status='ok', checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    windows=[dict(remaining_percent=remaining, is_primary=True, scope='codex')], **extra)

    def configure(self):
        req = self.request()
        req.update(fallback_ids=[self.spare['id']], auto_fallback=True)
        self.manager.apply(req)
        return self.manager.root / ('agent-' + self.pk + '.json')

    def test_fallback_validation(self):
        for ids in ([self.spare['id']] * 2, ['a', 'b', 'c', 'd'], ['default-codex'], ['default-claude']):
            req = self.request(); req.update(fallback_ids=ids, auto_fallback=True)
            with self.assertRaises(ValueError): self.manager.validate(req)
        req = self.request(); req.update(fallback_ids=[], auto_fallback=True)
        with self.assertRaises(ValueError): self.manager.validate(req)

    def test_limited_switches_and_rotates_without_model_changes(self):
        path = self.configure()
        before = self.manager.store.read_bytes()
        with patch.object(self.manager, 'usage', side_effect=lambda aid: self.quota(0 if aid == 'default-codex' else 70)):
            state = self.manager.monitor()
        profile = b.read_json(path)
        self.assertEqual(profile['account_ids']['codex'], self.spare['id'])
        self.assertEqual(profile['fallback_ids']['codex'], ['default-codex'])
        self.assertEqual(self.manager.store.read_bytes(), before)
        self.assertEqual(len(state['events']), 1)
        with patch.object(self.manager, 'usage', return_value=self.quota(50)):
            self.manager.monitor()
        self.assertEqual(b.read_json(path)['account_ids']['codex'], self.spare['id'])

    def test_unknown_and_exhausted_spares_do_not_switch(self):
        for spare_usage in (self.quota(0), {'status': 'unavailable'}):
            path = self.configure(); before = path.read_bytes()
            with patch.object(self.manager, 'usage', side_effect=lambda aid: self.quota(0) if aid == 'default-codex' else spare_usage):
                self.manager.monitor()
            self.assertEqual(path.read_bytes(), before)

    def test_current_unknown_does_not_switch(self):
        path = self.configure(); before = path.read_bytes()
        with patch.object(self.manager, 'usage', return_value={'status': 'unavailable'}):
            self.manager.monitor()
        self.assertEqual(path.read_bytes(), before)

    def test_quota_scopes_freshness_and_invalid_values(self):
        q = self.quota(60)
        q['windows'].append(dict(remaining_percent=0, scope='gpt-reserve', is_primary=False))
        self.assertEqual(self.manager.quota_state(q, 'codex', 'gpt-6-astra'), 'available')
        self.assertEqual(self.manager.quota_state(q, 'codex', 'gpt-5.6-luna'), 'available')
        q['ordinary_blocked'] = True
        self.assertEqual(self.manager.quota_state(q, 'codex', 'gpt-5.6-luna'), 'limited')
        self.assertEqual(self.manager.quota_state(q, 'codex', 'gpt-spark'), 'unknown')
        q['checked_at'] = '2000-01-01T00:00:00+00:00'
        self.assertEqual(self.manager.quota_state(q, 'codex', 'gpt-6-astra'), 'unknown')
        q = self.quota(0); q['windows'][0]['resets_at'] = '2000-01-01T00:00:00+00:00'
        self.assertEqual(self.manager.quota_state(q, 'codex', 'gpt-6-astra'), 'unknown')
        for value in (float('nan'), None, True):
            self.assertEqual(self.manager.quota_state(self.quota(value), 'codex', 'gpt'), 'unknown')
        q = self.quota(50, ordinary_blocked=True)
        self.assertEqual(self.manager.quota_state(q, 'codex', 'gpt'), 'limited')

    def test_claude_model_specific_limit(self):
        q = self.quota(90)
        q['windows'].append(dict(scope='seven_day_fable', remaining_percent=0, is_primary=False))
        self.assertEqual(self.manager.quota_state(q, 'claude', 'fable'), 'limited')
        self.assertEqual(self.manager.quota_state(q, 'claude', 'sonnet'), 'available')

    def test_disabled_does_not_switch(self):
        path = self.configure(); p = b.read_json(path); p['auto_fallback']['codex'] = False; b.write_json(path, p)
        with patch.object(self.manager, 'usage', return_value=self.quota(0)):
            self.assertEqual(self.manager.monitor()['events'], [])

    def test_shutdown_failure_does_not_write(self):
        path = self.configure(); before = path.read_bytes()
        with patch.object(self.manager, 'usage', side_effect=lambda aid: self.quota(0 if aid == 'default-codex' else 90)), patch.object(self.manager, 'buzz_running', return_value=True), patch.object(b.subprocess, 'run', side_effect=OSError):
            self.manager.monitor()
        self.assertEqual(before, path.read_bytes())

    def test_fallback_account_cannot_be_deleted(self):
        self.configure()
        with self.assertRaises(ValueError): self.manager.delete_account(self.spare['id'])

    def test_profile_write_failure_rolls_back(self):
        path = self.configure(); before = path.read_bytes()
        original = b.atomic_bytes
        failed = False
        def fail_once(target, data, mode=0o600):
            nonlocal failed
            if target == path and not failed:
                failed = True
                raise OSError('test')
            return original(target, data, mode)
        with patch.object(self.manager, 'usage', side_effect=lambda aid: self.quota(0 if aid == 'default-codex' else 90)), patch.object(b, 'atomic_bytes', side_effect=fail_once):
            state = self.manager.monitor()
        self.assertEqual(before, path.read_bytes())
        self.assertIn('완료하지 못했습니다', state['events'][0])

    def test_running_buzz_restarts_once(self):
        self.configure()
        other = self.request(); other['agent_id'] = 'b' * 64
        other.update(fallback_ids=[self.spare['id']], auto_fallback=True)
        self.manager.apply(other)
        with patch.object(self.manager, 'usage', side_effect=lambda aid: self.quota(0 if aid == 'default-codex' else 90)), patch.object(self.manager, 'buzz_running', side_effect=[True, False]), patch.object(b.subprocess, 'run') as run:
            run.return_value.returncode = 0
            state = self.manager.monitor()
        self.assertEqual(len(state['events']), 2)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args.args[0][0], '/usr/bin/open')

    def test_stale_editor_cannot_override_switch(self):
        self.configure()
        req = self.request(); req['expected_account_id'] = 'default-codex'
        with patch.object(self.manager, 'usage', side_effect=lambda aid: self.quota(0 if aid == 'default-codex' else 90)):
            self.manager.monitor()
        with self.assertRaises(ValueError): self.manager.apply(req)
