"""Regression checks for accidental writes through inherited Windows APPDATA."""
import sandbox
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_backend import b
import windows_support as win


class SandboxTests(unittest.TestCase):
    def test_subprocess_output_can_use_null_device(self):
        with open(os.devnull, 'wb') as output:
            output.write(b'fixture')

    def test_storage_environment_is_isolated_without_shell_setup(self):
        for key in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'TMP', 'TEMP'):
            self.assertTrue(Path(os.environ[key]).is_relative_to(sandbox.ROOT), key)
        with tempfile.TemporaryDirectory() as folder:
            self.assertTrue(Path(folder).is_relative_to(sandbox.ROOT))

    def test_windows_store_cannot_escape_through_appdata(self):
        # The checkout is outside the sandbox. The guard must reject before
        # creating this file, even if APPDATA is accidentally restored.
        outside = Path(__file__).resolve().parents[1] / 'escaped-appdata'
        with patch.dict(os.environ, APPDATA=str(outside)):
            path = win.store_path(sandbox.ROOT / 'home')
            with self.assertRaisesRegex(PermissionError, 'outside sandbox'):
                path.write_text('fixture')

    def test_atomic_replace_cannot_escape(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source'
            source.write_text('fixture')
            destination = Path(__file__).resolve().parents[1] / 'escaped-store.json'
            with self.assertRaisesRegex(PermissionError, 'outside sandbox'):
                os.replace(source, destination)
            self.assertEqual(source.read_text(), 'fixture')

    def test_atomic_writer_cannot_create_directories_outside_sandbox(self):
        outside = Path(__file__).resolve().parents[1] / 'escaped-appdata/store.json'
        with self.assertRaisesRegex(PermissionError, 'outside sandbox'):
            b.write_json(outside, [])

    def test_fresh_process_preserves_inherited_appdata_canary(self):
        with tempfile.TemporaryDirectory() as folder:
            canary = Path(folder) / 'xyz.block.buzz.app/agents/managed-agents.json'
            canary.parent.mkdir(parents=True)
            canary.write_text('preserve')
            before = hashlib.sha256(canary.read_bytes()).hexdigest()
            env = dict(os.environ, APPDATA=folder)
            code = '''
import os
inherited = os.environ['APPDATA']
import sandbox
import backend
import tempfile
from pathlib import Path
manager = backend.Manager(tempfile.mkdtemp())
backend.write_json(manager.store, [])
# Simulate the original mistake after bootstrap, including restoring APPDATA.
os.environ['APPDATA'] = inherited
import windows_support
try:
    backend.write_json(windows_support.store_path(Path(tempfile.mkdtemp())), [])
except PermissionError:
    print('escaped write blocked')
else:
    raise AssertionError('write escaped the test sandbox')
'''
            result = subprocess.run([sys.executable, '-B', '-c', code], env=env,
                                    cwd=Path(__file__).parent, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('escaped write blocked', result.stdout)
            self.assertEqual(hashlib.sha256(canary.read_bytes()).hexdigest(), before)
