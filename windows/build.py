#!/usr/bin/env python3
"""Cross-build an offline Windows x64 installer with Go, NSIS and embedded Python."""
from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build'
VERSION = '3.13.12'
SHA256 = '76f238f606250c87c6beac75dccd35ee99070a13490555936abb6cb64ecce3d0'


def main():
    BUILD.mkdir(exist_ok=True)
    archive = BUILD / f'python-{VERSION}-embed-amd64.zip'
    if not archive.exists():
        urllib.request.urlretrieve(f'https://www.python.org/ftp/python/{VERSION}/{archive.name}', archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise SystemExit('Embedded Python SHA-256 mismatch')
    payload = BUILD / 'windows-payload'
    if payload.exists():
        shutil.rmtree(payload)
    runtime = payload / 'runtime'
    runtime.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        z.extractall(runtime)
    # Include the installed backend, never ambient user site-packages or PYTHONPATH.
    (runtime / 'python313._pth').write_text('python313.zip\n.\n..\n', encoding='utf-8')
    env = dict(os.environ, GOOS='windows', GOARCH='amd64', CGO_ENABLED='0')
    subprocess.run(['go', 'build', '-trimpath', '-ldflags=-s -w -H=windowsgui',
                    '-o', str(payload / 'agent-launcher.exe'), str(ROOT / 'windows/launcher.go')], env=env, check=True)
    shutil.copy2(payload / 'agent-launcher.exe', payload / 'Buzz Account Manager.exe')
    for name in ('backend.py', 'windows_support.py'):
        shutil.copy2(ROOT / 'Resources' / name, payload / name)
    for name in ('App.ps1', 'Login.ps1'):
        # Windows PowerShell 5.1 needs the BOM to recognize Korean source as UTF-8.
        (payload / name).write_text((ROOT / 'windows' / name).read_text(encoding='utf-8'), encoding='utf-8-sig')
    shutil.copy2(ROOT / 'windows/login_console.py', payload / 'login_console.py')
    shutil.copy2(ROOT / 'windows/README.md', payload / 'README-Windows.txt')
    shutil.copy2(ROOT / 'LICENSE', payload / 'LICENSE')
    shutil.copy2(ROOT / 'Resources/AppIcon.png', payload / 'AppIcon.png')
    subprocess.run(['makensis', str(ROOT / 'windows/installer.nsi')], cwd=ROOT / 'windows', check=True)
    setup = BUILD / 'Buzz-Account-Manager-1.2.0-preview.2-windows-x64-setup.exe'
    digest = hashlib.sha256(setup.read_bytes()).hexdigest()
    setup.with_suffix('.exe.sha256').write_text(digest + '  ' + setup.name + '\n')
    print(setup)

if __name__ == '__main__':
    main()
