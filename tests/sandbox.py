"""Automatic process-local test isolation; import before loading application code.

This is an accident guard for Python file writes, not a security sandbox for
arbitrary subprocesses. Child processes inherit the isolated home directories.
"""
import atexit
import os
from pathlib import Path
import stat
import sys
import tempfile

if sys.platform == 'win32':
    import ctypes
    from ctypes import wintypes
    import msvcrt

    _final_path = ctypes.WinDLL('kernel32', use_last_error=True).GetFinalPathNameByHandleW
    _final_path.argtypes = (wintypes.HANDLE, wintypes.LPWSTR,
                           wintypes.DWORD, wintypes.DWORD)
    _final_path.restype = wintypes.DWORD

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
    """Absolute path an open file or directory descriptor points at."""
    try:
        if sys.platform == 'darwin' and fcntl is not None:
            # F_GETPATH only gained a fcntl constant in 3.13; 50 is its value.
            raw = fcntl.fcntl(descriptor, getattr(fcntl, 'F_GETPATH', 50), bytes(1024))
            return os.fsdecode(raw.split(b'\0', 1)[0])
        if sys.platform.startswith('linux'):
            name = os.readlink(f'/proc/self/fd/{descriptor}')
            # procfs also returns non-path labels: pipe:[...], socket:[...],
            # and anon_inode:... . Only absolute names identify filesystem nodes.
            # Mocked Linux tests retain the host's os.path (ntpath on Windows).
            if not name.startswith('/'):
                raise OSError('descriptor has no filesystem path')
            return name
        if sys.platform == 'win32':
            handle = msvcrt.get_osfhandle(descriptor)
            size = 32768
            while True:
                buffer = ctypes.create_unicode_buffer(size)
                length = _final_path(handle, buffer, size, 0)
                if length == 0:
                    raise ctypes.WinError(ctypes.get_last_error())
                if length >= size:
                    size = length + 1
                    continue
                name = buffer.value
                # Preserve UNC roots when removing the extended-path prefix.
                if name.startswith('\\\\?\\UNC\\'):
                    return '\\\\' + name[8:]
                if name.startswith('\\\\?\\'):
                    return name[4:]
                return name
    except OSError as error:
        raise PermissionError(f'Test write against an unreadable fd refused: {error}')
    # Refuse descriptors on platforms where their target cannot be named.
    raise PermissionError('Test write through an fd refused: '
                          'this platform cannot name the descriptor')


def check_write(path, dir_fd=-1):
    if isinstance(path, int):
        try:
            mode = os.fstat(path).st_mode
        except OSError as error:
            raise PermissionError(f'Test write against an unreadable fd refused: {error}')
        # Named special files need the same boundary check as regular files.
        # Only unnameable special descriptors (pipes/sockets) may pass.
        try:
            path = directory_of(path)
        except PermissionError:
            if stat.S_ISREG(mode) or stat.S_ISDIR(mode):
                raise
            return
        if stat.S_ISLNK(mode):
            # chmod on O_SYMLINK mutates the link itself, not its referent.
            link = Path(path)
            location = link.parent.resolve() / link.name
            if not location.is_relative_to(ROOT):
                raise PermissionError(f'Test write outside sandbox refused: {location}')
    name = os.fsdecode(path)
    if name == os.devnull:
        raise PermissionError('Test mutation of the null device refused')
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
        if not isinstance(path, int) and os.fsdecode(path) == os.devnull:
            # subprocess.DEVNULL needs open access, never remove/chmod/rename.
            return
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

# CPython 3.14 emits no audit events for these creation APIs. Keep their
# signatures and native exceptions, and check before invoking the originals.
_original_mkfifo = getattr(os, 'mkfifo', None)
if _original_mkfifo is not None:
    def _mkfifo(path, mode=0o666, *, dir_fd=None):
        check_write(path, dir_fd)
        return _original_mkfifo(path, mode, dir_fd=dir_fd)
    os.mkfifo = _mkfifo

_original_mknod = getattr(os, 'mknod', None)
if _original_mknod is not None:
    def _mknod(path, mode=0o600, device=0, *, dir_fd=None):
        check_write(path, dir_fd)
        return _original_mknod(path, mode, device, dir_fd=dir_fd)
    os.mknod = _mknod
