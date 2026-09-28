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

    @unittest.skipUnless(os.unlink in os.supports_dir_fd,
                         'removal relative to a directory fd is unsupported')
    def test_removal_through_a_directory_descriptor_cannot_escape(self):
        # shutil.rmtree walks POSIX trees with relative names against an open
        # directory. Resolving those against the working directory would let
        # the removal through whenever that directory sits in the sandbox.
        descriptor = os.open(OUTSIDE, os.O_RDONLY)
        try:
            with contextlib.chdir(sandbox.ROOT):
                expected = re.escape(str(OUTSIDE / 'escaped-dir-fd'))
                with self.assertRaisesRegex(PermissionError, expected):
                    os.unlink('escaped-dir-fd', dir_fd=descriptor)
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


class DescriptorGuardTests(GuardTestCase):
    def assert_external_descriptor_refused(self, operation):
        # The parent owns the disposable canary; the child's sandbox is a
        # different root. No checkout or real user file is a mutation target.
        canary = self.sandboxed_file('fd-canary')
        before = (canary.read_bytes(), canary.stat().st_mode)
        code = '''
import os
import sys
target, operation = sys.argv[1:]
# A writable descriptor can predate the hook (or be inherited).
fd = os.open(target, os.O_RDWR) if operation == 'truncate' else None
import sandbox
if fd is None:
    # Read-only opens after bootstrap must not grant permission to chmod.
    fd = os.open(target, os.O_RDONLY)
try:
    try:
        if operation == 'chmod':
            os.chmod(fd, 0o640)
        else:
            os.truncate(fd, 1)
    except PermissionError:
        print('descriptor mutation blocked')
    else:
        raise AssertionError('external descriptor mutation escaped')
finally:
    os.close(fd)
'''
        result = subprocess.run([sys.executable, '-B', '-c', code,
                                 str(canary), operation],
                                cwd=Path(__file__).parent,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('descriptor mutation blocked', result.stdout)
        self.assertEqual((canary.read_bytes(), canary.stat().st_mode), before)

    @unittest.skipUnless(os.chmod in os.supports_fd, 'chmod(fd) unsupported')
    def test_readonly_external_descriptor_cannot_chmod(self):
        self.assert_external_descriptor_refused('chmod')

    def test_preopened_external_descriptor_cannot_truncate(self):
        self.assert_external_descriptor_refused('truncate')

    @unittest.skipUnless(sys.platform in ('darwin', 'win32') or sys.platform.startswith('linux'),
                         'platform cannot resolve file descriptors')
    def test_internal_fdopen_and_ftruncate_still_work(self):
        descriptor, name = tempfile.mkstemp()
        with os.fdopen(descriptor, 'wb') as output:
            output.write(b'fixture')
            output.flush()
            os.ftruncate(output.fileno(), 3)
        self.assertEqual(Path(name).read_bytes(), b'fix')

    def test_pipe_fdopen_still_works(self):
        reader, writer = os.pipe()
        try:
            with os.fdopen(writer, 'wb', closefd=False) as output:
                output.write(b'pipe fixture')
            self.assertEqual(os.read(reader, 12), b'pipe fixture')
        finally:
            os.close(writer)
            os.close(reader)

    def test_unresolvable_descriptor_is_refused(self):
        descriptor, _ = tempfile.mkstemp()
        os.close(descriptor)
        with self.assertRaises(PermissionError):
            sandbox.check_write(descriptor)
        descriptor, _ = tempfile.mkstemp()
        try:
            with patch.object(sys, 'platform', 'unsupported'):
                with self.assertRaises(PermissionError):
                    sandbox.check_write(descriptor)
        finally:
            os.close(descriptor)

    def test_null_device_mutation_events_are_refused(self):
        # Emit real event shapes without ever mutating the actual device.
        source = str(self.sandboxed_file('source'))
        events = [('os.remove', (os.devnull, -1)),
                  ('os.rmdir', (os.devnull, -1)),
                  ('os.chmod', (os.devnull, 0o600, -1)),
                  ('os.truncate', (os.devnull, 0)),
                  ('os.rename', (source, os.devnull, -1, -1)),
                  ('os.link', (source, os.devnull, -1, -1)),
                  ('os.symlink', (source, os.devnull, -1)),
                  ('_winapi.CopyFile2', (source, os.devnull, 0))]
        for event, args in events:
            with self.subTest(event=event):
                with self.assertRaises(PermissionError):
                    sys.audit(event, *args)


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
