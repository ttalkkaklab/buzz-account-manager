"""Isolated Windows boundary tests; no live accounts, tasks, or Buzz processes."""
import importlib.util
import contextlib
import io
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Resources'))
import windows_support as win
from test_backend import b


class WindowsSupportTests(unittest.TestCase):
    def test_store_uses_roaming_appdata(self):
        with patch.dict(os.environ, {'APPDATA': '/test/한글 user/roaming'}):
            self.assertEqual(win.store_path(Path('/other')), Path('/test/한글 user/roaming/xyz.block.buzz.app/agents/managed-agents.json'))

    def test_npm_shim_is_resolved_without_shell_evaluation(self):
        with tempfile.TemporaryDirectory(prefix='한글 space ') as tmp:
            root = Path(tmp)
            package = root / 'node_modules/@scope/adapter'
            package.mkdir(parents=True)
            (package / 'package.json').write_text(json.dumps({'bin': {'codex-acp':'index.js'}}))
            (package / 'index.js').write_text('// fixture')
            with patch.object(win.shutil, 'which', return_value='/runtime/node.exe'):
                args = win.cli_command([str(root / 'codex-acp.cmd'), 'a & b', '$(no)', '%PATH%'])
            self.assertEqual(args, ['/runtime/node.exe', str((package / 'index.js').resolve()), 'a & b', '$(no)', '%PATH%'])
            with self.assertRaises(ValueError):
                win.cli_command([str(root / 'unknown.cmd')])

    def test_pipe_reader_supports_unicode_eof_and_timeout(self):
        reader = win.PipeReader(io.BytesIO('{"name":"계정"}\n'.encode()))
        self.assertEqual(json.loads(reader.receive(time.monotonic()+1)), {'name':'계정'})
        with self.assertRaises(ValueError):
            reader.receive(time.monotonic()+1)
        reader = object.__new__(win.PipeReader)
        import queue
        reader.lines = queue.Queue()
        with self.assertRaises(TimeoutError):
            reader.receive(time.monotonic())

    def test_adapter_suffixes(self):
        for suffix in ('.exe','.cmd','.bat',''):
            self.assertEqual(win.adapter_name('claude-agent-acp'+suffix), 'claude-agent-acp')

    def test_path_refresh_reads_new_user_install_without_restarting_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            installed = str(Path(tmp) / 'new-cli')
            stale = str(Path(tmp) / 'old-cli')
            with patch.object(win, 'registered_paths', return_value=[installed]), \
                 patch.dict(os.environ, {'PATH': stale}):
                folders = win.executable_path(Path(tmp)).split(os.pathsep)
            self.assertIn(installed, folders)
            self.assertIn(stale, folders)
            self.assertLess(folders.index(installed), folders.index(stale))

    def test_custom_buzz_install_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'buzz-acp.exe'
            binary.write_bytes(b'MZ-fixture')
            with patch.dict(os.environ, {'BUZZ_INSTALL_DIR': tmp}), \
                 patch.object(win.shutil, 'which', return_value=None):
                self.assertEqual(win.buzz_binary('buzz-acp'), binary)

    def test_buzz_registry_location_accepts_nsis_quoted_directory(self):
        with tempfile.TemporaryDirectory(prefix='Buzz installation ') as tmp:
            binary = Path(tmp) / 'buzz-acp.exe'
            binary.write_bytes(b'MZ-fixture')
            registry = SimpleNamespace(
                HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2, KEY_READ=4,
                KEY_WOW64_64KEY=8, KEY_WOW64_32KEY=16,
                OpenKey=lambda *args: contextlib.nullcontext('key'),
                QueryInfoKey=lambda key: (1, 0, 0), EnumKey=lambda key, i: 'Buzz',
                QueryValueEx=lambda key, name: ({'DisplayName': 'Buzz',
                                                'InstallLocation': '"' + tmp + '"'}[name], 1),
            )
            windows_os = SimpleNamespace(**{k: getattr(os, k) for k in dir(os) if not k.startswith('__')})
            windows_os.name = 'nt'
            with patch.object(win, 'os', windows_os), patch.dict(sys.modules, {'winreg': registry}), \
                 patch.dict(os.environ, {'BUZZ_INSTALL_DIR': ''}), \
                 patch.object(win, 'registered_paths', return_value=[]), \
                 patch.object(win.shutil, 'which', return_value=None):
                self.assertEqual(win.buzz_binary('buzz-acp'), binary)

    def test_task_xml_quotes_paths_and_uses_interactive_user(self):
        captured = {}
        def run(args, **kwargs):
            import xml.etree.ElementTree as ET
            captured['xml'] = ET.parse(args[args.index('/XML')+1]).getroot()
            captured['args'] = args
        with patch.object(win, 'installation_dir', return_value=Path('/test/한글 & space')), \
             patch.object(win.subprocess, 'check_output', return_value='PC\\tester\n'), \
             patch.object(win.subprocess, 'run', side_effect=run), \
             patch.dict(os.environ, {'USERNAME':'tester'}):
            win.install_monitor(Path('/home'))
        ns={'t':'http://schemas.microsoft.com/windows/2004/02/mit/task'}
        root=captured['xml']
        self.assertEqual(root.find('.//t:LogonType', ns).text, 'InteractiveToken')
        self.assertEqual(root.find('.//t:RunLevel', ns).text, 'LeastPrivilege')
        self.assertEqual(root.find('.//t:Interval', ns).text, 'PT5M')
        expected = subprocess.list2cmdline(['-X', 'utf8', str(Path('/test/한글 & space') / 'backend.py'), 'monitor'])
        self.assertEqual(expected, root.find('.//t:Arguments',ns).text)
        self.assertIn('Buzz Account Manager Monitor-tester', captured['args'])

    def test_windows_apply_and_profile_roundtrip_preserve_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            # Replace only backend's platform facade; pathlib keeps the host implementation.
            windows_os=SimpleNamespace(**{k:getattr(os,k) for k in dir(os) if not k.startswith('__')})
            windows_os.name='nt'
            with patch.object(b, 'os', windows_os), patch.object(b, 'win', win, create=True), \
                 patch.dict(os.environ, {'APPDATA':str(home/'roaming')}), \
                 patch.object(win, 'launcher_bytes', return_value=b'MZ-test-launcher'), \
                 patch.object(win, 'installation_dir', return_value=home/'installed'), \
                 patch.object(win, 'buzz_binary', return_value=home/'buzz-acp.exe'), \
                 patch.object(b.Manager, 'buzz_running', return_value=False), \
                 patch.object(b.Manager, 'resolve_cli', return_value='/node/codex-acp.cmd'):
                manager=b.Manager(home)
                record=dict(pubkey='a'*64,name='Windows agent',runtime='codex',model='test',team_id='keep',env_vars={'KEEP':'yes'})
                b.write_json(manager.store,[record])
                b.write_json(home/'.codex/auth.json',{'auth_mode':'chatgpt','tokens':{'access_token':'fixture'}})
                req=dict(agent_id='a'*64,account_id='default-codex',provider='codex',model='test',effort='',revision=b.revision(manager.store.read_bytes()))
                manager.apply(req)
                updated=b.read_json(manager.store)[0]
                self.assertTrue(updated['acp_command'].endswith('.exe'))
                self.assertEqual(Path(updated['acp_command']).read_bytes(),b'MZ-test-launcher')
                self.assertEqual(updated['team_id'],'keep')
                self.assertEqual(updated['env_vars'],{'KEEP':'yes'})
                profile=manager.read_profile(updated)
                self.assertEqual(profile['account_ids']['codex'],'default-codex')
                self.assertTrue((manager.root/'windows_support.py').exists())
                self.assertEqual((manager.root/'installation.txt').read_text(),str(home/'installed'))

if __name__ == '__main__':
    unittest.main()
