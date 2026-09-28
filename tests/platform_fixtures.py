"""Host boundaries for backend unit tests; never execute installed launchers."""
import sandbox
import contextlib
import os
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch


def installed_launcher(test, home):
    if os.name != 'nt':
        return
    import windows_support as win
    installed = Path(home) / 'fixture-installation'
    installed.mkdir()
    # apply() copies opaque build bytes; these tests do not execute the PE file.
    (installed / 'agent-launcher.exe').write_bytes(b'MZ-unit-test-not-executable')
    for name, options in (
        ('installation_dir', dict(return_value=installed)),
        ('buzz_binary', dict(side_effect=lambda name: installed / (name + '.exe'))),
    ):
        mocker = patch.object(win, name, **options)
        mocker.start()
        test.addCleanup(mocker.stop)


@contextlib.contextmanager
def capture_launch(backend):
    """Expose both process APIs as (executable, argv, env) to assertions."""
    if os.name == 'nt':
        capture = Mock(return_value=0)
        with patch.object(backend.win, 'run_cli',
                          side_effect=lambda argv, env: capture(argv[0], argv, env)):
            yield capture
    else:
        with patch.object(backend.os, 'execve') as capture:
            yield capture


def launch(test, manager, slug, extra):
    if os.name == 'nt':
        with test.assertRaises(SystemExit) as result:
            manager.launch(slug, extra)
        test.assertEqual(result.exception.code, 0)
    else:
        manager.launch(slug, extra)


def supports_private_modes():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'mode-probe'
        path.mkdir(mode=0o700)
        path.chmod(0o700)
        private_file = path / 'file'
        private_file.write_bytes(b'fixture')
        private_file.chmod(0o600)
        return (path.stat().st_mode & 0o777 == 0o700
                and private_file.stat().st_mode & 0o777 == 0o600)


HAS_PRIVATE_MODES = supports_private_modes()
