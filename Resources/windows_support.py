"""Windows process, locking, and installation boundaries (standard library only)."""
from pathlib import Path
import base64
import csv
import io
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET

LOCK_EX = 2
LOCK_NB = 4


def flock(fd, flags):
    import msvcrt
    os.lseek(fd, 0, os.SEEK_SET)
    if os.fstat(fd).st_size == 0:
        os.write(fd, b'\0')
        os.lseek(fd, 0, os.SEEK_SET)
    while True:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            if flags & LOCK_NB:
                raise BlockingIOError('Lock is held') from None
            time.sleep(0.05)


def store_path(home):
    roaming = Path(os.environ.get('APPDATA', str(home / 'AppData/Roaming')))
    return roaming / 'xyz.block.buzz.app/agents/managed-agents.json'


def installation_dir():
    location = Path(__file__).with_name('installation.txt')
    return Path(location.read_text(encoding='utf-8').strip()) if location.exists() else Path(__file__).resolve().parent


def launcher_bytes():
    return (installation_dir() / 'agent-launcher.exe').read_bytes()


def registered_paths():
    """Read current Windows PATH values, including installs made after app startup."""
    if os.name != 'nt':
        return []
    import winreg
    paths = []
    for hive, key in (
        (winreg.HKEY_CURRENT_USER, r'Environment'),
        (winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'),
    ):
        try:
            with winreg.OpenKey(hive, key) as handle:
                value, _ = winreg.QueryValueEx(handle, 'Path')
                paths.extend(p for p in winreg.ExpandEnvironmentStrings(value).split(';') if p)
        except OSError:
            continue
    return paths


def executable_path(home):
    roaming = Path(os.environ.get('APPDATA', str(home / 'AppData/Roaming')))
    local = Path(os.environ.get('LOCALAPPDATA', str(home / 'AppData/Local')))
    folders = [home / '.local/bin', roaming / 'Buzz/node-tools', roaming / 'npm',
               home / '.bun/bin', local / 'Programs/Ollama']
    for root in (roaming, local):
        folders.extend(sorted((root / 'Buzz/runtimes/node').glob('*/win-*'), reverse=True))
    folders.extend(Path(p) for p in registered_paths())
    folders.extend(Path(p) for p in os.environ.get('PATH', '').split(os.pathsep) if p)
    return os.pathsep.join(dict.fromkeys(map(str, folders)))


def buzz_binary(name):
    found = shutil.which(name, path=executable_path(Path.home()))
    if found:
        return Path(found)
    roots = ([Path(os.environ['BUZZ_INSTALL_DIR'])] if os.environ.get('BUZZ_INSTALL_DIR') else [])
    roots += [Path.home() / '.buzz/bin',
             Path(os.environ.get('LOCALAPPDATA', '')) / 'Buzz',
             Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Buzz',
             Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')) / 'Buzz',
             Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Buzz']
    if os.name == 'nt':
        import winreg
        key = r'Software\Microsoft\Windows\CurrentVersion\Uninstall'
        for hive, view in ((h, v) for h in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
                           for v in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)):
            try:
                with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as parent:
                    for i in range(winreg.QueryInfoKey(parent)[0]):
                        try:
                            with winreg.OpenKey(parent, winreg.EnumKey(parent, i), 0, winreg.KEY_READ | view) as sub:
                                if winreg.QueryValueEx(sub, 'DisplayName')[0] == 'Buzz':
                                    # Tauri's NSIS installer stores this directory in quotes.
                                    location = winreg.QueryValueEx(sub, 'InstallLocation')[0]
                                    roots.append(Path(location.strip().strip('"')))
                        except OSError:
                            continue
            except OSError:
                pass
    for root in roots:
        for folder in (root, root / 'resources', root / 'binaries'):
            candidate = folder / (name + '.exe')
            if candidate.is_file():
                return candidate
    raise ValueError('Buzz 실행 파일을 찾지 못했습니다. Windows용 Buzz를 설치하세요: ' + name)


def adapter_name(name):
    for suffix in ('.exe', '.cmd', '.bat'):
        if name.lower().endswith(suffix):
            return name[:-len(suffix)]
    return name


def cli_command(command):
    """Resolve npm shims to Node entry points without interpreting shell input."""
    path = Path(command[0])
    if path.suffix.lower() not in ('.cmd', '.bat'):
        return command
    name = path.stem
    modules = path.parent / 'node_modules'
    packages = list(modules.glob('*/package.json')) + list(modules.glob('@*/*/package.json'))
    for manifest in packages:
        try:
            package = json.loads(manifest.read_text(encoding='utf-8'))
            bins = package.get('bin', {})
            if isinstance(bins, str):
                bins = {package.get('name', '').split('/')[-1]: bins}
            if name not in bins:
                continue
            entry = (manifest.parent / bins[name]).resolve()
            if not entry.is_file():
                continue
            node = shutil.which('node', path=executable_path(Path.home()))
            if not node:
                raise ValueError('Node.js를 찾지 못했습니다. Buzz에서 실행 도구를 설치하세요.')
            return [node, str(entry), *command[1:]]
        except (OSError, ValueError, TypeError):
            continue
    raise ValueError('CLI 실행 파일을 확인할 수 없습니다. Buzz에서 실행 도구를 다시 설치하세요: ' + name)


def run_cli(command, env):
    return subprocess.call(cli_command(command), env=env)


class PipeReader:
    def __init__(self, stream):
        self.lines = queue.Queue()
        self.thread = threading.Thread(target=self._read, args=(stream,), daemon=True)
        self.thread.start()

    def _read(self, stream):
        try:
            for line in iter(stream.readline, b''):
                self.lines.put(line)
        finally:
            self.lines.put(None)

    def receive(self, deadline):
        try:
            line = self.lines.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            raise TimeoutError() from None
        if line is None:
            raise ValueError('CLI 연결이 종료됐습니다.')
        return line


def buzz_running():
    result = subprocess.run(['tasklist.exe', '/FO', 'CSV', '/NH', '/FI', 'IMAGENAME eq buzz-desktop.exe'],
                            capture_output=True, check=True, encoding='utf-8', errors='replace')
    return any(row and row[0].lower() == 'buzz-desktop.exe' for row in csv.reader(io.StringIO(result.stdout)))


def stop_buzz():
    # Ask the main window to close; never force-kill agents to change accounts.
    script = "Get-Process buzz-desktop -ErrorAction SilentlyContinue | ForEach-Object { [void]$_.CloseMainWindow() }"
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                   check=True, capture_output=True, timeout=15)


def install_monitor(home):
    root = ET.Element('Task', version='1.2', xmlns='http://schemas.microsoft.com/windows/2004/02/mit/task')
    triggers = ET.SubElement(root, 'Triggers')
    trigger = ET.SubElement(triggers, 'TimeTrigger')
    import datetime
    ET.SubElement(trigger, 'StartBoundary').text = datetime.datetime.now().isoformat(timespec='seconds')
    repetition = ET.SubElement(trigger, 'Repetition')
    ET.SubElement(repetition, 'Interval').text = 'PT5M'
    principals = ET.SubElement(root, 'Principals')
    principal = ET.SubElement(principals, 'Principal', id='Author')
    user = subprocess.check_output(['whoami.exe'], text=True).strip()
    ET.SubElement(principal, 'UserId').text = user
    ET.SubElement(principal, 'LogonType').text = 'InteractiveToken'
    ET.SubElement(principal, 'RunLevel').text = 'LeastPrivilege'
    settings = ET.SubElement(root, 'Settings')
    ET.SubElement(settings, 'MultipleInstancesPolicy').text = 'IgnoreNew'
    ET.SubElement(settings, 'DisallowStartIfOnBatteries').text = 'false'
    ET.SubElement(settings, 'StopIfGoingOnBatteries').text = 'false'
    ET.SubElement(settings, 'ExecutionTimeLimit').text = 'PT4M'
    actions = ET.SubElement(root, 'Actions', Context='Author')
    action = ET.SubElement(actions, 'Exec')
    ET.SubElement(action, 'Command').text = str(installation_dir() / 'runtime/pythonw.exe')
    ET.SubElement(action, 'Arguments').text = subprocess.list2cmdline(['-X', 'utf8', str(installation_dir() / 'backend.py'), 'monitor'])
    with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as f:
        filename = f.name
        f.write(ET.tostring(root, encoding='utf-16', xml_declaration=True))
    try:
        subprocess.run(['schtasks.exe', '/Create', '/TN', 'Buzz Account Manager Monitor-' + os.environ['USERNAME'], '/XML', filename, '/F'],
                       check=True, capture_output=True, timeout=20)
    finally:
        Path(filename).unlink(missing_ok=True)
    return {'ok': True}
