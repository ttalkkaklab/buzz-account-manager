"""Separate real generated launchers in temporary HOME; never start Buzz."""
import sandbox  # Isolate paths and guard writes before loading application code.
import copy
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import test_account_pin as fixture

b = fixture.b


class SharedDefinitionTests(unittest.TestCase):
    def setUp(self):
        fixture.AccountPinTests.setUp(self)
        self.definition.update(slug='builtin:fizz', is_builtin=True, shared=True,
                               source_team_persona_slug='old-public-slug',
                               catalog_source={'author': 'original', 'd_tag': 'old-public-slug'},
                               system_prompt='keep definition prompt',
                               env_vars={'KEEP_DEFINITION': 'yes', 'ANTHROPIC_MODEL': 'old'},
                               definition_parallelism=5, session_policy='channel',
                               definition_respond_to='allowlist', definition_respond_to_allowlist=['owner'])
        self.record['persona_id'] = self.sibling['persona_id'] = 'builtin:fizz'
        self.original = copy.deepcopy([self.definition, self.record, self.sibling])
        b.write_json(self.manager.store, self.original)
        self.accounts = [self.manager.create_account('seat-' + str(i), 'codex') for i in range(2)]

    def save(self, index=0):
        record = self.original[index + 1]
        req = dict(agent_id=record['pubkey'], account_id=self.accounts[index]['id'], provider='codex',
                   model='model-' + str(index), effort='high', revision=b.revision(self.manager.store.read_bytes()))
        return self.manager.apply(req)

    @unittest.skipIf(os.name == 'nt', 'POSIX generated launcher')
    def test_two_saved_seats_restore_and_execute_their_own_accounts(self):
        harness = self.manager.home / '.buzz/bin/buzz-acp-persistent'
        harness.parent.mkdir(parents=True)
        harness.write_text('#!/usr/bin/python3\nimport json,os\n'
                           'keys=["CODEX_HOME","CODEX_CONFIG","BUZZ_PRIVATE_KEY","BUZZ_ACP_MODEL"]\n'
                           'print(json.dumps({k:os.environ.get(k) for k in keys}))\n')
        harness.chmod(0o700)
        self.save(0)
        first = b.read_json(self.manager.store)
        self.assertEqual(first[:1] + first[2:3], [self.original[0], self.original[2]])
        dedicated = first[-1]
        self.assertNotEqual(dedicated['slug'], 'builtin:fizz')
        self.assertLessEqual(len(dedicated['slug']), 64)
        self.assertFalse(dedicated['is_builtin'])
        self.assertFalse(dedicated['shared'])
        for key in ('source_team_persona_slug', 'catalog_source', 'source_team', 'team_catalog_source'):
            self.assertIsNone(dedicated[key])
        for key in ('system_prompt', 'definition_parallelism', 'session_policy',
                    'definition_respond_to', 'definition_respond_to_allowlist'):
            self.assertEqual(dedicated[key], self.definition[key])
        self.assertEqual(dedicated['env_vars'], {'KEEP_DEFINITION': 'yes'})
        self.save(1)
        self.save(0)  # Repeated saves reuse the seat's definition.
        records = b.read_json(self.manager.store)
        self.assertEqual(len(records), 5)
        self.assertEqual(records[0], self.original[0])
        instances = [r for r in records if r.get('pubkey')]
        self.assertNotEqual(instances[0]['persona_id'], instances[1]['persona_id'])
        for i, record in enumerate(instances):
            definition = next(r for r in records if not r.get('pubkey') and r['slug'] == record['persona_id'])
            # External Buzz 0.5.25 snapshot contract, persona_events.rs:634-639:
            # replace the transport from the linked definition, stock if absent.
            record.update(acp_command=definition.get('acp_command') or 'buzz-acp',
                          runtime=definition['runtime'], model=definition['model'])
            self.assertEqual(record['acp_command'], str(self.manager.root / ('launch-agent-' + record['pubkey'])))
            for key in ('pubkey', 'team_id', 'auth_tag', 'parallelism', 'env_vars'):
                self.assertEqual(record.get(key), self.original[i + 1].get(key))
            env = dict(os.environ, HOME=str(self.manager.home), BUZZ_PRIVATE_KEY='identity-' + str(i),
                       BUZZ_ACP_AGENT_COMMAND=record['agent_command_override'], BUZZ_ACP_MODEL=record['model'],
                       BUZZ_ACP_EFFORT_LEVEL=record['effort_level'], CODEX_HOME='/wrong')
            result = subprocess.run([record['acp_command']], env=env, capture_output=True, text=True, check=True)
            actual = json.loads(result.stdout)
            self.assertEqual(actual['CODEX_HOME'], self.accounts[i]['home'])
            self.assertEqual(actual['BUZZ_PRIVATE_KEY'], 'identity-' + str(i))
            self.assertEqual(actual['BUZZ_ACP_MODEL'], 'model-' + str(i))
            self.assertEqual(json.loads(actual['CODEX_CONFIG'])['model_reasoning_effort'], 'high')

    def test_single_builtin_keeps_original_record_bytes_and_gets_dedicated_definition(self):
        def first_record_bytes():
            raw = self.manager.store.read_text()
            start = raw.index('{')
            _, end = json.JSONDecoder().raw_decode(raw, start)
            return raw[start:end].encode('utf-8')

        for slug, flag in [('builtin:fizz', True), ('builtin:fizz', False), ('legacy-built-in', True)]:
            with self.subTest(slug=slug, is_builtin=flag):
                definition = dict(self.original[0], slug=slug, is_builtin=flag)
                record = dict(self.original[1], persona_id=slug)
                b.write_json(self.manager.store, [definition, record])
                before = first_record_bytes()
                self.save()
                saved = b.read_json(self.manager.store)
                self.assertEqual(first_record_bytes(), before)
                self.assertEqual(len(saved), 3)
                self.assertRegex(saved[1]['persona_id'], r'^account-[0-9a-f]{32}$')
                self.assertEqual(saved[2]['slug'], saved[1]['persona_id'])
                self.assertEqual(saved[2]['acp_command'], saved[1]['acp_command'])
                self.assertFalse(saved[2]['is_builtin'])
                self.save()  # A dedicated non-builtin definition is reused.
                self.assertEqual(first_record_bytes(), before)
                self.assertEqual(len(b.read_json(self.manager.store)), 3)

    def test_inactive_sibling_is_also_protected(self):
        records = copy.deepcopy(self.original)
        records[2]['is_active'] = False
        b.write_json(self.manager.store, records)
        self.save()
        saved = b.read_json(self.manager.store)
        self.assertEqual(saved[0], records[0])
        self.assertEqual(saved[2], records[2])
        self.assertNotEqual(saved[1]['persona_id'], saved[2]['persona_id'])

    def test_invalid_or_team_managed_definitions_refuse_before_writes(self):
        cases = [self.original[1:], [self.original[0]] + self.original,
                 [dict(self.original[0], source_team='team')] + self.original[1:],
                 [dict(self.original[0], team_catalog_source={'team': 'foreign'})] + self.original[1:]]
        for records in cases:
            with self.subTest(records=records):
                b.write_json(self.manager.store, records)
                before = self.manager.store.read_bytes()
                with self.assertRaisesRegex(ValueError, '정의'):
                    self.save()
                self.assertEqual(self.manager.store.read_bytes(), before)
                self.assertFalse((self.manager.root / 'backups').exists())
                self.assertFalse((self.manager.root / 'manager-backend.py').exists())

    def test_dedicated_slug_collision_refuses_without_overwriting(self):
        from types import SimpleNamespace
        records = self.original + [dict(pubkey='', slug='account-collision', name='Existing')]
        b.write_json(self.manager.store, records)
        with patch.object(b.uuid, 'uuid4', return_value=SimpleNamespace(hex='collision')):
            with self.assertRaisesRegex(ValueError, '이름이 겹칩니다'):
                self.save()
        self.assertEqual(b.read_json(self.manager.store), records)

    def test_readback_detects_instance_definition_relink_and_parse_failures(self):
        original_write = b.atomic_bytes
        for mode in ('instance', 'definition', 'relink', 'sibling', 'invalid-json', 'missing-store'):
            with self.subTest(mode=mode):
                b.write_json(self.manager.store, self.original)
                foreign_bytes = None
                def interfere(path, data, permissions=0o600):
                    nonlocal foreign_bytes
                    original_write(path, data, permissions)
                    if path != self.manager.store:
                        return
                    if mode == 'missing-store':
                        path.unlink()
                        return
                    rows = json.loads(data)
                    if mode == 'instance':
                        rows[1]['acp_command'] = 'buzz-acp'
                    elif mode == 'definition':
                        rows[-1]['acp_command'] = 'buzz-acp'
                    elif mode == 'relink':
                        rows[1]['persona_id'] = 'builtin:fizz'
                    elif mode == 'sibling':
                        rows[2]['persona_id'] = rows[1]['persona_id']
                    foreign_bytes = b'{' if mode == 'invalid-json' else json.dumps(rows).encode()
                    original_write(path, foreign_bytes, permissions)
                with patch.object(b, 'atomic_bytes', side_effect=interfere):
                    with self.assertRaisesRegex(ValueError, '저장 뒤 계정 연결'):
                        self.save()
                # Detection must not overwrite the unexpected external store.
                if foreign_bytes is not None:
                    self.assertEqual(self.manager.store.read_bytes(), foreign_bytes)
                self.assertTrue(list((self.manager.root / 'backups').glob('*/manifest.json')))

    def test_write_failure_rolls_back_split_and_preserves_installed_files(self):
        paths = [self.manager.root / 'manager-backend.py',
                 self.manager.root / ('agent-' + self.pk + '.json'),
                 self.manager.root / ('launch-agent-' + self.pk)]
        for path in paths:
            path.write_text('existing file')
        before = self.manager.store.read_bytes()
        original_write = b.atomic_bytes
        failed = False
        def fail_once(path, data, mode=0o600):
            nonlocal failed
            if path == self.manager.store and not failed:
                failed = True
                raise OSError('simulated write failure')
            original_write(path, data, mode)
        # Existing profile must remain valid while apply plans the update.
        b.write_json(paths[1], dict(pubkey=self.pk, account_ids={'codex': self.accounts[0]['id']}))
        originals = [p.read_bytes() for p in paths]
        with patch.object(b, 'atomic_bytes', side_effect=fail_once):
            with self.assertRaises(OSError):
                self.save()
        self.assertEqual(self.manager.store.read_bytes(), before)
        self.assertEqual([p.read_bytes() for p in paths], originals)
