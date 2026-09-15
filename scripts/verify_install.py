#!/usr/bin/env python3
from pathlib import Path
import hashlib
import json
import plistlib
import subprocess

app = Path.home() / 'Applications/Buzz Account Manager.app'
info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
prefs = plistlib.loads(subprocess.check_output(['/usr/bin/defaults', 'export', 'com.apple.dock', '-']))
entries = [x for x in prefs.get('persistent-apps', []) if x.get('tile-data', {}).get('bundle-identifier') == info['CFBundleIdentifier']]
processes = subprocess.check_output(['/bin/ps', '-axo', 'comm='], text=True).splitlines()
print(json.dumps(dict(version=info['CFBundleShortVersionString'], dock_entries=len(entries),
                      running=any(x.strip() == str(app / 'Contents/MacOS/BuzzAccountManager') for x in processes),
                      icon=info.get('CFBundleIconFile'),
                      icon_sha256=hashlib.sha256((app / 'Contents/Resources/AppIcon.icns').read_bytes()).hexdigest())))
subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
