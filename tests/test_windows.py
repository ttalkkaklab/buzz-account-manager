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
import re
import shutil
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Resources'))
import windows_support as win
from test_backend import b


class WindowsSupportTests(unittest.TestCase):
    def test_windows_translation_keys_have_both_languages(self):
        root = Path(__file__).resolve().parents[1]
        catalog = json.loads((root / 'Resources/Translations.json').read_text(encoding='utf-8'))
        keys = set()
        for name in ('App.ps1', 'Login.ps1', 'Localization.ps1'):
            source = (root / 'windows' / name).read_text(encoding='utf-8-sig')
            keys.update(re.findall(r"(?:\bL|\bSet-Message)\s+(?:\(\s*)?'([^']+)'", source))
        self.assertGreater(len(keys), 70)
        for key in keys:
            for language in ('en', 'vi'):
                with self.subTest(key=key, language=language):
                    self.assertTrue(catalog.get(key, {}).get(language, '').strip())

    def test_stop_buzz_dispatch_is_windows_only_and_mocked(self):
        for platform in ('nt', 'posix'):
            facade = SimpleNamespace(name=platform)
            with patch.object(b, 'os', facade), patch.object(b, 'win', win, create=True), \
                 patch.object(win, 'stop_buzz') as stop:
                if platform == 'nt':
                    self.assertEqual(b.Manager.stop_buzz(), {'ok': True})
                    stop.assert_called_once_with()
                else:
                    with self.assertRaises(ValueError):
                        b.Manager.stop_buzz()
                    stop.assert_not_called()
        # Exercise CLI routing too, without constructing a Manager or touching a process.
        with patch.object(b, 'Manager') as manager, patch.object(sys, 'argv', ['backend.py', 'stop-buzz']), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            manager.return_value.stop_buzz.return_value = {'ok': True}
            b.main()
            manager.return_value.stop_buzz.assert_called_once_with()
            self.assertEqual(json.loads(output.getvalue()), {'ok': True})

    def test_windows_payload_includes_shared_catalog(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('windows_build', root / 'windows/build.py')
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        self.assertIn('Translations.json', build.RESOURCE_FILES)
        self.assertIn('Localization.ps1', build.POWERSHELL_FILES)
        uninstall = (root / 'windows/installer.nsi').read_text(encoding='utf-8')
        for name in ('Translations.json', 'Localization.ps1'):
            self.assertIn('Delete "$INSTDIR\\' + name + '"', uninstall)

    @unittest.skipUnless(os.name == 'nt', 'Windows PowerShell localization runtime')
    def test_windows_localization_preserves_dynamic_values(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            shutil.copy2(root / 'Resources/Translations.json', folder / 'Translations.json')
            (folder / 'Localization.ps1').write_text(
                (root / 'windows/Localization.ps1').read_text(encoding='utf-8'), encoding='utf-8-sig')
            script = """$ErrorActionPreference='Stop'
. "$PSScriptRoot/Localization.ps1"
$script:language='en'
$result=@(
 (L '{0} 설정을 저장했습니다. Buzz는 직접 시작하세요.' @('Name {1}', 'INJECTED')),
 (Localize-Backend 'My {0} CLI를 찾지 못했습니다.'),
 (Localize-Backend 'Client: 사용 가능한 예비 계정이 없습니다.'),
 (Localize-Backend 'Client: 예비 계정으로 전환했습니다.'),
 (Localize-Backend 'Client: 지출 한도 도달'),
 (Localize-Backend 'Client 크레딧: 무제한'),
 (Localize-Backend 'Client 크레딧: 42'),
 (Localize-Backend 'Buzz 실행 파일을 찾지 못했습니다. Windows용 Buzz를 설치하세요: C:\\test: keep'),
 (Localize-Backend 'CLI 실행 파일을 확인할 수 없습니다. Buzz에서 실행 도구를 다시 설치하세요: untouched {0}'),
 (Localize-QuotaLabel '5시간 · 7일 · OAuth 앱'),
 (Localize-Backend 'unknown untouched')
)
$script:language='vi'
$result+=Localize-QuotaLabel '5시간 · 7일'
$result+=Display-Date '2026-09-27T12:00:00.123456+00:00'
[Console]::OutputEncoding=[Text.Encoding]::UTF8
ConvertTo-Json -InputObject $result -Compress
"""
            runner = folder / 'check.ps1'
            runner.write_text(script, encoding='utf-8-sig')
            result = subprocess.run(['powershell.exe', '-NoProfile', '-File', str(runner)],
                                    capture_output=True, text=True, encoding='utf-8', check=True)
            rows = json.loads(result.stdout.lstrip('\ufeff'))
            self.assertIn('Name {1}', rows[0])
            self.assertNotIn('INJECTED', rows[0])
            self.assertEqual(rows[1], 'My {0} CLI was not found.')
            for row in rows[2:9]:
                self.assertNotRegex(row, '[가-힣]')
            self.assertTrue(rows[7].endswith('C:\\test: keep'))
            self.assertTrue(rows[8].endswith('untouched {0}'))
            self.assertEqual(rows[9], '5 hours · 7 days · OAuth apps')
            self.assertEqual(rows[10], 'unknown untouched')
            self.assertEqual(rows[11], '5 giờ · 7 ngày')
            self.assertNotIn('T12:', rows[12])

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
