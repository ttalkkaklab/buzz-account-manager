import sandbox  # Isolate paths and guard writes before loading application code.
import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('version_guard', Path(__file__).resolve().parents[1] / 'scripts/version_guard.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def bundle(root, name, version):
    """Write a minimal app bundle; version None leaves out CFBundleVersion."""
    info = Path(root) / name / 'Contents/Info.plist'
    info.parent.mkdir(parents=True)
    data = {'CFBundleIdentifier': 'kr.co.astravision.buzz-account-manager'}
    if version is not None:
        data['CFBundleVersion'] = version
    info.write_bytes(plistlib.dumps(data))
    return str(Path(root) / name)


class VersionGuardTests(unittest.TestCase):
    def test_older_build_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = bundle(folder, 'candidate.app', '10')
            installed = bundle(folder, 'installed.app', '11')
            message = g.downgrade_error(candidate, installed)
            self.assertIn('older build 10', message)
            self.assertIn('build 11', message)
            self.assertIn('BUZZ_INSTALL_FORCE=1', message)
            self.assertEqual(g.main(['version_guard.py', candidate, installed], {}), 1)

    def test_same_and_newer_builds_install(self):
        with tempfile.TemporaryDirectory() as folder:
            installed = bundle(folder, 'installed.app', '11')
            for version in ('11', '12', '100'):
                candidate = bundle(folder, f'candidate-{version}.app', version)
                self.assertIsNone(g.downgrade_error(candidate, installed))
                self.assertEqual(g.main(['version_guard.py', candidate, installed], {}), 0)

    def test_first_install_has_nothing_to_compare(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = bundle(folder, 'candidate.app', '10')
            self.assertIsNone(g.downgrade_error(candidate, str(Path(folder) / 'missing.app')))

    def test_unreadable_versions_do_not_block(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = bundle(folder, 'candidate.app', '10')
            self.assertIsNone(g.downgrade_error(candidate, bundle(folder, 'no-key.app', None)))
            self.assertIsNone(g.downgrade_error(candidate, bundle(folder, 'text.app', '1.4.5')))
            self.assertIsNone(g.downgrade_error(bundle(folder, 'bad-candidate.app', '1.4.5'), bundle(folder, 'installed.app', '11')))

    def test_force_overrides_the_refusal(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = bundle(folder, 'candidate.app', '10')
            installed = bundle(folder, 'installed.app', '11')
            self.assertEqual(g.main(['version_guard.py', candidate, installed], {'BUZZ_INSTALL_FORCE': '1'}), 0)
            self.assertEqual(g.main(['version_guard.py', candidate, installed], {'BUZZ_INSTALL_FORCE': '0'}), 1)


if __name__ == '__main__':
    unittest.main()
