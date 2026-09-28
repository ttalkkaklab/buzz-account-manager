import sandbox  # Isolate paths and guard writes before loading application code.
import os
from pathlib import Path
import tempfile
import unittest
from test_backend import b
from unittest.mock import patch
import windows_support as win

class CLIPathsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.roaming = self.home / 'roaming'
        for mocker in (
            patch.dict(os.environ, {'PATH': '', 'PATHEXT': '.COM;.EXE;.BAT;.CMD',
                                    'APPDATA': str(self.roaming),
                                    'LOCALAPPDATA': str(self.home / 'local'),
                                    'NoDefaultCurrentDirectoryInExePath': '1'}),
            patch.object(win, 'registered_paths', return_value=[]),
        ):
            mocker.start()
            self.addCleanup(mocker.stop)

    def adapter(self, folder, name):
        path = folder / (name + ('.cmd' if os.name == 'nt' else ''))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('@exit /b 0\n' if os.name == 'nt' else '#!/bin/sh\nexit 0\n')
        path.chmod(0o700)
        return path

    def test_buzz_managed_adapter_and_interpreter_are_discovered(self):
        manager = b.Manager(self.home)
        folder = (self.roaming / 'Buzz/node-tools' if os.name == 'nt'
                  else self.home / 'Library/Application Support/Buzz/node-tools/bin')
        adapter = self.adapter(folder, 'codex-acp')
        self.assertEqual(Path(manager.resolve_cli('codex-acp')), adapter)
        env = manager.auth_env(manager.account('default-codex'), {})
        self.assertIn(str(adapter.parent), env['PATH'].split(os.pathsep))

    def test_npm_global_adapter_is_discovered(self):
        manager = b.Manager(self.home)
        folder = self.roaming / 'npm' if os.name == 'nt' else self.home / '.npm-global/bin'
        adapter = self.adapter(folder, 'claude-agent-acp')
        self.assertEqual(Path(manager.resolve_cli('claude-agent-acp')), adapter)

    @unittest.skipUnless(os.name == 'nt', 'Windows PATH and registry discovery boundary')
    def test_missing_fixture_does_not_discover_host_adapter(self):
        manager = b.Manager(self.home)
        self.assertTrue(all(Path(folder).is_relative_to(self.home)
                            for folder in manager.executable_path().split(os.pathsep)))
        for name in ('codex-acp', 'claude-agent-acp'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                manager.resolve_cli(name)
