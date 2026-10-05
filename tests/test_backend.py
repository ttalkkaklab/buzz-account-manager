import sandbox  # Isolate paths and guard writes before loading application code.
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from platform_fixtures import HAS_PRIVATE_MODES, installed_launcher, capture_launch, launch

spec = importlib.util.spec_from_file_location('backend', Path(__file__).resolve().parents[1] / 'Resources/backend.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        installed_launcher(self, self.home)
        self.manager = b.Manager(self.home)
        self.pk = 'a' * 64
        self.records = [
            {'name': '리더', 'slug': 'role-leader', 'pubkey': '', 'runtime': 'codex', 'model': 'test-model', 'is_active': True},
            {'name': '리더', 'persona_id': 'role-leader', 'pubkey': self.pk, 'runtime': 'codex', 'model': 'test-model',
             'effort_level': 'medium', 'is_active': True, 'team_id': 'keep-team', 'auth_tag': 'test-attestation',
             'parallelism': 3, 'system_prompt': 'preserve instructions', 'agent_args': ['--test-existing'],
             'env_vars': {'KEEP_ME': 'value', 'ANTHROPIC_MODEL': 'stale'}},
            {'name': '작가', 'pubkey': 'b' * 64, 'runtime': 'codex', 'model': 'other', 'is_active': True},
            {'name': 'Grok', 'slug': 'builtin:bumble', 'pubkey': '', 'runtime': 'grok', 'is_active': False}]
        b.write_json(self.manager.store, self.records)
        b.write_json(self.home / '.codex/auth.json', {'auth_mode':'chatgpt', 'tokens':{'access_token':'test-only'}})
        b.write_json(self.home / '.codex/models_cache.json', {'models':[
            {'slug':'test-model', 'display_name':'Test', 'supported_reasoning_levels':[{'effort':'medium'}, {'effort':'high'}]}]})
        self.cli = patch.object(b.Manager, 'resolve_cli', return_value='/test/cli')
        self.cli.start()
        self.running = patch.object(b.Manager, 'buzz_running', return_value=False)
        self.running.start()
    def tearDown(self):
        self.cli.stop(); self.running.stop(); self.temp.cleanup()
    def request(self):
        return dict(agent_id=self.pk, account_id='default-codex', provider='codex', model='test-model', effort='high',
                    revision=b.revision(self.manager.store.read_bytes()))
    def test_new_codex_model_saves_despite_stale_cache_and_reaches_runtime(self):
        req = dict(self.request(), model='future-codex-model')
        self.manager.apply(req)
        saved = b.read_json(self.manager.store)
        instance = next(r for r in saved if r.get('pubkey') == self.pk)
        definition = next(r for r in saved if r.get('slug') == instance['persona_id'])
        for record in (instance, definition):
            self.assertEqual(record['model'], req['model'])
            self.assertEqual(record['effort_level'], req['effort'])
        env = dict(BUZZ_PRIVATE_KEY='test-identity', BUZZ_ACP_AGENT_COMMAND='codex-acp', BUZZ_ACP_MODEL=instance['model'],
                   BUZZ_ACP_EFFORT_LEVEL=instance['effort_level'])
        with patch.dict(os.environ, env, clear=True), capture_launch(b) as execute:
            launch(self, self.manager, 'agent-' + self.pk, [])
            config = json.loads(execute.call_args.args[2]['CODEX_CONFIG'])
            self.assertEqual(config['model'], req['model'])
            self.assertEqual(config['model_reasoning_effort'], req['effort'])
    def test_custom_account_hide_restore_preserves_metadata_and_credentials(self):
        for provider in ('codex', 'claude', 'grok', 'ollama'):
            with self.subTest(provider=provider):
                endpoint = 'http://127.0.0.1:11436' if provider in ('codex', 'ollama') else None
                account = self.manager.create_account('Restorable', provider, endpoint)
                auth = Path(account['home']) / 'auth.json'
                auth.write_text('{"fixture":"preserve"}')
                before = auth.read_bytes()
                self.manager.delete_account(account['id'])
                restarted = b.Manager(self.home)
                self.assertNotIn(account, restarted.accounts())
                self.assertIn(account, restarted.hidden_accounts())
                self.assertIn(account, restarted.accounts(include_hidden=True))
                with self.assertRaises(ValueError) as create_error:
                    restarted.create_account('Restorable', provider, endpoint)
                self.assertEqual(str(create_error.exception), '숨긴 계정 중에 같은 이름이 있습니다. 「숨긴 계정」에서 복원하거나 다른 이름을 쓰세요.')
                other = restarted.create_account('Other', provider, endpoint)
                with self.assertRaises(ValueError) as update_error:
                    restarted.update_account(other['id'], 'Restorable')
                self.assertEqual(str(update_error.exception), '숨긴 계정 중에 같은 이름이 있습니다. 「숨긴 계정」에서 복원하거나 다른 이름을 쓰세요.')
                restarted.restore_account(account['id'])
                self.assertEqual(restarted.account(account['id']), account)
                self.assertEqual(auth.read_bytes(), before)
                self.assertNotIn(account, restarted.hidden_accounts())
                for operation in (lambda: restarted.create_account('Restorable', provider, endpoint),
                                  lambda: restarted.update_account(other['id'], 'Restorable')):
                    with self.assertRaises(ValueError) as visible_error:
                        operation()
                    self.assertEqual(str(visible_error.exception), '같은 서비스에 같은 이름의 계정이 있습니다.')
        data = b.read_json(self.manager.registry)
        data['hidden_defaults'] = ['default-grok']
        b.write_json(self.manager.registry, data)
        self.assertIn('default-grok', [a['id'] for a in self.manager.hidden_accounts()])
        self.manager.restore_account('default-grok')
        self.assertEqual(self.manager.account('default-grok')['id'], 'default-grok')

    def test_reorder_persists_and_new_accounts_follow_in_registration_order(self):
        first = self.manager.create_account('First', 'codex')
        second = self.manager.create_account('Second', 'codex')
        ids = lambda m: [a['id'] for a in m.accounts()]
        self.assertEqual(ids(self.manager)[-2:], [first['id'], second['id']])
        result = self.manager.reorder_accounts([second['id'], 'default-codex', first['id'], 'default-claude', 'default-grok', 'default-ollama'])
        self.assertEqual(result['message'], '계정 순서를 저장했습니다.')
        restarted = b.Manager(self.home)
        self.assertEqual(ids(restarted), [second['id'], 'default-codex', first['id'], 'default-claude', 'default-grok', 'default-ollama'])
        third = restarted.create_account('Third', 'claude')
        self.assertEqual(ids(b.Manager(self.home))[-1], third['id'])
        self.assertEqual(b.read_json(restarted.registry)['account_order'][-1], 'default-ollama')

    def test_partial_reorder_refills_only_the_slots_those_accounts_held(self):
        codex = self.manager.create_account('Codex two', 'codex')
        claude = self.manager.create_account('Claude two', 'claude')
        before = [a['id'] for a in self.manager.accounts()]
        self.assertEqual(before, ['default-codex', 'default-claude', 'default-grok', 'default-ollama', codex['id'], claude['id']])
        self.manager.reorder_accounts([claude['id'], 'default-claude'])
        self.assertEqual([a['id'] for a in b.Manager(self.home).accounts()],
                         ['default-codex', claude['id'], 'default-grok', 'default-ollama', codex['id'], 'default-claude'])

    def test_reorder_rejects_unknown_hidden_duplicate_and_malformed_lists(self):
        account = self.manager.create_account('Gone', 'grok')
        self.manager.delete_account(account['id'])
        for bad in ([], ['default-codex', 'default-codex'], ['missing'], [account['id']], 'default-codex', [1], None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.manager.reorder_accounts(bad)
        self.assertNotIn('account_order', b.read_json(self.manager.registry))

    def test_deleted_account_leaves_the_order_and_restored_account_returns_last(self):
        account = self.manager.create_account('Movable', 'codex')
        self.manager.reorder_accounts([account['id'], 'default-codex'])
        self.assertEqual(b.read_json(self.manager.registry)['account_order'][0], account['id'])
        self.manager.delete_account(account['id'])
        self.assertNotIn(account['id'], b.read_json(self.manager.registry)['account_order'])
        self.assertEqual([a['id'] for a in self.manager.hidden_accounts()], [account['id']])
        self.manager.restore_account(account['id'])
        self.assertEqual([a['id'] for a in b.Manager(self.home).accounts()],
                         ['default-claude', 'default-grok', 'default-ollama', 'default-codex', account['id']])

    def test_delete_account_ignores_template_and_inactive_agent_links(self):
        account = self.manager.create_account('Unused', 'codex')
        template = self.records[0]
        inactive = dict(self.records[2], is_active=False)
        template['acp_command'] = str(self.manager.root / 'launch-template')
        inactive['acp_command'] = str(self.manager.root / 'launch-inactive')
        b.write_json(self.manager.root / 'template.json',
                     {'account_ids': {'codex': account['id']}})
        b.write_json(self.manager.root / 'inactive.json',
                     {'fallback_ids': {'codex': [account['id']]}})
        b.write_json(self.manager.store, [template, inactive])

        self.manager.delete_account(account['id'])
        self.manager.delete_account('default-codex')

        hidden = {item['id'] for item in self.manager.hidden_accounts()}
        self.assertIn(account['id'], hidden)
        self.assertIn('default-codex', hidden)

    def test_delete_account_rejects_active_agent_links(self):
        record = dict(self.records[1], acp_command=str(self.manager.root / 'launch-linked'))
        b.write_json(self.manager.store, [record])
        explicit = self.manager.create_account('Explicit', 'codex')
        fallback = self.manager.create_account('Fallback', 'codex')
        cases = [
            (explicit['id'], {'account_ids': {'codex': explicit['id']}}),
            ('default-codex', {}),
            (fallback['id'], {'account_ids': {'codex': explicit['id']},
                              'fallback_ids': {'codex': [fallback['id']]}}),
        ]
        for identity, profile in cases:
            with self.subTest(identity=identity):
                b.write_json(self.manager.root / 'linked.json', profile)
                with self.assertRaisesRegex(ValueError, '에이전트에 연결된 계정입니다'):
                    self.manager.delete_account(identity)
                self.assertEqual(self.manager.account(identity)['id'], identity)

    def test_apply_rechecks_primary_and_fallback_after_validation_under_lock(self):
        account = self.manager.create_account('Race target', 'codex')
        b.write_json(Path(account['home']) / 'auth.json',
                     {'auth_mode': 'chatgpt', 'tokens': {'access_token': 'test-only'}})
        original_lock = self.manager.lock
        for target in ('default-codex', account['id'], 'fallback'):
            with self.subTest(target=target):
                b.write_json(self.manager.registry, {'version': 1, 'accounts': [account]})
                req = self.request()
                if target == 'fallback':
                    req['fallback_ids'] = [account['id']]
                else:
                    req['account_id'] = target
                hidden_id = account['id'] if target == 'fallback' else target
                before = self.manager.store.read_bytes()
                @contextlib.contextmanager
                def hide_before_lock():
                    # Simulate another process hiding an account after validate
                    # and before apply obtains the shared manager lock.
                    data = b.read_json(self.manager.registry)
                    data['hidden_accounts'] = [hidden_id]
                    b.write_json(self.manager.registry, data)
                    with original_lock():
                        yield
                with patch.object(self.manager, 'lock', side_effect=hide_before_lock), \
                     patch.object(self.manager, 'validate', wraps=self.manager.validate) as validate:
                    with self.assertRaisesRegex(ValueError, '계정이 없습니다. 새로고침해 주세요.'):
                        self.manager.apply(req)
                    validate.assert_called_once_with(req)
                self.assertEqual(self.manager.store.read_bytes(), before)
                self.assertFalse((self.manager.root / ('agent-' + self.pk + '.json')).exists())
                self.assertFalse((self.manager.root / 'backups').exists())

    def test_local_codex_ready_validate_apply_without_tokens(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.path, self.headers.get('Authorization')))
                self.send_response(200); self.end_headers()
                self.wfile.write(b'{"data":[{"id":"local-model"}]}')
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            endpoint = 'http://127.0.0.1:' + str(server.server_port)
            a = self.manager.create_account('Local', 'codex', endpoint + '/v1/', model_context_window=131072)
            self.assertEqual(a['endpoint'], endpoint)
            self.assertIn('model_context_window = 131072\n', (Path(a['home']) / 'config.toml').read_text())
            self.assertFalse((Path(a['home']) / 'auth.json').exists())
            self.assertTrue(self.manager.account_ready(a))
            req = self.request(); req.update(account_id=a['id'], model='local-model')
            self.manager.validate(req)
            self.manager.apply(req)
            records = b.read_json(self.manager.store)
            self.assertEqual(records[1]['model'], 'local-model')
            self.assertEqual(records[1]['effort_level'], 'high')
            self.assertEqual(records[1]['mcp_command'], 'buzz-dev-mcp')
            self.assertEqual(records[1]['pubkey'], self.pk)
            self.assertEqual(records[2:], self.records[2:])
            profile = b.read_json(self.manager.root / ('agent-' + self.pk + '.json'))
            self.assertEqual(profile['account_ids']['codex'], a['id'])
            env = dict(BUZZ_PRIVATE_KEY='identity', BUZZ_ACP_AGENT_COMMAND='codex-acp',
                       BUZZ_ACP_MODEL='local-model', BUZZ_ACP_EFFORT_LEVEL='high',
                       OPENAI_API_KEY='must-not-reach-local', CODEX_CONFIG='{"model_provider":"openai","model_context_window":32768}')
            with patch.dict(os.environ, env, clear=True), capture_launch(b) as execute:
                launch(self, self.manager, 'agent-' + self.pk, [])
                runtime = execute.call_args.args[2]
                config = json.loads(runtime['CODEX_CONFIG'])
                self.assertEqual(runtime['CODEX_HOME'], a['home'])
                self.assertNotIn('OPENAI_API_KEY', runtime)
                self.assertEqual(config['model_provider'], 'local')
                self.assertEqual(config['model_context_window'], 131072)
                self.assertEqual(config['model'], 'local-model')
                self.assertEqual(config['model_providers']['local']['base_url'], endpoint + '/v1')
                self.assertFalse(config['model_providers']['local']['requires_openai_auth'])
            for request in requests:
                self.assertEqual(request, ('/v1/models', None))
            before = self.manager.store.read_bytes()
            req.update(model='not-installed', revision=b.revision(before))
            with self.assertRaises(ValueError): self.manager.apply(req)
            self.assertEqual(self.manager.store.read_bytes(), before)
            with patch.object(b, 'CodexRPC', side_effect=AssertionError('cloud request')):
                self.assertEqual(self.manager.usage(a['id'])['status'], 'unavailable')
                with self.assertRaises(ValueError): self.manager.login_plan(a['id'])
                with self.assertRaises(ValueError): self.manager.codex_login(a['id'])
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_local_codex_not_ready_and_catalog_validation(self):
        import io
        a = self.manager.create_account('Offline', 'codex', 'http://127.0.0.1:11235')
        # A leftover subscription token cannot make an offline local server ready.
        b.write_json(Path(a['home']) / 'auth.json', {'auth_mode':'chatgpt', 'tokens':{'access_token':'test'}})
        for payload in (b'{}', b'[]', b'{"data":[{}]}', b'{"data":[{"id":12}]}', b'bad json'):
            self.manager._local_codex_cache.clear()
            with patch.object(b.urllib.request, 'build_opener') as opener:
                opener.return_value.open.return_value = io.BytesIO(payload)
                self.assertFalse(self.manager.account_ready(a))
        self.manager._local_codex_cache.clear()
        before = self.manager.store.read_bytes()
        req = self.request(); req['account_id'] = a['id']
        with patch.object(b.urllib.request, 'build_opener') as opener:
            opener.return_value.open.side_effect = OSError('offline')
            self.assertFalse(self.manager.account_ready(a))
            with self.assertRaises(ValueError): self.manager.apply(req)
        self.assertEqual(self.manager.store.read_bytes(), before)

    def test_local_codex_context_validation(self):
        for value in (True, 0, -1, 1.5, '131072'):
            with self.assertRaises(ValueError):
                self.manager.create_account('invalid', 'codex', 'http://localhost:11235', value)
        with self.assertRaises(ValueError):
            self.manager.create_account('subscription', 'codex', model_context_window=131072)
        account = self.manager.create_account('Default context', 'codex', 'http://localhost:11235')
        self.assertNotIn('model_context_window', account)
        self.assertNotIn('model_context_window', self.manager.local_codex_config(account))
        self.assertNotIn('model_context_window', (Path(account['home']) / 'config.toml').read_text())

    def test_local_codex_endpoint_and_fallback_boundaries(self):
        for endpoint in ('file:///tmp', 'http://user:secret@localhost', 'http://localhost?key=x',
                         'http://localhost/v2', 'http://localhost:bad', 'http://localhost#secret'):
            with self.assertRaises(ValueError): self.manager.create_account('invalid', 'codex', endpoint)
        a = self.manager.create_account('Local', 'codex', 'http://localhost:11235')
        req = self.request(); req.update(account_id=a['id'], fallback_ids=['default-codex'])
        with self.assertRaises(ValueError): self.manager.validate_fallback(req)
        req = self.request(); req['fallback_ids'] = [a['id']]
        with self.assertRaises(ValueError): self.manager.validate_fallback(req)
        self.assertTrue(self.manager.account_ready(self.manager.account('default-codex')))
        self.assertNotIn('endpoint', self.manager.create_account('Subscription', 'codex'))

    def test_apply_preserves_other_agents_and_identity(self):
        self.manager.apply(self.request())
        updated = b.read_json(self.manager.store)
        self.assertEqual(updated[2:], self.records[2:])
        self.assertEqual(updated[1]['team_id'], 'keep-team')
        self.assertEqual(updated[1]['auth_tag'], 'test-attestation')
        self.assertEqual(updated[1]['pubkey'], self.pk)
        self.assertEqual(updated[1]['parallelism'], 3)
        self.assertEqual(updated[1]['system_prompt'], 'preserve instructions')
        self.assertEqual(updated[1]['agent_args'], ['--test-existing'])
        self.assertEqual(updated[0]['effort_level'], 'high')
        self.assertEqual(updated[1]['agent_command_override'], updated[1]['agent_command'])
        self.assertEqual(updated[1]['env_vars'], {'KEEP_ME':'value'})
        self.assertTrue(Path(updated[1]['acp_command']).exists())
    @unittest.skipIf(os.name == 'nt', 'posix launcher')
    def test_launcher_pins_python_that_cannot_move(self):
        self.manager.apply(self.request())
        launcher = Path(b.read_json(self.manager.store)[1]['acp_command']).read_text()
        self.assertIn('exec /usr/bin/python3 ', launcher)
    def test_no_writes_when_buzz_running(self):
        before = self.manager.store.read_bytes()
        with patch.object(b.Manager, 'buzz_running', return_value=True):
            with self.assertRaises(ValueError):self.manager.apply(self.request())
        self.assertEqual(before, self.manager.store.read_bytes())
    def test_conflict_blocks_writes(self):
        req = self.request()
        self.records[2]['model'] = 'user-changed'
        b.write_json(self.manager.store, self.records)
        with self.assertRaises(ValueError):self.manager.apply(req)
        self.assertEqual(b.read_json(self.manager.store)[2]['model'], 'user-changed')
    def test_shutdown_timestamp_does_not_conflict(self):
        req = self.request()
        self.records[1]['last_stopped_at'] = 'now'
        self.records[1]['updated_at'] = 'now'
        b.write_json(self.manager.store, self.records)
        self.manager.apply(req)
    def test_wrong_account_provider_and_missing_login(self):
        req = self.request();req['account_id'] = 'default-grok'
        with self.assertRaises(ValueError):self.manager.validate(req)
        a = self.manager.create_account('new', 'codex')
        req = self.request();req['account_id'] = a['id']
        with self.assertRaises(ValueError):self.manager.validate(req)
    def test_effort_validation(self):
        req = self.request();req['effort'] = 'ultra'
        with self.assertRaises(ValueError):self.manager.validate(req)
    def test_claude_efforts_save_and_reach_runtime(self):
        levels = ['low', 'medium', 'high', 'xhigh', 'max']
        opus = next(m for m in self.manager.models('claude') if m['id'] == 'opus')
        self.assertEqual(opus['efforts'], levels)
        for level in levels:
            with self.subTest(effort=level):
                req = self.request()
                req.update(provider='claude', account_id='default-claude', model='opus', effort=level)
                with patch.object(b.Manager, 'account_ready', return_value=True):
                    self.manager.apply(req)
                self.assertEqual(b.read_json(self.manager.store)[1]['effort_level'], level)
                env = dict(BUZZ_PRIVATE_KEY='test-identity', BUZZ_ACP_AGENT_COMMAND='claude-agent-acp', BUZZ_ACP_MODEL='opus',
                           BUZZ_ACP_EFFORT_LEVEL=level)
                with patch.dict(os.environ, env, clear=True), capture_launch(b) as execute:
                    launch(self, self.manager, 'agent-' + self.pk, [])
                    self.assertEqual(execute.call_args.args[2]['CLAUDE_CODE_EFFORT_LEVEL'], level)
        for model in ('opus', 'opus[1m]', 'custom-claude-model'):
            req = self.request()
            req.update(provider='claude', account_id='default-claude', model=model, effort='ultra')
            with patch.object(b.Manager, 'account_ready', return_value=True):
                with self.assertRaises(ValueError):
                    self.manager.validate(req)

    def test_update_account_preserves_identity_and_credentials(self):
        a = self.manager.create_account('Staging', 'ollama', 'http://127.0.0.1:11436')
        marker = Path(a['home']) / 'credentials.json'
        marker.write_text('test-secret')
        before = self.manager.store.read_bytes()
        self.manager.update_account(a['id'], 'Renamed', 'http://localhost:11436/')
        actual = b.Manager(self.home).account(a['id'])
        self.assertEqual(actual, dict(a, name='Renamed', endpoint='http://localhost:11436'))
        self.assertEqual(marker.read_text(), 'test-secret')
        self.assertEqual(self.manager.store.read_bytes(), before)
        raw = self.manager.registry.read_bytes()
        for identity, name, endpoint in [(a['id'], '', None), (a['id'], 'Bad', 'file:///tmp'),
                                         ('default-ollama', 'Builtin', None)]:
            with self.assertRaises(ValueError):
                self.manager.update_account(identity, name, endpoint)
            self.assertEqual(self.manager.registry.read_bytes(), raw)
        other = self.manager.create_account('Other', 'ollama')
        with self.assertRaises(ValueError):
            self.manager.update_account(a['id'], other['name'])

    def test_new_profiles_never_copy_tokens(self):
        for provider in ('codex', 'claude', 'grok'):
            a = self.manager.create_account('Test account', provider)
            self.assertFalse((Path(a['home'])/'auth.json').exists())
            command, env = self.manager.login_plan(a['id'])
            self.assertEqual(env[{'codex':'CODEX_HOME','claude':'CLAUDE_CONFIG_DIR','grok':'GROK_HOME'}[provider]], a['home'])
            self.assertNotIn('--console', command)

    @unittest.skipUnless(HAS_PRIVATE_MODES, 'filesystem cannot enforce POSIX owner-only mode bits')
    def test_profiles_and_backups_have_private_modes(self):
        self.manager.apply(self.request())
        backups = list(self.manager.root.glob('backups/*/*'))
        self.assertTrue(backups)
        for path in backups:
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        for provider in ('codex', 'claude', 'grok'):
            account = self.manager.create_account('Private profile', provider)
            self.assertEqual(Path(account['home']).stat().st_mode & 0o777, 0o700)
    def test_auth_environment_isolation(self):
        original = dict(HOME='/wrong', GROK_AUTH='test', ANTHROPIC_AUTH_TOKEN='test',
                        OPENAI_API_KEY='test', CLAUDE_SECURESTORAGE_CONFIG_DIR='/wrong',
                        CODEX_HOME='/wrong', GROK_HOME='/wrong', CLAUDE_CONFIG_DIR='/wrong',
                        BUZZ_PRIVATE_KEY='keep-identity', BUZZ_ACP_MODEL='keep-model')
        for provider in ('codex', 'claude', 'grok'):
            a = self.manager.create_account('isolated', provider)
            env = self.manager.auth_env(a, original)
            self.assertFalse(any(k in env for k in b.AUTH_OVERRIDES))
            self.assertEqual(env['BUZZ_PRIVATE_KEY'], 'keep-identity')
            self.assertEqual(env['BUZZ_ACP_MODEL'], 'keep-model')
            key = {'codex':'CODEX_HOME','claude':'CLAUDE_CONFIG_DIR','grok':'GROK_HOME'}[provider]
            self.assertEqual(env[key], a['home'])
            self.assertEqual(sum(k in env for k in ('CODEX_HOME','CLAUDE_CONFIG_DIR','GROK_HOME')), 1)
    def test_launch_native_effort_and_default_auth(self):
        self.manager.apply(self.request())
        for provider, command in b.CLI_COMMAND.items():
            if provider == 'ollama':
                continue
            a = self.manager.create_account('launch account', provider)
            path = self.manager.root / ('agent-' + self.pk + '.json')
            profile = b.read_json(path);profile['account_ids'][provider] = a['id'];profile['active_provider'] = provider;b.write_json(path, profile)
            env = dict(BUZZ_PRIVATE_KEY='test-identity', BUZZ_ACP_AGENT_COMMAND=command,
                       BUZZ_ACP_MODEL='selected', BUZZ_ACP_EFFORT_LEVEL='high', BUZZ_ACP_AGENT_ARGS='agent,stdio')
            with patch.dict(os.environ, env, clear=True), capture_launch(b) as execute:
                launch(self, self.manager, 'agent-' + self.pk, [])
                actual = execute.call_args.args[2]
                self.assertEqual(actual['BUZZ_PRIVATE_KEY'], 'test-identity')
                if provider == 'codex':self.assertEqual(json.loads(actual['CODEX_CONFIG'])['model_reasoning_effort'], 'high')
                if provider == 'claude':self.assertEqual(actual['CLAUDE_CODE_EFFORT_LEVEL'], 'high')
                if provider == 'grok':self.assertTrue(actual['BUZZ_ACP_AGENT_ARGS'].startswith('--model,selected,--reasoning-effort,high,'))
    def test_model_args_preserve_permission_flags(self):
        self.assertEqual(b.clean_model_args(['agent','--model','old','--always-approve','--effort=low','stdio']), ['agent','--always-approve','stdio'])
    def test_default_effort_clears_stale_native_override(self):
        self.manager.apply(self.request())
        env = dict(BUZZ_PRIVATE_KEY='test', BUZZ_ACP_AGENT_COMMAND='codex-acp', CODEX_CONFIG='{"model_reasoning_effort":"ultra"}')
        with patch.dict(os.environ, env, clear=True), capture_launch(b) as execute:
            launch(self, self.manager, 'agent-' + self.pk, [])
            self.assertNotIn('model_reasoning_effort', json.loads(execute.call_args.args[2]['CODEX_CONFIG']))
    def test_pruning_runs_after_successful_verification_with_deletion_enabled(self):
        verify = self.manager.verify_account_pin
        calls = []
        def verified(*args):
            verify(*args)
            calls.append('verified')
        def pruned(*args, **kwargs):
            self.assertEqual(calls, ['verified'])
            self.assertFalse(kwargs['dry_run'])
            self.assertTrue(kwargs['protected'].is_dir())
            calls.append('pruned')
        with patch.object(self.manager, 'verify_account_pin', side_effect=verified), patch.object(b, 'prune_backups', side_effect=pruned):
            self.manager.apply(self.request())
        self.assertEqual(calls, ['verified', 'pruned'])

    def test_failed_verification_does_not_prune(self):
        with patch.object(self.manager, 'verify_account_pin', side_effect=ValueError('fixture')), patch.object(b, 'prune_backups') as prune:
            with self.assertRaises(ValueError):
                self.manager.apply(self.request())
            prune.assert_not_called()

    def test_pruning_io_failure_does_not_fail_saved_settings(self):
        with patch.object(b, 'prune_backups', side_effect=OSError('fixture')):
            result = self.manager.apply(self.request())
        self.assertTrue(Path(result['backup']).is_dir())

    def test_failed_write_rolls_back(self):
        raw = self.manager.store.read_bytes()
        original = b.atomic_bytes
        failed = False
        def fail_once(path, data, mode=0o600):
            nonlocal failed
            if path == self.manager.store and not failed:
                failed = True
                raise OSError('test failure')
            return original(path, data, mode)
        with patch.object(b, 'atomic_bytes', side_effect=fail_once), patch.object(b, 'prune_backups') as prune:
            with self.assertRaises(ValueError) as result:self.manager.apply(self.request())
            prune.assert_not_called()
        self.assertIsInstance(result.exception.__cause__, OSError)
        self.assertEqual(self.manager.store.read_bytes(), raw)
        self.assertFalse((self.manager.root / ('agent-' + self.pk + '.json')).exists())

    def test_first_payload_write_failure_reports_no_changes(self):
        backend = self.manager.root / 'manager-backend.py'
        backend.write_bytes(b'previous backend')
        originals = {p: p.read_bytes() for p in self.manager.root.iterdir() if p.is_file()}
        raw = self.manager.store.read_bytes()
        original = b.atomic_bytes
        failure = PermissionError('private fixture detail')
        payload_attempts = []

        def fail_first_payload(path, data, mode=0o600):
            if path.parent == self.manager.root or path == self.manager.store:
                payload_attempts.append(path)
                raise failure
            return original(path, data, mode)

        with patch.object(b, 'atomic_bytes', side_effect=fail_first_payload):
            with self.assertRaisesRegex(ValueError, '파일을 변경하지 않았습니다') as result:
                self.manager.apply(self.request())
        self.assertIs(result.exception.__cause__, failure)
        self.assertNotIn('변경한 파일을 복원했습니다', str(result.exception))
        self.assertNotIn('private fixture detail', str(result.exception))
        self.assertEqual(payload_attempts, [backend])
        self.assertEqual(self.manager.store.read_bytes(), raw)
        # Acquiring the save lock creates .manager.lock before payload writes.
        self.assertEqual({p: p.read_bytes() for p in self.manager.root.iterdir()
                          if p.is_file() and p.name != '.manager.lock'}, originals)

    def test_rollback_continues_after_restore_failure_and_skips_unwritten_files(self):
        backend = self.manager.root / 'manager-backend.py'
        profile = self.manager.root / ('agent-' + self.pk + '.json')
        backend.write_bytes(b'previous backend')
        profile.write_bytes(b'{}')
        raw = self.manager.store.read_bytes()
        original = b.atomic_bytes
        store_writes = []
        failure = OSError('save fixture failure')

        def fail_save_and_one_restore(path, data, mode=0o600):
            if path == self.manager.store:
                store_writes.append(path)
                raise failure
            if path == profile and data == b'{}':
                raise OSError('restore fixture failure')
            return original(path, data, mode)

        with patch.object(b, 'atomic_bytes', side_effect=fail_save_and_one_restore):
            with self.assertRaisesRegex(ValueError, '일부 파일을 복원하지 못했습니다') as result:
                self.manager.apply(self.request())
        self.assertIs(result.exception.__cause__, failure)
        self.assertIn('복원 실패: ' + profile.name, str(result.exception))
        self.assertIn('백업: ' + str(self.manager.root / 'backups'), str(result.exception))
        self.assertNotIn('save fixture failure', str(result.exception))
        self.assertEqual(store_writes, [self.manager.store])
        self.assertEqual(self.manager.store.read_bytes(), raw)
        self.assertEqual(backend.read_bytes(), b'previous backend')
        suffix = '.exe' if os.name == 'nt' else ''
        self.assertFalse((self.manager.root / ('launch-agent-' + self.pk + suffix)).exists())
        self.assertNotEqual(profile.read_bytes(), b'{}')
        backups = list((self.manager.root / 'backups').iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / ('1-' + profile.name)).read_bytes(), b'{}')

    @contextlib.contextmanager
    def locked_windows_launcher(self, path):
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                      ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.restype = ctypes.c_int
        # Read sharing only: replacing this file must fail on native Windows.
        handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            kernel.CloseHandle(handle)

    @unittest.skipUnless(os.name == 'nt', 'native Windows sharing semantics')
    def test_unchanged_locked_windows_launcher_can_save(self):
        self.manager.apply(self.request())
        launcher = self.manager.root / ('launch-agent-' + self.pk + '.exe')
        before = launcher.read_bytes()
        with self.locked_windows_launcher(launcher):
            req = self.request()
            req['effort'] = 'medium'
            self.manager.apply(req)
        self.assertEqual(launcher.read_bytes(), before)
        self.assertEqual(b.read_json(self.manager.store)[1]['effort_level'], 'medium')

    @unittest.skipUnless(os.name == 'nt', 'native Windows sharing semantics')
    def test_changed_locked_windows_launcher_fails_before_any_payload_write(self):
        self.manager.apply(self.request())
        launcher = self.manager.root / ('launch-agent-' + self.pk + '.exe')
        backend = self.manager.root / 'manager-backend.py'
        backend.write_bytes(b'previous backend')
        originals = {p: p.read_bytes() for p in self.manager.root.iterdir() if p.is_file()}
        raw = self.manager.store.read_bytes()
        with self.locked_windows_launcher(launcher), \
             patch.object(b.win, 'launcher_bytes', return_value=b'MZ-updated-fixture'), \
             patch.object(b, 'atomic_bytes', wraps=b.atomic_bytes) as writes:
            req = self.request()
            req['effort'] = 'medium'
            with self.assertRaisesRegex(ValueError, '파일이 사용 중이거나 쓰기 권한') as result:
                self.manager.apply(req)
            writes.assert_not_called()
        self.assertIsInstance(result.exception.__cause__, PermissionError)
        self.assertIn(result.exception.__cause__.winerror, (5, 32, 33))
        self.assertEqual(self.manager.store.read_bytes(), raw)
        for path, data in originals.items():
            self.assertEqual(path.read_bytes(), data, path.name)

    @unittest.skipUnless(os.name == 'nt', 'native Windows executable image locking')
    def test_running_windows_launcher_image_unchanged_save_and_changed_preflight(self):
        import subprocess
        executable = Path(os.environ['SystemRoot']) / 'System32/cmd.exe'
        image = executable.read_bytes()
        with patch.object(b.win, 'launcher_bytes', return_value=image):
            self.manager.apply(self.request())
            launcher = self.manager.root / ('launch-agent-' + self.pk + '.exe')
            # This fixture only waits on its private stdin. It never invokes Buzz.
            process = subprocess.Popen([str(launcher), '/d', '/q', '/c', 'set /p fixture='],
                                       stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                self.assertIsNone(process.poll())
                req = self.request(); req['effort'] = 'medium'
                self.manager.apply(req)
                self.assertEqual(b.read_json(self.manager.store)[1]['effort_level'], 'medium')
                raw = self.manager.store.read_bytes()
                with patch.object(b.win, 'launcher_bytes', return_value=b'MZ-new-image'), \
                     patch.object(b, 'atomic_bytes', wraps=b.atomic_bytes) as writes:
                    with self.assertRaisesRegex(ValueError, '파일이 사용 중이거나 쓰기 권한') as result:
                        self.manager.apply(self.request())
                    writes.assert_not_called()
                self.assertIsInstance(result.exception.__cause__, PermissionError)
                self.assertIn('아직 종료되지 않은 에이전트: 1', str(result.exception))
                self.assertIn(launcher.name, str(result.exception))
                self.assertEqual(self.manager.store.read_bytes(), raw)
                self.assertEqual(launcher.read_bytes(), image)
                self.assertIsNone(process.poll())
            finally:
                process.terminate()
                process.wait(timeout=10)
                process.stdin.close()

    def test_identical_payload_files_are_not_replaced(self):
        self.manager.apply(self.request())
        with patch.object(b, 'atomic_bytes', wraps=b.atomic_bytes) as writes:
            self.manager.apply(self.request())
        # Backup metadata can be written, but no managed payload is replaced.
        payloads = [call.args[0] for call in writes.call_args_list
                    if self.manager.root / 'backups' not in call.args[0].parents]
        self.assertEqual(payloads, [])

    def test_provider_switch_does_not_add_auto_approval(self):
        req = self.request();req.update(provider='grok', account_id='default-grok', model='grok-test')
        with patch.object(b.Manager, 'account_ready', return_value=True):self.manager.apply(req)
        r = b.read_json(self.manager.store)[1]
        self.assertEqual(r['agent_args'], ['agent','stdio'])
        self.assertIsNone(r['provider'])
    def test_snapshot_does_not_return_authentication_values(self):
        with patch.object(b.Manager, 'account_ready', return_value=True):snapshot = self.manager.snapshot()
        text = json.dumps(snapshot)
        self.assertNotIn('test-only', text)
        self.assertNotIn('test-attestation', text)
        self.assertNotIn('preserve instructions', text)

if __name__ == '__main__':unittest.main()
