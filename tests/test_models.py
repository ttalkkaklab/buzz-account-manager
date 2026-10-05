"""Model selection without live subscriptions or inference requests."""
import sandbox
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from platform_fixtures import installed_launcher
from test_backend import b


class ModelCatalogTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.manager = b.Manager(self.home)
        installed_launcher(self, self.home)
        cli = patch.object(self.manager, 'resolve_cli', return_value='/fixture/adapter')
        cli.start()
        self.addCleanup(cli.stop)

    def catalog(self, provider='codex', home=None):
        rows = self.manager.models(provider, home)
        self.assertEqual(len(rows), len({row['id'] for row in rows}))
        return {row['id']: row for row in rows}

    def test_current_models_are_available_without_cli_cache_or_network(self):
        with patch.object(b.subprocess, 'Popen', side_effect=AssertionError('must stay offline')), \
                patch.object(b.urllib.request, 'urlopen', side_effect=AssertionError('must stay offline')):
            codex = self.catalog()
            claude = self.catalog('claude')
        self.assertTrue({'gpt-6.1-sol', 'gpt-6-astra', 'gpt-6-sol', 'gpt-6-luna',
                         'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5'} <= codex.keys())
        self.assertTrue({'fable', 'opus', 'sonnet', 'haiku', 'best', 'default', 'opusplan', 'opus[1m]',
                         'sonnet[1m]', 'claude-fable-5-1', 'claude-opus-5-5', 'claude-sonnet-5-5',
                         'claude-fable-5', 'claude-opus-5', 'claude-sonnet-5', 'claude-opus-4-8',
                         'claude-opus-4-7', 'claude-opus-4-6', 'claude-sonnet-4-6',
                         'claude-opus-4-5-20251101', 'claude-sonnet-4-5-20250929',
                         'claude-haiku-4-5-20251001'} <= claude.keys())
        self.assertNotIn('gpt-5.3-codex-spark', codex)  # Retired, not an offline suggestion.

    def test_caches_merge_and_selected_account_metadata_wins(self):
        account = self.manager.create_account('Work', 'codex')
        b.write_json(Path(account['home']) / 'models_cache.json', {'models': [
            {'slug': 'gpt-6-astra', 'display_name': 'Account Astra', 'default_reasoning_level': 'high',
             'supported_reasoning_levels': [{'effort': 'medium'}, {'effort': 'high'}]},
            {'slug': 'account-preview', 'supported_reasoning_levels': []},
        ]})
        b.write_json(self.home / '.codex/models_cache.json', {'models': [
            {'slug': 'gpt-6-astra', 'supported_reasoning_levels': [{'effort': 'low'}]},
            {'slug': 'new-cli-model', 'supported_reasoning_levels': [{'effort': 'max'}]},
            {'slug': 'internal-model', 'visibility': 'hide'},
        ]})
        catalog = self.catalog(home=account['home'])
        self.assertIn('gpt-6.1-sol', catalog)
        self.assertIn('account-preview', catalog)
        self.assertIn('new-cli-model', catalog)
        self.assertNotIn('internal-model', catalog)
        self.assertEqual(catalog['gpt-6-astra'], dict(id='gpt-6-astra', name='Account Astra',
                                                   efforts=['medium', 'high'], default_effort='high'))
        self.assertEqual(catalog['account-preview']['efforts'], [])

    def test_bad_cache_and_bad_rows_do_not_remove_other_models(self):
        cache = self.home / '.codex/models_cache.json'
        cache.parent.mkdir()
        for content in ('broken json', 'null', '[]', '{"models":{}}'):
            with self.subTest(content=content):
                cache.write_text(content)
                self.assertIn('gpt-6.1-sol', self.catalog())
        b.write_json(cache, {'models': [None, {}, {'slug': []}, {'slug': 'bad id'},
            {'slug': 'gpt-6-luna', 'display_name': [], 'supported_reasoning_levels': [None]},
            {'slug': 'valid-preview', 'supported_reasoning_levels': [{'effort': 'high'}]},
        ]})
        catalog = self.catalog()
        self.assertIn('valid-preview', catalog)
        self.assertEqual(catalog['gpt-6-luna']['efforts'], ['low', 'medium', 'high', 'xhigh', 'max'])
        self.assertEqual(catalog['gpt-6-luna']['name'], 'GPT-6 Luna')
        with patch.object(b, 'read_json', side_effect=PermissionError('unreadable cache')):
            self.assertIn('gpt-6.1-sol', self.catalog())

    def test_every_suggested_model_validates_with_its_efforts(self):
        with patch.object(self.manager, 'account_ready', return_value=True), \
                patch.object(self.manager, 'resolve_cli', return_value='/fixture/adapter'):
            for provider in ('codex', 'claude'):
                for model in self.catalog(provider).values():
                    for effort in ['', *model['efforts']]:
                        with self.subTest(provider=provider, model=model['id'], effort=effort):
                            self.manager.validate(dict(account_id='default-' + provider, provider=provider,
                                                       model=model['id'], effort=effort))

    def test_model_specific_efforts_and_invalid_ids_are_rejected_before_writes(self):
        with patch.object(self.manager, 'account_ready', return_value=True):
            for provider, model, effort in (
                    ('codex', 'gpt-6-luna', 'ultra'), ('codex', 'gpt-5.5', 'max'),
                    ('claude', 'claude-sonnet-4-6', 'xhigh'), ('claude', 'haiku', 'high'),
                    ('claude', 'claude-haiku-4-5-20251001', 'medium'),
                    ('claude', 'claude-sonnet-5-5', 'ultra'), ('claude', 'future-model', 'ultra'),
                    ('codex', 'model; command', ''), ('codex', 'x' * 181, ''), ('claude', '', '')):
                with self.subTest(model=model, effort=effort), self.assertRaises(ValueError):
                    self.manager.apply(dict(account_id='default-' + provider, provider=provider,
                                            model=model, effort=effort))
        self.assertFalse((self.manager.root / 'backups').exists())

    def test_latest_versions_save_to_instance_and_definition_and_snapshot(self):
        pk = 'a' * 64
        b.write_json(self.manager.store, [dict(name='Agent', pubkey=pk, persona_id='role', runtime='codex'),
                                         dict(name='Role', slug='role', runtime='codex')])
        with patch.object(self.manager, 'account_ready', return_value=True), \
                patch.object(self.manager, 'resolve_cli', return_value='/fixture/adapter'), \
                patch.object(self.manager, 'buzz_running', return_value=False), \
                patch.object(self.manager, 'ollama_models', return_value=[]):
            for provider, model in (('codex', 'gpt-6.1-sol'), ('codex', 'gpt-6-luna'),
                                    ('claude', 'claude-fable-5-1'), ('claude', 'claude-opus-5-5'),
                                    ('claude', 'claude-sonnet-5-5'), ('claude', 'opus[1m]')):
                with self.subTest(model=model):
                    self.manager.apply(dict(agent_id=pk, account_id='default-' + provider,
                        provider=provider, model=model, effort='high',
                        revision=b.revision(self.manager.store.read_bytes())))
                    records = b.read_json(self.manager.store)
                    instance = next(r for r in records if r.get('pubkey') == pk)
                    definition = next(r for r in records if r.get('slug') == instance['persona_id'])
                    self.assertEqual(instance['model'], model)
                    self.assertEqual(definition['model'], model)
                    self.assertEqual(instance['effort_level'], 'high')
                    self.assertEqual(self.manager.snapshot()['agents'][0]['model'], model)

    def test_local_server_catalog_does_not_gain_cloud_suggestions(self):
        account = self.manager.create_account('Local', 'codex', 'http://localhost:12345')
        with patch.object(self.manager, 'local_codex_catalog', return_value=[{'id': 'local-only'}]):
            self.assertEqual(list(self.catalog(home=account['home'])), ['local-only'])
        with patch.object(self.manager, 'local_codex_catalog', return_value=None):
            self.assertEqual(self.catalog(home=account['home']), {})
