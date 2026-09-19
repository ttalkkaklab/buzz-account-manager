import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('backend', Path(__file__).resolve().parents[1] / 'Resources/backend.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
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
        self.assertEqual(updated[1]['env_vars'], {'KEEP_ME':'value'})
        self.assertTrue(Path(updated[1]['acp_command']).exists())
        for f in self.manager.root.glob('backups/*/*'):
            self.assertEqual(f.stat().st_mode & 0o777, 0o600)
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
        for model in self.manager.models('claude'):
            self.assertEqual(model['efforts'], levels)
        for level in levels:
            with self.subTest(effort=level):
                req = self.request()
                req.update(provider='claude', account_id='default-claude', model='opus', effort=level)
                with patch.object(b.Manager, 'account_ready', return_value=True):
                    self.manager.apply(req)
                self.assertEqual(b.read_json(self.manager.store)[1]['effort_level'], level)
                env = dict(BUZZ_PRIVATE_KEY='test-identity', BUZZ_ACP_AGENT_COMMAND='claude-agent-acp', BUZZ_ACP_MODEL='opus',
                           BUZZ_ACP_EFFORT_LEVEL=level)
                with patch.dict(os.environ, env, clear=True), patch.object(os, 'execve') as execute:
                    self.manager.launch('agent-' + self.pk, [])
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
            self.assertEqual(Path(a['home']).stat().st_mode & 0o777, 0o700)
            self.assertFalse((Path(a['home'])/'auth.json').exists())
            command, env = self.manager.login_plan(a['id'])
            self.assertEqual(env[{'codex':'CODEX_HOME','claude':'CLAUDE_CONFIG_DIR','grok':'GROK_HOME'}[provider]], a['home'])
            self.assertNotIn('--console', command)
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
            profile = b.read_json(path);profile['account_ids'][provider] = a['id'];b.write_json(path, profile)
            env = dict(BUZZ_PRIVATE_KEY='test-identity', BUZZ_ACP_AGENT_COMMAND=command,
                       BUZZ_ACP_MODEL='selected', BUZZ_ACP_EFFORT_LEVEL='high', BUZZ_ACP_AGENT_ARGS='agent,stdio')
            with patch.dict(os.environ, env, clear=True), patch.object(os, 'execve') as execute:
                self.manager.launch('agent-' + self.pk, [])
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
        with patch.dict(os.environ, env, clear=True), patch.object(os, 'execve') as execute:
            self.manager.launch('agent-' + self.pk, [])
            self.assertNotIn('model_reasoning_effort', json.loads(execute.call_args.args[2]['CODEX_CONFIG']))
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
        with patch.object(b, 'atomic_bytes', side_effect=fail_once):
            with self.assertRaises(OSError):self.manager.apply(self.request())
        self.assertEqual(self.manager.store.read_bytes(), raw)
        self.assertFalse((self.manager.root / ('agent-' + self.pk + '.json')).exists())
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
