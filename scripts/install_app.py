#!/usr/bin/env python3
"""Install the app bundle for the current macOS user."""
import datetime
import itertools
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys


def reserve_backup_directory(root):
    """Create and return a unique timestamped backup directory."""
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    for suffix in itertools.count():
        name = stamp if suffix == 0 else f'{stamp}-{suffix}'
        candidate = root / name
        try:
            candidate.mkdir(parents=True, mode=0o700)
        except FileExistsError:
            continue
        return candidate


archive = Path(sys.argv[1])
applications = Path.home() / 'Applications'
applications.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='buzz-app-', dir=applications) as folder:
    subprocess.run(['/usr/bin/ditto', '-x', '-k', str(archive), folder], check=True)
    candidate = Path(folder) / 'Buzz Account Manager.app'
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(candidate)], check=True)
    target = applications / candidate.name
    guard = subprocess.run(['/usr/bin/python3', str(Path(__file__).with_name('version_guard.py')),
                            str(candidate), str(target)])
    if guard.returncode != 0:
        raise SystemExit(guard.returncode)
    backup = None
    if target.exists():
        backup_root = Path.home() / '.config/buzz-agents/app-backups'
        backup = reserve_backup_directory(backup_root) / target.name
        shutil.move(str(target), str(backup))
    try:
        shutil.move(str(candidate), str(target))
    except BaseException:
        if backup is not None:
            shutil.move(str(backup), str(target))
        raise
    print('Installed:', target)
    # Verify that this Mac can read its own Buzz agent store, without printing secrets.
    import json
    data = json.loads(subprocess.check_output(['/usr/bin/python3', str(target / 'Contents/Resources/backend.py'), 'status']))
    if 'error' in data:
        raise SystemExit(data['error'])
    print('Local agents:', len(data['agents']), 'Accounts:', len(data['accounts']))
    print('CLI availability:', data['cli_available'])
