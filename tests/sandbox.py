"""Automatic process-local test isolation; import before loading application code.

This is an accident guard for Python file writes, not a security sandbox for
arbitrary subprocesses. Child processes inherit the isolated home directories.
"""
import atexit
import os
from pathlib import Path
import sys
import tempfile

# Do not write bytecode into the checkout while the write guard is active.
sys.dont_write_bytecode = True
_temporary = tempfile.TemporaryDirectory(prefix='buzz-account-manager-tests-')
ROOT = Path(_temporary.name).resolve()
atexit.register(_temporary.cleanup)
for key, suffix in (('HOME', 'home'), ('USERPROFILE', 'home'),
                    ('APPDATA', 'roaming'), ('LOCALAPPDATA', 'local'),
                    ('TMP', 'tmp'), ('TEMP', 'tmp'), ('TMPDIR', 'tmp')):
    folder = ROOT / suffix
    folder.mkdir(exist_ok=True)
    os.environ[key] = str(folder)
os.environ['HOMEDRIVE'], os.environ['HOMEPATH'] = os.path.splitdrive(os.environ['USERPROFILE'])
tempfile.tempdir = str(ROOT / 'tmp')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Resources'))


def check_write(path):
    if isinstance(path, int):
        # fdopen is used after mkstemp; the original open was already checked.
        return
    if os.fsdecode(path) == os.devnull:
        # subprocess.DEVNULL is a sink, not a user file.
        return
    resolved = Path(os.fsdecode(path)).resolve()
    if not resolved.is_relative_to(ROOT):
        raise PermissionError(f'Test write outside sandbox refused: {resolved}')


def _audit(event, args):
    if event == 'open':
        path, mode, flags = args
        if (mode and any(c in mode for c in 'wax+')) or flags & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            check_write(path)
    elif event == 'os.rename':
        source, destination, source_fd, destination_fd = args
        if source_fd != -1 or destination_fd != -1:
            raise PermissionError('Test rename with dir_fd is not supported')
        check_write(source)
        check_write(destination)
    elif event == 'os.mkdir':
        check_write(args[0])


sys.addaudithook(_audit)
