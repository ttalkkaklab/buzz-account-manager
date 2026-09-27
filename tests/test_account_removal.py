"""Account removal never touches credentials or agent assignments."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('removal_backend', Path(__file__).resolve().parents[1] / 'Resources/backend.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class AccountRemovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.manager = b.Manager(Path(self.temp.name))
        b.write_json(self.manager.store, [])
        cli = patch.object(b.Manager, "resolve_cli", return_value="/test/cli")
        cli.start()
        self.addCleanup(cli.stop)

    def test_all_defaults_hide_persist_list_and_restore_without_auth_changes(self):
        defaults = self.manager.accounts()
        for account in defaults:
            auth = Path(account['home']) / 'auth.json'
            b.write_json(auth, {'fixture': 'keep'})
            before = auth.read_bytes()
            with patch.object(b.subprocess, 'run', side_effect=AssertionError('No Keychain or CLI mutation')):
                self.manager.delete_account(account['id'])
                self.assertEqual(auth.read_bytes(), before)
        restarted = b.Manager(self.manager.home)
        self.assertEqual(restarted.accounts(), [])
        self.assertEqual(restarted.accounts(include_hidden=True), defaults)
        with patch.object(b.Manager, 'account_ready', side_effect=AssertionError('Hidden auth lookup')):
            state = restarted.snapshot()
        self.assertEqual(state['accounts'], [])
        self.assertEqual(state['hidden_defaults'], defaults)
        for account in defaults:
            with self.assertRaises(ValueError): restarted.account(account['id'])
            restarted.restore_default(account['id'])
            self.assertEqual(restarted.account(account['id']), account)
        self.assertEqual(restarted.hidden_defaults(), [])

    def test_custom_account_removal_retains_credentials_and_other_accounts(self):
        account = self.manager.create_account('Fixture', 'codex')
        auth = Path(account['home']) / 'auth.json'
        b.write_json(auth, {'fixture': 'keep'})
        before = auth.read_bytes()
        self.manager.delete_account(account['id'])
        self.assertEqual(auth.read_bytes(), before)
        self.assertEqual(len(self.manager.accounts()), 4)
        self.assertEqual(self.manager.hidden_defaults(), [])
        with self.assertRaises(ValueError): self.manager.restore_default(account['id'])

    def test_primary_and_fallback_references_reject_without_changing_registry(self):
        account = self.manager.create_account('Fixture', 'codex')
        record = {'pubkey': 'a' * 64, 'name': 'Fixture', 'runtime': 'codex',
                  'acp_command': str(self.manager.root / 'launch-fixture')}
        b.write_json(self.manager.store, [record])
        for field, value in [('account_ids', account['id']), ('fallback_ids', [account['id']]),
                             ('account_ids', 'default-codex'), ('fallback_ids', ['default-codex'])]:
            target = value[0] if isinstance(value, list) else value
            b.write_json(self.manager.root / 'fixture.json', {field: {'codex': value}})
            before = self.manager.registry.read_bytes()
            with self.assertRaisesRegex(ValueError, '에이전트에 연결'): self.manager.delete_account(target)
            self.assertEqual(self.manager.registry.read_bytes(), before)

    def test_implicit_default_reference_cannot_be_hidden(self):
        b.write_json(self.manager.store, [{'pubkey': 'a' * 64, 'name': 'Fixture', 'runtime': 'codex'}])
        with self.assertRaisesRegex(ValueError, '에이전트에 연결'):
            self.manager.delete_account('default-codex')
        self.assertEqual(self.manager.hidden_defaults(), [])

    def test_custom_ollama_models_work_when_default_is_hidden(self):
        account = self.manager.create_account('Fixture server', 'ollama', 'http://127.0.0.1:11435')
        self.manager.delete_account('default-ollama')
        models = [dict(id='fixture-model', name='fixture-model', efforts=[], default_effort='')]
        with patch.object(self.manager, 'ollama_models', return_value=models) as query:
            self.assertEqual(self.manager.models('ollama', account['home']), models)
            query.assert_called_once_with(account)
        self.assertEqual(self.manager.models('ollama', '/missing'), [])
