"""Automatic process-local test isolation; import before loading application code.

This is an accident guard for Python file writes, not a security sandbox for
arbitrary subprocesses. Child processes inherit the isolated home directories.
"""
import atexit
import os
from pathlib import Path
import sys
import tempfile

try:
    import fcntl
except ImportError:  # Windows has neither fcntl nor dir_fd support.
    fcntl = None

# Do not write bytecode into the checkout while the write guard is active.
sys.dont_write_bytecode = True
# Cleanup errors are ignored because a child process still holding a handle
# makes the Windows teardown raise out of atexit.
_temporary = tempfile.TemporaryDirectory(prefix='buzz-account-manager-tests-',
                                         ignore_cleanup_errors=True)
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

def directory_of(descriptor):
    """Absolute path an open directory descriptor points at."""
    try:
        if sys.platform == 'darwin' and fcntl is not None:
            # F_GETPATH only gained a fcntl constant in 3.13; 50 is its value.
            raw = fcntl.fcntl(descriptor, getattr(fcntl, 'F_GETPATH', 50), bytes(1024))
            return os.fsdecode(raw.split(b'\0', 1)[0])
        if sys.platform.startswith('linux'):
            return os.readlink(f'/proc/self/fd/{descriptor}')
    except OSError as error:
        raise PermissionError(f'Test write against an unreadable dir_fd refused: {error}')
    # Windows has no dir_fd support at all, so this is an unhandled platform:
    # refuse rather than guess, because a relative name cannot be checked.
    raise PermissionError('Test write relative to a dir_fd refused: '
                          'this platform cannot name the directory')


def check_write(path, dir_fd=-1):
    if isinstance(path, int):
        # fdopen and ftruncate reuse a descriptor whose open was already checked.
        return
    name = os.fsdecode(path)
    if name == os.devnull:
        # subprocess.DEVNULL is a sink, not a user file.
        return
    if dir_fd is not None and dir_fd != -1:
        # shutil.rmtree walks POSIX trees with relative names against an open
        # directory. Resolving those against the process working directory
        # would let a delete outside the sandbox pass whenever that working
        # directory happens to sit inside the sandbox.
        name = os.path.join(directory_of(dir_fd), name)
    resolved = Path(name).resolve()
    if not resolved.is_relative_to(ROOT):
        raise PermissionError(f'Test write outside sandbox refused: {resolved}')


def _audit(event, args):
    if event == 'open':
        path, mode, flags = args
        if (mode and any(c in mode for c in 'wax+')) or flags & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            check_write(path)
    elif event in ('os.rename', 'os.link'):
        # A hard link also exposes its source file to later writes through the
        # sandboxed name, so both ends are checked for either event.
        source, destination, source_fd, destination_fd = args
        check_write(source, source_fd)
        check_write(destination, destination_fd)
    elif event == 'os.symlink':
        check_write(args[1], args[2])
    elif event in ('os.remove', 'os.rmdir'):
        check_write(args[0], args[1])
    elif event == 'os.mkdir':
        check_write(args[0], args[2])
    elif event == 'os.chmod':
        check_write(args[0], args[2])
    elif event == 'os.truncate':
        check_write(args[0])
    elif event == '_winapi.CopyFile2':
        # Windows copies through CopyFile2 without emitting an open event;
        # the second argument is the destination.
        check_write(args[1])


sys.addaudithook(_audit)
