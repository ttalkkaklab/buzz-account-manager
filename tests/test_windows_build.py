import sandbox

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('windows_build', Path(__file__).resolve().parents[1] / 'windows/build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class PinnedLauncherTests(unittest.TestCase):
    def test_wrong_hash_and_missing_pair_fail_before_payload_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'launcher.exe'
            source.write_bytes(b'MZ-fixture')
            for path, digest in ((source, None), (None, 'a' * 64), (source, 'a' * 64)):
                with self.subTest(path=path, digest=digest), self.assertRaises(SystemExit):
                    build.verified_launcher(path, digest)

    def test_pinned_build_never_compiles_and_packages_exact_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'build'
            output.mkdir()
            source = root / 'verified-launcher.exe'
            source.write_bytes(b'MZ-known-allowed-test-fixture')
            archive = output / f'python-{build.VERSION}-embed-amd64.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr('python.exe', b'fixture')
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            setup = output / 'Buzz-Account-Manager-1.2.0-preview.2-windows-x64-setup.exe'
            def package(command, **kwargs):
                self.assertEqual(command[0], 'makensis')
                for name in ('agent-launcher.exe', 'Buzz Account Manager.exe'):
                    self.assertEqual((output / 'windows-payload' / name).read_bytes(), source.read_bytes())
                setup.write_bytes(b'fixture installer')
            with patch.object(build, 'BUILD', output), patch.object(build, 'SHA256', hashlib.sha256(archive.read_bytes()).hexdigest()), patch('sys.argv', ['build.py', '--launcher-file', str(source), '--launcher-sha256', digest]), patch.object(build.subprocess, 'run', side_effect=package) as run:
                build.main()
            self.assertEqual(run.call_count, 1)
