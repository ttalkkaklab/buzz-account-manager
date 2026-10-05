"""Buzz may omit runtime while retaining a Claude command or linked definition."""
import sandbox  # Isolate paths and guard writes before loading application code.
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('runtime_backend', Path(__file__).resolve().parents[1] / 'Resources/backend.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class RuntimeResolutionTests(unittest.TestCase):
    def test_buzz_resolution_precedence(self):
        definition = dict(slug='builtin:honey', pubkey='', runtime='claude')
        cases = [
            ({'agent_command_override': 'claude-agent-acp'}, 'claude'),
            ({'runtime': 'codex', 'agent_command_override': '/Buzz/bin/claude-agent-acp'}, 'claude'),
            ({'runtime': 'codex', 'agent_command': 'claude-agent-acp'}, 'codex'),
            ({'persona_id': 'builtin:honey', 'agent_command': 'codex-acp'}, 'claude'),
            ({'agent_command': 'claude-code-acp'}, 'claude'),
            ({'agent_command_override': r'C:\Buzz\codex-acp.cmd'}, 'codex'),
            ({'agent_command_override': 'unknown', 'runtime': 'codex'}, None),
            ({}, None),
        ]
        for record, expected in cases:
            with self.subTest(record=record):
                self.assertEqual(b.Manager.effective_provider(record, [definition]), expected)

    def test_snapshot_and_delete_use_actual_claude_runtime(self):
        with tempfile.TemporaryDirectory() as home:
            manager = b.Manager(home)
            record = dict(pubkey='a' * 64, name='Developer', runtime=None,
                          agent_command_override='claude-agent-acp', model=None)
            b.write_json(manager.store, [record])
            with patch.object(manager, 'account_ready', return_value=False), \
                 patch.object(manager, 'models', return_value=[]), \
                 patch.object(manager, 'buzz_running', return_value=False):
                agent = manager.snapshot()['agents'][0]
            self.assertEqual(agent['provider'], 'claude')
            self.assertEqual(agent['account_id'], 'default-claude')
            with self.assertRaisesRegex(ValueError, '에이전트에 연결된 계정'):
                manager.delete_account('default-claude')
            manager.delete_account('default-codex')

    def test_runtime_drift_warns_even_when_launcher_is_still_linked(self):
        with tempfile.TemporaryDirectory() as home:
            manager = b.Manager(home)
            slug = 'agent-' + 'a' * 64
            record = dict(pubkey='a' * 64, name='Developer', runtime='codex',
                          agent_command_override='claude-agent-acp',
                          acp_command=str(manager.root / ('launch-' + slug)))
            b.write_json(manager.store, [record])
            b.write_json(manager.root / (slug + '.json'),
                         dict(active_provider='codex', account_ids={'codex': 'default-codex'}))
            with patch.object(manager, 'account_ready', return_value=False), \
                 patch.object(manager, 'models', return_value=[]), \
                 patch.object(manager, 'buzz_running', return_value=False):
                agent = manager.snapshot()['agents'][0]
            self.assertTrue(agent['account_connection_lost'])
            self.assertEqual(agent['provider'], 'codex')
