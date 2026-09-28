"""Restart boundaries: temporary HOME, fake harness, no real credentials or login."""
import sandbox  # Isolate paths and guard writes before loading application code.
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('pin_backend', Path(__file__).resolve().parents[1] / 'Resources/backend.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class AccountPinTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.manager = b.Manager(self.temp.name)
        self.pk = 'a' * 64
        self.slug = 'agent-' + self.pk
        self.definition = dict(slug='shared', pubkey='', runtime='claude', name='Definition')
        self.record = dict(pubkey=self.pk, name='Fixture', runtime='claude', persona_id='shared',
                           model='opus', effort_level='high', team_id='team', auth_tag='fixture-attestation',
                           env_vars={'KEEP_ME': 'yes'}, agent_args=[])
        self.sibling = dict(self.record, pubkey='b' * 64)
        b.write_json(self.manager.store, [self.definition, self.record, self.sibling])
        for name, value in [('resolve_cli', None), ('account_ready', True), ('buzz_running', False)]:
            mocker = patch.object(b.Manager, name, **({'side_effect': lambda cmd: '/fixture/' + cmd} if value is None else {'return_value': value}))
            mocker.start()
            self.addCleanup(mocker.stop)

    def apply(self, provider):
        account = self.manager.create_account('fixture-' + provider, provider)
        req = dict(agent_id=self.pk, account_id=account['id'], provider=provider,
                   model='opus' if provider == 'claude' else 'fixture-model', effort='high',
                   revision=b.revision(self.manager.store.read_bytes()))
        self.manager.apply(req)
        return account, req

    @unittest.skipIf(os.name == 'nt', 'POSIX generated launcher')
    def test_saved_launcher_executes_in_fresh_process_with_pinned_account(self):
        harness = self.manager.home / '.buzz/bin/buzz-acp-persistent'
        harness.parent.mkdir(parents=True)
        harness.write_text('#!/usr/bin/python3\nimport os,json\n'
                           'keys=["CODEX_HOME","CLAUDE_CONFIG_DIR","CODEX_CONFIG",'
                           '"CLAUDE_CODE_EFFORT_LEVEL","BUZZ_PRIVATE_KEY","BUZZ_ACP_MODEL"]\n'
                           'print(json.dumps({k:os.environ.get(k) for k in keys}))\n')
        harness.chmod(0o700)
        for provider in ('codex', 'claude'):
            with self.subTest(provider=provider):
                account, req = self.apply(provider)
                records = b.read_json(self.manager.store)
                definition = next(r for r in records if not r.get('pubkey') and r['slug'] == records[1]['persona_id'])
                self.assertEqual(definition['runtime'], provider)
                self.assertEqual(definition['model'], req['model'])
                self.assertEqual(records[0], self.definition)
                self.assertEqual(records[2], self.sibling)
                record = records[1]
                self.assertEqual(record['agent_command_override'], '/fixture/' + b.CLI_COMMAND[provider])
                self.assertEqual(record['team_id'], 'team')
                self.assertEqual(record['auth_tag'], 'fixture-attestation')
                self.assertEqual(record['effort_level'], 'high')
                # Buzz re-snapshots the linked definition at restart. The saved
                # definition and explicit runtime pin must agree with the account.
                record.update(runtime=definition['runtime'], model=definition['model'],
                              acp_command=definition['acp_command'])
                incoming_command = record['agent_command_override']
                env = dict(os.environ, HOME=str(self.manager.home), BUZZ_PRIVATE_KEY='fixture-identity',
                           BUZZ_ACP_AGENT_COMMAND=incoming_command, BUZZ_ACP_MODEL=req['model'],
                           BUZZ_ACP_EFFORT_LEVEL='high', CODEX_HOME='/wrong', CLAUDE_CONFIG_DIR='/wrong')
                result = subprocess.run([record['acp_command']], env=env, capture_output=True, text=True, check=True)
                actual = json.loads(result.stdout)
                key = 'CODEX_HOME' if provider == 'codex' else 'CLAUDE_CONFIG_DIR'
                self.assertEqual(actual[key], account['home'])
                self.assertEqual(actual['BUZZ_PRIVATE_KEY'], 'fixture-identity')
                self.assertEqual(actual['BUZZ_ACP_MODEL'], req['model'])
                if provider == 'codex':
                    self.assertEqual(json.loads(actual['CODEX_CONFIG'])['cli_auth_credentials_store'], 'file')
                else:
                    self.assertEqual(actual['CLAUDE_CODE_EFFORT_LEVEL'], 'high')

    def test_wrong_or_unassigned_runtime_never_executes_default_account(self):
        self.apply('claude')
        path = self.manager.root / (self.slug + '.json')
        for active, accounts in [('claude', {'claude': 'fixture'}),
                                 ('codex', {}), (None, {})]:
            b.write_json(path, dict(pubkey=self.pk, active_provider=active, account_ids=accounts))
            with patch.dict(os.environ, {'BUZZ_PRIVATE_KEY': 'fixture', 'BUZZ_ACP_AGENT_COMMAND': 'codex-acp'}, clear=True), patch.object(os, 'execve') as execute:
                with self.assertRaises(ValueError):
                    self.manager.launch(self.slug, [])
                execute.assert_not_called()

    def test_lost_launcher_is_reported_and_resave_recovers_same_account(self):
        account, req = self.apply('codex')
        records = b.read_json(self.manager.store)
        records[1]['acp_command'] = 'buzz-acp'
        records[1]['agent_command_override'] = None
        b.write_json(self.manager.store, records)
        before = self.manager.store.read_bytes()
        restarted = b.Manager(self.manager.home)
        snapshot = restarted.snapshot()
        agent = next(a for a in snapshot['agents'] if a['id'] == self.pk)
        self.assertEqual(agent['account_id'], account['id'])
        self.assertTrue(agent['account_connection_lost'])
        self.assertEqual(restarted.store.read_bytes(), before)  # Inspection is read-only.
        with self.assertRaisesRegex(ValueError, '에이전트에 연결된 계정'):
            restarted.delete_account(account['id'])
        req.update(revision=snapshot['revision'], expected_account_id=account['id'])
        restarted.apply(req)
        agent = next(a for a in restarted.snapshot()['agents'] if a['id'] == self.pk)
        self.assertFalse(agent['account_connection_lost'])
        self.assertEqual(agent['account_id'], account['id'])
        self.assertEqual(b.read_json(restarted.store)[1]['agent_command_override'], '/fixture/codex-acp')

    def test_recovery_does_not_adopt_another_identity_profile(self):
        self.apply('codex')
        record = b.read_json(self.manager.store)[1]
        record['acp_command'] = 'buzz-acp'
        path = self.manager.root / (self.slug + '.json')
        data = b.read_json(path)
        data['pubkey'] = 'b' * 64
        b.write_json(path, data)
        self.assertEqual(self.manager.saved_profile(record), {})

    def test_explicit_default_selection_still_works(self):
        _, req = self.apply('codex')
        req.update(account_id='default-codex', revision=b.revision(self.manager.store.read_bytes()))
        self.manager.apply(req)
        with patch.dict(os.environ, {'BUZZ_PRIVATE_KEY': 'fixture', 'BUZZ_ACP_AGENT_COMMAND': 'codex-acp'}, clear=True), patch.object(os, 'execve') as execute:
            self.manager.launch(self.slug, [])
            self.assertEqual(execute.call_args.args[2]['CODEX_HOME'], str(self.manager.home / '.codex'))
