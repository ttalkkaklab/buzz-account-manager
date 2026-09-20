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
            a = self.manager.create_account('Local', 'codex', endpoint + '/v1/')
            self.assertEqual(a['endpoint'], endpoint)
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
                       OPENAI_API_KEY='must-not-reach-local', CODEX_CONFIG='{"model_provider":"openai"}')
            with patch.dict(os.environ, env, clear=True), patch.object(os, 'execve') as execute:
                self.manager.launch('agent-' + self.pk, [])
                runtime = execute.call_args.args[2]
                config = json.loads(runtime['CODEX_CONFIG'])
                self.assertEqual(runtime['CODEX_HOME'], a['home'])
                self.assertNotIn('OPENAI_API_KEY', runtime)
                self.assertEqual(config['model_provider'], 'local')
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
