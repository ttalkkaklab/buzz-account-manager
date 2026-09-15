import os
from pathlib import Path
import tempfile
import unittest
from test_backend import b

class CLIPathsTests(unittest.TestCase):
    def test_buzz_managed_adapter_and_interpreter_are_discovered(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = b.Manager(folder)
            adapter = Path(folder) / 'Library/Application Support/Buzz/node-tools/bin/codex-acp'
            adapter.parent.mkdir(parents=True)
            adapter.write_text('#!/bin/sh\nexit 0\n')
            adapter.chmod(0o700)
            self.assertEqual(manager.resolve_cli('codex-acp'), str(adapter))
            env = manager.auth_env(manager.account('default-codex'), {})
            self.assertIn(str(adapter.parent), env['PATH'].split(os.pathsep))

    def test_npm_global_adapter_is_discovered(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = b.Manager(folder)
            adapter = Path(folder) / '.npm-global/bin/claude-agent-acp'
            adapter.parent.mkdir(parents=True)
            adapter.write_text('#!/bin/sh\nexit 0\n')
            adapter.chmod(0o700)
            self.assertEqual(manager.resolve_cli('claude-agent-acp'), str(adapter))
