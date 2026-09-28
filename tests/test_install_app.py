import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / 'scripts/install_app.py'


def make_archive(folder, version):
    """Create a signed test app ZIP that the real installer can unpack."""
    app = Path(folder) / 'source' / 'Buzz Account Manager.app'
    executable = app / 'Contents/MacOS/BuzzAccountManager'
    resources = app / 'Contents/Resources'
    executable.parent.mkdir(parents=True)
    resources.mkdir(parents=True)
    executable.write_text('#!/bin/sh\nexit 0\n')
    executable.chmod(0o755)
    (resources / 'backend.py').write_text(
        'import json\n'
        "print(json.dumps({'agents': [], 'accounts': [], 'cli_available': {}}))\n"
    )
    info = {
        'CFBundleExecutable': executable.name,
        'CFBundleIdentifier': 'kr.co.astravision.buzz-account-manager.install-test',
        'CFBundlePackageType': 'APPL',
        'CFBundleVersion': str(version),
    }
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(app)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    archive = Path(folder) / f'app-{version}.zip'
    subprocess.run(['/usr/bin/ditto', '-c', '-k', '--keepParent', str(app), str(archive)], check=True)
    return archive


def installed_version(home):
    info = Path(home) / 'Applications/Buzz Account Manager.app/Contents/Info.plist'
    return plistlib.loads(info.read_bytes())['CFBundleVersion']


class InstallAppTests(unittest.TestCase):
    def run_installer(self, home, archive, force=False, python_path=None):
        environ = os.environ.copy()
        environ['HOME'] = str(home)
        if python_path is not None:
            existing = environ.get('PYTHONPATH')
            environ['PYTHONPATH'] = str(python_path) + (os.pathsep + existing if existing else '')
        if force:
            environ['BUZZ_INSTALL_FORCE'] = '1'
        else:
            environ.pop('BUZZ_INSTALL_FORCE', None)
        return subprocess.run(['/usr/bin/python3', str(INSTALLER), str(archive)], env=environ,
                              text=True, capture_output=True)

    def test_zip_installer_guards_downgrades_and_allows_override(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            build_10 = make_archive(root / 'v10', 10)
            build_11 = make_archive(root / 'v11', 11)

            first_home = root / 'first-home'
            first_home.mkdir()
            first = self.run_installer(first_home, build_10)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(installed_version(first_home), '10')

            same_home = root / 'same-home'
            same_home.mkdir()
            self.assertEqual(self.run_installer(same_home, build_10).returncode, 0)
            same = self.run_installer(same_home, build_10)
            self.assertEqual(same.returncode, 0, same.stderr)
            self.assertEqual(installed_version(same_home), '10')

            newer_home = root / 'newer-home'
            newer_home.mkdir()
            self.assertEqual(self.run_installer(newer_home, build_10).returncode, 0)
            newer = self.run_installer(newer_home, build_11)
            self.assertEqual(newer.returncode, 0, newer.stderr)
            self.assertEqual(installed_version(newer_home), '11')

            downgrade_home = root / 'downgrade-home'
            downgrade_home.mkdir()
            self.assertEqual(self.run_installer(downgrade_home, build_11).returncode, 0)
            refused = self.run_installer(downgrade_home, build_10)
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual(
                refused.stderr,
                'Refusing to replace build 11 with older build 10. '
                'Build from the integrated source, or set BUZZ_INSTALL_FORCE=1 '
                'to install this build anyway.\n',
            )
            self.assertEqual(installed_version(downgrade_home), '11')

            forced = self.run_installer(downgrade_home, build_10, force=True)
            self.assertEqual(forced.returncode, 0, forced.stderr)
            self.assertEqual(installed_version(downgrade_home), '10')

    def test_zip_installer_keeps_backups_unique_within_same_second(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = make_archive(root / 'archive', 10)
            home = root / 'home'
            home.mkdir()
            hook = root / 'fixed-time'
            hook.mkdir()
            (hook / 'sitecustomize.py').write_text(
                'import datetime\n'
                'class FixedDateTime(datetime.datetime):\n'
                '    @classmethod\n'
                '    def now(cls, tz=None):\n'
                '        return cls(2026, 9, 28, 12, 34, 56, tzinfo=tz)\n'
                'datetime.datetime = FixedDateTime\n'
            )

            for _ in range(3):
                installed = self.run_installer(home, archive, python_path=hook)
                self.assertEqual(installed.returncode, 0, installed.stderr)

            backup_root = home / '.config/buzz-agents/app-backups'
            self.assertEqual(
                sorted(path.name for path in backup_root.iterdir()),
                ['20260928-123456', '20260928-123456-1'],
            )
            self.assertTrue(all((path / 'Buzz Account Manager.app').is_dir()
                                for path in backup_root.iterdir()))


if __name__ == '__main__':
    unittest.main()
