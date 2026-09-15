#!/usr/bin/env python3
"""Pin the installed app without changing existing Dock items."""
import datetime
import getpass
from pathlib import Path
import plistlib
import subprocess
import urllib.parse
import uuid

app = Path.home() / 'Applications/Buzz Account Manager.app'
if not app.is_dir():
    raise SystemExit('App is not installed')
raw = subprocess.check_output(['/usr/bin/defaults', 'export', 'com.apple.dock', '-'])
prefs = plistlib.loads(raw)
uri = app.as_uri() + '/'
items = prefs.get('persistent-apps', [])
for item in items:
    data = item.get('tile-data', {})
    url = data.get('file-data', {}).get('_CFURLString', '')
    if data.get('bundle-identifier') == 'kr.co.astravision.buzz-account-manager' or urllib.parse.unquote(url).rstrip('/') == urllib.parse.unquote(uri).rstrip('/'):
        print('Dock already pinned')
        break
else:
    backup = Path.home() / '.config/buzz-agents/backups' / ('dock-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6] + '.plist')
    backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup.write_bytes(raw)
    backup.chmod(0o600)
    item = {'tile-data': {'file-data': {'_CFURLString': uri, '_CFURLStringType': 15},
                          'file-label': 'Buzz 계정 관리', 'bundle-identifier': 'kr.co.astravision.buzz-account-manager',
                          'file-type': 41}, 'tile-type': 'file-tile'}
    # Append one item through the preferences service; preserve all unrelated preferences.
    value = plistlib.dumps(item).decode()
    subprocess.run(['/usr/bin/defaults', 'write', 'com.apple.dock', 'persistent-apps', '-array-add', value], check=True)
    updated = plistlib.loads(subprocess.check_output(['/usr/bin/defaults', 'export', 'com.apple.dock', '-']))
    assert any(x.get('tile-data', {}).get('bundle-identifier') == 'kr.co.astravision.buzz-account-manager' for x in updated['persistent-apps'])
    subprocess.run(['/usr/bin/killall', '-u', getpass.getuser(), 'Dock'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print('Dock pinned; previous preferences backed up')
