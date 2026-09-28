"""Regression checks for accidental writes through inherited Windows APPDATA."""
import sandbox
import ast
import contextlib
import hashlib
import os
from pathlib import Path
import re
import shutil
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


OUTSIDE = Path(__file__).resolve().parents[1]


class GuardTestCase(unittest.TestCase):
    """Shared fixtures for the escape checks.

    Every escape target is a checkout path that does not exist. The audit
    hook runs before the system call, so the refusal is what proves the
    guard, and nothing outside the sandbox is touched.
    """

    def sandboxed_file(self, name):
        path = Path(tempfile.mkdtemp()) / name
        path.write_text('fixture')
        return path

    @contextlib.contextmanager
    def refused_target(self, name):
        """A checkout path the guard must refuse.

        Nothing is ever created there while the guard holds, but a regressed
        guard would leave the artefact behind, so it is removed either way.
        """
        target = OUTSIDE / name
        try:
            yield target
        finally:
            with contextlib.suppress(OSError):
                if target.is_symlink() or target.exists():
                    target.unlink()


class DeletionGuardTests(GuardTestCase):
    """The guard has to refuse removals too, not only writes."""

    def test_file_removal_cannot_escape(self):
        for remove in (os.remove, os.unlink):
            with self.subTest(remove=remove.__name__):
                with self.assertRaisesRegex(PermissionError, 'outside sandbox'):
                    remove(OUTSIDE / 'escaped-remove')
        with self.assertRaisesRegex(PermissionError, 'outside sandbox'):
            (OUTSIDE / 'escaped-remove').unlink()

    def test_directory_removal_cannot_escape(self):
        with self.assertRaisesRegex(PermissionError, 'outside sandbox'):
            os.rmdir(OUTSIDE / 'escaped-rmdir')

    def test_truncation_cannot_escape(self):
        with self.assertRaisesRegex(PermissionError, 'outside sandbox'):
            os.truncate(OUTSIDE / 'escaped-truncate', 0)

    def test_symlink_cannot_escape(self):
        with self.refused_target('escaped-symlink') as destination:
            with self.assertRaisesRegex(PermissionError, 'outside sandbox'):
                os.symlink(sandbox.ROOT / 'home', destination)
            self.assertFalse(destination.is_symlink())

    def test_permission_change_cannot_escape(self):
        with self.assertRaisesRegex(PermissionError, 'outside sandbox'):
            os.chmod(OUTSIDE / 'escaped-chmod', 0o600)

    def test_hard_link_cannot_escape_in_either_direction(self):
        source = self.sandboxed_file('link-source')
        with self.refused_target('escaped-link') as destination:
            with self.assertRaisesRegex(PermissionError, 'outside sandbox'):
                os.link(source, destination)
            self.assertFalse(destination.exists())
        # Linking inwards would expose a checkout file to sandboxed writes,
        # because the sandboxed name then resolves inside the sandbox.
        with self.assertRaisesRegex(PermissionError, 'outside sandbox'):
            os.link(Path(__file__).resolve(), source.parent / 'escaped-target')

    def test_removal_through_a_directory_descriptor_cannot_escape(self):
        # shutil.rmtree walks POSIX trees with relative names against an open
        # directory. Resolving those against the working directory would let
        # the removal through whenever that directory sits in the sandbox.
        descriptor = os.open(OUTSIDE, os.O_RDONLY)
        try:
            with contextlib.chdir(sandbox.ROOT):
                expected = re.escape(str(OUTSIDE / 'escaped-dir-fd'))
                with self.assertRaisesRegex(PermissionError, expected):
                    os.remove('escaped-dir-fd', dir_fd=descriptor)
        finally:
            os.close(descriptor)

    def test_recursive_removal_inside_the_sandbox_still_works(self):
        # The descriptor branch must name the directory rather than refuse
        # it outright, or removing a populated tree inside the sandbox fails.
        tree = Path(tempfile.mkdtemp()) / 'tree'
        (tree / 'sub').mkdir(parents=True)
        (tree / 'sub' / 'leaf').write_text('fixture')
        shutil.rmtree(tree)
        self.assertFalse(tree.exists())

    def test_live_store_removal_is_covered(self):
        # tests/test_shared_definition.py removes the store this way, and on
        # Windows that path is the one the application itself takes. The
        # removal has to be refused on its own, not only because the write
        # one line above it was refused first.
        with patch.dict(os.environ, APPDATA=str(OUTSIDE)):
            store = win.store_path(sandbox.ROOT / 'home')
        with self.assertRaisesRegex(PermissionError, 'outside sandbox'):
            store.unlink()


class WindowsCopyGuardTests(GuardTestCase):
    """Windows 3.14 copies files without ever emitting an open event."""

    def test_copy_file_2_destination_is_checked(self):
        # Raised directly so the branch is covered on every platform; macOS
        # never reaches CopyFile2 because shutil.copy2 opens both files.
        with self.assertRaisesRegex(PermissionError, 'outside sandbox'):
            sys.audit('_winapi.CopyFile2', str(self.sandboxed_file('copy-source')),
                      str(OUTSIDE / 'escaped-copyfile2'), 0)

    @unittest.skipUnless(sys.platform == 'win32',
                         'only Windows copies without an open event')
    def test_windows_copies_cannot_escape(self):
        source = self.sandboxed_file('copy-source')
        for name, copy in (('copy2', lambda target: shutil.copy2(source, target)),
                           ('Path.copy', lambda target: source.copy(target))):
            with self.subTest(copy=name), \
                    self.refused_target('escaped-windows-copy') as destination:
                with self.assertRaisesRegex(PermissionError, 'outside sandbox'):
                    copy(destination)
                self.assertFalse(destination.exists())


class ModuleImportTests(unittest.TestCase):
    def test_every_test_module_imports_sandbox_first(self):
        # A module that loads application code before sandbox runs unguarded,
        # and tests/__init__.py cannot fix it: as a package the modules are
        # renamed tests.test_x and `from test_backend import b` stops working.
        modules = sorted(Path(__file__).parent.glob('test_*.py'))
        self.assertGreater(len(modules), 1)
        for module in modules:
            with self.subTest(module=module.name):
                body = ast.parse(module.read_text(encoding='utf-8')).body
                imports = [node for node in body
                           if isinstance(node, (ast.Import, ast.ImportFrom))]
                self.assertTrue(imports, 'no import at all')
                first = imports[0]
                names = ([alias.name for alias in first.names]
                         if isinstance(first, ast.Import) else [first.module])
                self.assertEqual(names, ['sandbox'],
                                 'sandbox must be imported before anything else')
