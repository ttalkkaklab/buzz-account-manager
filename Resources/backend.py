#!/usr/bin/env python3
"""Local storage and process boundary for Buzz Account Manager. No model API calls."""
from __future__ import annotations
import os
import contextlib
import datetime
if os.name == "nt":
    import windows_support as win
    fcntl = win
else:
    import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import sys
import tempfile
import unicodedata
import uuid
import selectors
import signal
import time
import math
import plistlib
from concurrent.futures import ThreadPoolExecutor
import urllib.request
import urllib.error
import urllib.parse

PROVIDERS = ('codex', 'claude', 'grok', 'ollama')
CLI_COMMAND = {'codex': 'codex-acp', 'claude': 'claude-agent-acp', 'grok': 'grok', 'ollama': 'claude-agent-acp'}
ALL_EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max', 'ultra')
CLAUDE_EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')
AUTH_OVERRIDES = (
    'OPENAI_API_KEY', 'OPENAI_API_KEY_FILE', 'OPENAI_BASE_URL', 'OPENAI_API_BASE',
    'CODEX_API_KEY', 'CODEX_API_KEY_FILE', 'OPENAI_ORGANIZATION', 'OPENAI_ORG_ID',
    'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_API_KEY_FILE',
    'ANTHROPIC_CUSTOM_HEADERS', 'CLAUDE_CODE_OAUTH_TOKEN',
    'ANTHROPIC_BASE_URL', 'CLAUDE_API_KEY', 'CLAUDE_CODE_API_KEY',
    'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY',
    'CLAUDE_SECURESTORAGE_CONFIG_DIR', 'CLAUDE_CODE_HOST_CREDS_FILE',
    'CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST', 'CLAUDE_CODE_HOST_AUTH_ENV_VAR',
    'XAI_API_KEY', 'GROK_API_KEY', 'GROK_AUTH', 'GROK_AUTH_PATH',
    'GROK_AUTH_PROVIDER_COMMAND', 'GROK_DEPLOYMENT_KEY', 'GROK_ALPHA_TEST_KEY',
)

def read_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def atomic_bytes(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            os.chmod(temp, mode) if os.name == "nt" else os.fchmod(f.fileno(), mode)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def clean_model_args(args):
    result = []
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg in ('--model', '-m', '--effort', '--reasoning-effort'):
            skip = True
            continue
        if any(arg.startswith(flag + '=') for flag in ('--model', '--effort', '--reasoning-effort')):
            continue
        if arg:
            result.append(arg)
    return result


def revision(raw):
    data = json.loads(raw)
    for record in data:
        for key in ('runtime_pid', 'last_started_at', 'last_stopped_at', 'last_exit_code',
                    'last_error', 'last_error_code', 'updated_at'):
            record.pop(key, None)
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def write_json(path, data):
    atomic_bytes(path, (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode())


class CodexRPC:
    """A short-lived, account-scoped app server. Never starts a model turn."""
    def __init__(self, command, env):
        self.process = subprocess.Popen(
            (win.cli_command([command, 'app-server', '--stdio', '-c', 'cli_auth_credentials_store="file"']) if os.name == 'nt' else
             [command, 'app-server', '--stdio', '-c', 'cli_auth_credentials_store="file"']),
            env=env, cwd=env['HOME'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL)
        if os.name == 'nt':
            self.reader = win.PipeReader(self.process.stdout)
            self.selector = None
        else:
            self.selector = selectors.DefaultSelector()
            self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.buffer = b''
        self.sequence = 0
        self.pending = []

    def send(self, method, params=None, identity=None):
        msg = dict(method=method)
        if params is not None:
            msg['params'] = params
        if identity is not None:
            msg['id'] = identity
        self.process.stdin.write((json.dumps(msg) + '\n').encode())
        self.process.stdin.flush()

    def receive(self, deadline):
        if self.selector is None:
            return json.loads(self.reader.receive(deadline))
        while b'\n' not in self.buffer:
            if time.monotonic() >= deadline:
                raise TimeoutError()
            if not self.selector.select(max(0, deadline - time.monotonic())):
                raise TimeoutError()
            data = os.read(self.process.stdout.fileno(), 65536)
            if not data:
                raise ValueError('Codex 연결이 종료됐습니다.')
            self.buffer += data
        line, self.buffer = self.buffer.split(b'\n', 1)
        return json.loads(line)

    def request(self, method, params=None, timeout=20):
        self.sequence += 1
        identity = self.sequence
        self.send(method, params, identity)
        deadline = time.monotonic() + timeout
        while True:
            msg = self.receive(deadline)
            if msg.get('id') == identity:
                if 'error' in msg:
                    raise ValueError('Codex 요청을 처리하지 못했습니다. 로그인 상태를 확인하세요.')
                return msg.get('result', {})
            if msg.get('method') == 'account/login/completed':
                self.pending.append(msg)

    def __enter__(self):
        try:
            self.request('initialize', dict(clientInfo=dict(name='buzz_account_manager', version='1.1.0'),
                                           capabilities=None))
            self.send('initialized')
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.selector is not None:
            self.selector.close()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()

    def __exit__(self, *args):
        self.close()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def remaining_window(label, used, reset=None):
    if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used):
        return None
    if isinstance(reset, (int, float)) and not isinstance(reset, bool):
        try:
            reset = datetime.datetime.fromtimestamp(reset, datetime.timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            reset = None
    return dict(label=label, remaining_percent=max(0, min(100, 100 - used)),
                resets_at=reset if isinstance(reset, str) else None)


def codex_usage(data):
    windows, notes = [], []
    buckets = data.get('rateLimitsByLimitId') or {'codex': data.get('rateLimits') or {}}
    for key, bucket in buckets.items():
        if not isinstance(bucket, dict):
            continue
        title = bucket.get('limitName') or key
        for field, fallback in [('primary', '단기'), ('secondary', '장기')]:
            item = bucket.get(field)
            if not isinstance(item, dict):
                continue
            minutes = item.get('windowDurationMins')
            duration = ('%g일' % (minutes / 1440) if minutes >= 1440 else '%g시간' % (minutes / 60)) if isinstance(minutes, (int, float)) and minutes > 0 else fallback
            window = remaining_window(title + ' · ' + duration, item.get('usedPercent'), item.get('resetsAt'))
            if window:
                window['blocked'] = bucket.get('spendControlReached') is True
                window['scope'] = bucket.get('limitId') or key
                window['is_primary'] = key == 'codex' or bucket.get('limitId') == 'codex'
                windows.append(window)
        credits = bucket.get('credits') or {}
        if credits.get('unlimited'):
            notes.append(title + ' 크레딧: 무제한')
        elif credits.get('balance') is not None:
            # Credits are not tokens. Keep the provider's unit explicit.
            try:
                balance = float(credits['balance'])
                if math.isfinite(balance):
                    notes.append(title + ' 크레딧: %g' % balance)
            except (TypeError, ValueError):
                pass
        if bucket.get('spendControlReached') is True:
            notes.append(title + ': 지출 한도 도달')
    if data.get('ordinaryUsageAllowed') is False:
        notes.append('서비스가 현재 기본 구독 사용을 제한하고 있습니다.')
    return windows, notes


def claude_usage(data):
    labels = {'five_hour': '5시간', 'seven_day': '7일', 'seven_day_opus': 'Opus · 7일',
              'seven_day_sonnet': 'Sonnet · 7일', 'seven_day_fable': 'Fable · 7일',
              'seven_day_oauth_apps': 'OAuth 앱 · 7일', 'seven_day_cowork': 'Cowork · 7일'}
    windows = []
    for key, item in data.items():
        if not isinstance(item, dict) or key == 'extra_usage':
            continue
        window = remaining_window(labels.get(key, key), item.get('utilization'), item.get('resets_at'))
        if window:
            window['scope'] = key
            window['is_primary'] = key in ('five_hour', 'seven_day')
            windows.append(window)
    return windows, []


class Manager:
    def __init__(self, home=None):
        self.home = Path(home or Path.home())
        self.root = self.home / '.config/buzz-agents'
        self.registry = self.root / 'account-manager.json'
        self._ollama_cache = {}
        self.store = (win.store_path(self.home) if os.name == 'nt' else
                      self.home / 'Library/Application Support/xyz.block.buzz.app/agents/managed-agents.json')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    @contextlib.contextmanager
    def lock(self):
        fd = os.open(self.root / '.manager.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def accounts(self):
        data = read_json(self.registry, {'version': 1, 'accounts': []})
        defaults = [dict(id='default-' + p, name=('이 컴퓨터 기본 계정' if os.name == 'nt' else '이 Mac 기본 계정'), provider=p,
                         home=str(self.home / ('.' + p)), builtin=True) for p in PROVIDERS if p != 'ollama']
        defaults.append(dict(id='default-ollama', name=('이 컴퓨터의 Ollama' if os.name == 'nt' else '이 Mac의 Ollama'), provider='ollama',
                             home=str(self.root / 'ollama/default'), builtin=True, endpoint='http://127.0.0.1:11434'))
        return defaults + data['accounts']

    def account(self, identity):
        for a in self.accounts():
            if a['id'] == identity:
                return a
        raise ValueError('계정이 없습니다. 새로고침해 주세요.')

    def executable_path(self):
        if os.name == "nt":
            return win.executable_path(self.home)
        folders = [self.home / '.local/bin', self.home / 'Library/Application Support/Buzz/node-tools/bin',
                   self.home / '.npm-global/bin', self.home / '.bun/bin', self.home / 'bin',
                   Path('/opt/homebrew/bin'), Path('/usr/local/bin'), Path('/usr/bin'), Path('/bin'),
                   Path('/usr/sbin'), Path('/sbin')]
        return os.pathsep.join(map(str, folders))

    def resolve_cli(self, name):
        found = shutil.which(name, path=self.executable_path())
        if not found:
            raise ValueError(name + ' CLI를 찾지 못했습니다.')
        return found

    @staticmethod
    def ollama_endpoint(value):
        value = value.strip().rstrip('/')
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise ValueError('Ollama 주소는 http://호스트:포트 형식으로 입력하세요.')
        try:
            parsed.port
        except ValueError:
            raise ValueError('Ollama 서버 포트를 확인하세요.')
        return value

    def ollama_request(self, account, path, payload=None):
        endpoint = self.ollama_endpoint(account.get('endpoint', 'http://127.0.0.1:11434'))
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(endpoint + path, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=3) as response:
            return json.load(response)

    def ollama_catalog(self, account):
        endpoint = account.get('endpoint', 'http://127.0.0.1:11434')
        if endpoint not in self._ollama_cache:
            try:
                self._ollama_cache[endpoint] = self.ollama_request(account, '/api/tags')
            except Exception:
                self._ollama_cache[endpoint] = None
        return self._ollama_cache[endpoint]

    def ollama_models(self, account):
        catalog = self.ollama_catalog(account) or {}
        result = []
        for item in catalog.get('models', []):
            name = item.get('name', '')
            capabilities = item.get('capabilities')
            if not name or name.endswith(':cloud') or item.get('remote_host') or item.get('remote_model'):
                continue
            if capabilities and ('completion' not in capabilities or 'tools' not in capabilities):
                continue
            result.append(dict(id=name, name=name, efforts=[], default_effort=''))
        return result

    def account_ready(self, account):
        home = Path(account['home'])
        provider = account['provider']
        try:
            if provider == 'ollama':
                return self.ollama_catalog(account) is not None
            if provider == 'codex':
                d = read_json(home / 'auth.json', {})
                return d.get('auth_mode') == 'chatgpt' and bool((d.get('tokens') or {}).get('access_token'))
            if provider == 'grok':
                d = read_json(home / 'auth.json', {})
                # Only inspect fields; never return a credential to the UI.
                def has_login(x):
                    if isinstance(x, dict):
                        return any(k in ('access_token', 'accessToken', 'refresh_token', 'refreshToken') and bool(v)
                                   or has_login(v) for k, v in x.items())
                    return isinstance(x, list) and any(has_login(v) for v in x)
                return has_login(d)
            plain = read_json(home / '.credentials.json', {})
            if (plain.get('claudeAiOauth') or {}).get('accessToken'):
                return True
            suffix = '' if account['builtin'] else '-' + hashlib.sha256(
                unicodedata.normalize('NFC', str(home)).encode()).hexdigest()[:8]
            return subprocess.run(['/usr/bin/security', 'find-generic-password', '-s',
                                   'Claude Code-credentials' + suffix],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=3).returncode == 0
        except (ValueError, OSError, subprocess.TimeoutExpired):
            return False

    def models(self, provider, home=None):
        if provider == 'ollama':
            account = next((a for a in self.accounts() if a['provider'] == 'ollama' and a['home'] == home), self.account('default-ollama'))
            return self.ollama_models(account)
        homes = [Path(home)] if home else []
        homes.append(self.home / ('.' + provider))
        for folder in homes:
            try:
                data = read_json(folder / 'models_cache.json', {})
                if provider == 'codex' and data.get('models'):
                    return [dict(id=m['slug'], name=m.get('display_name', m['slug']),
                                 efforts=[e['effort'] for e in m.get('supported_reasoning_levels', [])],
                                 default_effort=m.get('default_reasoning_level', 'medium'))
                            for m in data['models'] if m.get('visibility') != 'hide']
                if provider == 'grok' and data.get('models'):
                    return [dict(id=k, name=v['info'].get('name', k),
                                 efforts=[e['value'] for e in v['info'].get('reasoning_efforts', [])],
                                 default_effort=v['info'].get('reasoning_effort', 'medium'))
                            for k, v in data['models'].items() if not v['info'].get('hidden')]
            except (ValueError, KeyError, TypeError):
                continue
        if provider == 'claude':
            return [dict(id=m, name=n, efforts=list(CLAUDE_EFFORTS), default_effort='medium')
                    for m, n in [('fable', 'Fable'), ('opus', 'Opus'), ('sonnet', 'Sonnet'), ('haiku', 'Haiku')]]
        return []

    def read_profile(self, record):
        # Accept only launch scripts in our own directory, never arbitrary paths from the store.
        command = Path(record.get('acp_command') or '')
        if command.parent == self.root and command.name.startswith('launch-'):
            return read_json(self.root / (command.name[7:].removesuffix('.exe') + '.json'), {})
        return {}

    def snapshot(self):
        if not self.store.exists():
            raise ValueError('Buzz를 설치하고 에이전트를 만든 뒤 새로고침하세요.')
        raw = self.store.read_bytes()
        records = json.loads(raw)
        accounts = self.accounts()
        public_accounts = []
        for a in accounts:
            public_accounts.append(dict(a, ready=self.account_ready(a),
                                        models=self.models(a['provider'], a['home'])))
        agents = []
        for r in records:
            if not r.get('pubkey') or not r.get('is_active', True):
                continue
            profile = self.read_profile(r)
            provider = 'ollama' if profile.get('active_provider') == 'ollama' and r.get('runtime') == 'claude' else r.get('runtime') or 'codex'
            if provider not in PROVIDERS:
                continue
            profile = self.read_profile(r)
            aid = profile.get('account_ids', {}).get(provider, 'default-' + provider)
            # Honor the earlier manually configured Codex directory, if present.
            legacy = profile.get('subscription_accounts', {}).get('codex')
            if provider == 'codex' and legacy and not profile.get('account_ids'):
                matched = next((a['id'] for a in accounts if a['provider'] == 'codex'
                                and str(Path(a['home']) / 'auth.json') == legacy), None)
                aid = matched or 'unregistered'
            agents.append(dict(id=r['pubkey'], name=r['name'], provider=provider,
                               model=r.get('model') or '', effort=r.get('effort_level') or '',
                               account_id=aid, fallback_ids=profile.get('fallback_ids', {}).get(provider, []),
                               auto_fallback=profile.get('auto_fallback', {}).get(provider, False)))
        return dict(revision=revision(raw), agents=agents,
                    accounts=public_accounts, monitor=read_json(self.root / 'monitor-state.json', {}),
                    cli_available={p: bool(shutil.which('claude-agent-acp' if p == 'ollama' else p, path=self.executable_path())) for p in PROVIDERS})

    def create_account(self, name, provider, endpoint=None):
        if provider not in PROVIDERS:
            raise ValueError('지원하지 않는 서비스입니다.')
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError('계정 이름은 1~80자로 입력하세요.')
        self.resolve_cli('claude-agent-acp' if provider == 'ollama' else provider)
        if provider == 'ollama':
            endpoint = self.ollama_endpoint(endpoint or 'http://127.0.0.1:11434')
        with self.lock():
            data = read_json(self.registry, {'version': 1, 'accounts': []})
            if any(a['provider'] == provider and a['name'] == name for a in self.accounts()):
                raise ValueError('같은 서비스에 같은 이름의 계정이 있습니다.')
            identity = provider + '-' + uuid.uuid4().hex[:12]
            folder = self.root / 'accounts' / identity
            folder.mkdir(parents=True, mode=0o700)
            folder.parent.chmod(0o700)
            item = dict(id=identity, name=name, provider=provider, home=str(folder), builtin=False)
            if provider == 'ollama':
                item['endpoint'] = endpoint
            # A new profile gets no copied tokens, endpoints, or API billing settings.
            if provider == 'codex':
                atomic_bytes(folder / 'config.toml', b'cli_auth_credentials_store = "file"\n')
            data['accounts'].append(item)
            write_json(self.registry, data)
            return item

    def update_account(self, identity, name, endpoint=None):
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError('계정 이름은 1~80자로 입력하세요.')
        with self.lock():
            account = self.account(identity)
            if account['builtin']:
                raise ValueError('기본 계정은 수정할 수 없습니다. 새 계정을 추가하세요.')
            if any(a['id'] != identity and a['provider'] == account['provider'] and a['name'] == name
                   for a in self.accounts()):
                raise ValueError('같은 서비스에 같은 이름의 계정이 있습니다.')
            updated = dict(account, name=name)
            if account['provider'] == 'ollama':
                updated['endpoint'] = self.ollama_endpoint(endpoint if endpoint is not None else account['endpoint'])
            data = read_json(self.registry)
            data['accounts'] = [updated if a['id'] == identity else a for a in data['accounts']]
            write_json(self.registry, data)
            self._ollama_cache.clear()
            return updated

    def delete_account(self, identity):
        with self.lock():
            a = self.account(identity)
            if a['builtin']:
                raise ValueError('기본 계정은 목록에서 삭제할 수 없습니다.')
            for r in read_json(self.store, []):
                profile = self.read_profile(r)
                if identity in profile.get('account_ids', {}).values() or any(identity in ids for ids in profile.get('fallback_ids', {}).values()):
                    raise ValueError('에이전트에 연결된 계정입니다. 먼저 다른 계정으로 바꾸세요.')
            data = read_json(self.registry)
            data['accounts'] = [x for x in data['accounts'] if x['id'] != identity]
            write_json(self.registry, data)
            # Retain authentication files/Keychain entries. Removal is reversible through import.
            return {'message': '계정 목록에서 제거했습니다. 로그인 파일은 보관합니다.'}

    def auth_env(self, a, original=None):
        env = dict(os.environ if original is None else original)
        for k in AUTH_OVERRIDES:
            env.pop(k, None)
        for k in ('CODEX_HOME', 'CLAUDE_CONFIG_DIR', 'GROK_HOME', 'CLAUDECODE',
                  'CLAUDE_CODE_SESSION_ID', 'CLAUDE_CODE_CHILD_SESSION', 'CLAUDE_CODE_EFFORT_LEVEL', 'NODE_OPTIONS'):
            env.pop(k, None)
        for k in list(env):
            if k.startswith('CMUX_'):
                env.pop(k)
        env['HOME'] = str(self.home)
        env['PATH'] = self.executable_path()
        provider = a['provider']
        if provider == 'ollama':
            env.update(CLAUDE_CONFIG_DIR=a['home'], ANTHROPIC_BASE_URL=self.ollama_endpoint(a.get('endpoint', 'http://127.0.0.1:11434')),
                       ANTHROPIC_AUTH_TOKEN='ollama', ANTHROPIC_API_KEY='', CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1')
            return env
        if provider != 'claude' or not a['builtin']:
            env[{'codex': 'CODEX_HOME', 'claude': 'CLAUDE_CONFIG_DIR', 'grok': 'GROK_HOME'}[provider]] = a['home']
        return env

    def login_plan(self, identity):
        a = self.account(identity)
        if a['provider'] == 'ollama':
            raise ValueError('Ollama는 로그인 없이 서버에 연결합니다.')
        if a['builtin']:
            raise ValueError('별도 계정을 추가해서 로그인하세요. 기본 로그인은 변경하지 않습니다.')
        command = [self.resolve_cli(a['provider'])]
        command += {'codex': ['login', '--device-auth'], 'claude': ['auth', 'login', '--claudeai'],
                    'grok': ['login', '--oauth', '--device-auth']}[a['provider']]
        return command, self.auth_env(a)

    def codex_login(self, identity):
        a = self.account(identity)
        if a['provider'] != 'codex' or a['builtin']:
            raise ValueError('별도 Codex 계정을 선택하세요.')
        with CodexRPC(self.resolve_cli('codex'), self.auth_env(a)) as rpc:
            result = rpc.request('account/login/start', {'type': 'chatgptDeviceCode'}, timeout=40)
            code, url = result.get('userCode'), result.get('verificationUrl')
            if not isinstance(code, str) or not isinstance(url, str) or not url.startswith('https://'):
                raise ValueError('로그인 코드를 받지 못했습니다. 다시 시도하세요.')
            print('BUZZ_LOGIN:' + json.dumps(dict(code=code, url=url)), flush=True)
            deadline = time.monotonic() + 15 * 60
            try:
                while True:
                    msg = rpc.pending.pop(0) if rpc.pending else rpc.receive(deadline)
                    if msg.get('method') != 'account/login/completed':
                        continue
                    params = msg.get('params') or {}
                    if params.get('loginId') != result.get('loginId'):
                        continue
                    if not params.get('success'):
                        raise ValueError('로그인이 완료되지 않았습니다. 코드를 새로 받아 다시 시도하세요.')
                    print('로그인 정보를 저장했습니다.', flush=True)
                    return
            except (KeyboardInterrupt, TimeoutError):
                rpc.send('account/login/cancel', {'loginId': result['loginId']}, 999)
                raise ValueError('로그인을 취소했거나 코드가 만료됐습니다.')

    def usage(self, identity):
        a = self.account(identity)
        result = dict(account_id=identity, windows=[], notes=[], checked_at=datetime.datetime.now(
            datetime.timezone.utc).isoformat(), status='unavailable', message='')
        if a['provider'] == 'ollama':
            result['message'] = '로컬 모델에는 Codex·Claude 구독 잔량이 적용되지 않습니다.' if self.account_ready(a) else 'Ollama 서버에 연결되지 않았습니다. 서버 실행과 주소를 확인하세요.'
            return result
        if not self.account_ready(a):
            result['message'] = '로그인 후 잔량을 조회할 수 있습니다.'
            return result
        if a['provider'] == 'grok':
            result['message'] = '현재 Grok CLI는 계정 잔량 조회를 제공하지 않습니다.'
            return result
        try:
            if a['provider'] == 'codex':
                with CodexRPC(self.resolve_cli('codex'), self.auth_env(a)) as rpc:
                    data = rpc.request('account/rateLimits/read')
                windows, notes = codex_usage(data)
            else:
                home = Path(a['home'])
                credentials = read_json(home / '.credentials.json', {})
                if not (credentials.get('claudeAiOauth') or {}).get('accessToken'):
                    suffix = '' if a['builtin'] else '-' + hashlib.sha256(
                        unicodedata.normalize('NFC', str(home)).encode()).hexdigest()[:8]
                    response = subprocess.run(['/usr/bin/security', 'find-generic-password', '-w',
                                               '-s', 'Claude Code-credentials' + suffix],
                                              capture_output=True, timeout=5)
                    if response.returncode:
                        raise ValueError('로그인 정보를 읽지 못했습니다.')
                    credentials = json.loads(response.stdout)
                token = (credentials.get('claudeAiOauth') or {}).get('accessToken')
                if not token:
                    raise ValueError('로그인 정보를 찾지 못했습니다.')
                request = urllib.request.Request('https://api.anthropic.com/api/oauth/usage', headers={
                    'Authorization': 'Bearer ' + token, 'anthropic-beta': 'oauth-2025-04-20',
                    'Accept': 'application/json', 'User-Agent': 'BuzzAccountManager/1.1.0'})
                # Credentials go only to this fixed HTTPS endpoint, never through redirects.
                with urllib.request.build_opener(NoRedirect()).open(request, timeout=12) as response:
                    data = json.load(response)
                windows, notes = claude_usage(data)
            result['ordinary_blocked'] = a['provider'] == 'codex' and data.get('ordinaryUsageAllowed') is False
            result.update(windows=windows, notes=notes, status='ok' if windows or notes else 'unavailable',
                          message='' if windows or notes else '서비스가 잔량 정보를 제공하지 않았습니다.')
        except urllib.error.HTTPError as error:
            result['message'] = ('로그인이 만료됐거나 조회 권한이 없습니다. CLI에서 로그인 상태를 확인하세요.'
                                 if error.code in (401, 403) else
                                 '조회 요청이 많습니다. 잠시 후 다시 조회하세요.' if error.code == 429 else
                                 '서비스에서 잔량을 조회하지 못했습니다.')
        except Exception:
            result['message'] = '잔량을 조회하지 못했습니다. 로그인 상태와 네트워크를 확인하세요.'
        return result

    @staticmethod
    def buzz_running():
        if os.name == 'nt':
            return win.buzz_running()
        text = subprocess.check_output(['/bin/ps', '-axo', 'comm='], text=True)
        return any(line.strip().endswith('/Buzz.app/Contents/MacOS/buzz-desktop') for line in text.splitlines())

    def validate(self, req):
        a = self.account(req['account_id'])
        if a['provider'] != req['provider']:
            raise ValueError('서비스와 계정이 일치하지 않습니다.')
        if a['provider'] == 'ollama' and not self.account_ready(a):
            raise ValueError('Ollama 서버에 연결하지 못했습니다. 서버를 실행하고 주소를 확인하세요.')
        if not self.account_ready(a):
            raise ValueError('로그인 정보를 찾지 못했습니다. 계정 탭에서 먼저 로그인하세요.')
        model = req['model'].strip()
        if not model or len(model) > 180 or not re.fullmatch(r'[A-Za-z0-9_.:/\[\]-]+', model):
            raise ValueError('모델 ID를 확인하세요.')
        if a['provider'] == 'ollama':
            if model not in [m['id'] for m in self.ollama_models(a)]:
                raise ValueError('서버에 설치된 로컬 대화 모델을 선택하세요.')
            info = self.ollama_request(a, '/api/show', {'model': model})
            if info.get('remote_host') or info.get('remote_model') or 'tools' not in info.get('capabilities', []):
                raise ValueError('로컬 실행과 도구 호출을 지원하는 Ollama 모델을 선택하세요.')
        effort = req.get('effort', '')
        allowed_efforts = CLAUDE_EFFORTS if a['provider'] == 'claude' else ALL_EFFORTS
        if effort and effort not in allowed_efforts:
            raise ValueError('지원하지 않는 effort 값입니다.')
        known = next((m for m in self.models(a['provider'], a['home']) if m['id'] == model), None)
        if known and effort and effort not in known['efforts']:
            raise ValueError('선택한 모델이 지원하는 effort를 선택하세요.')
        self.validate_fallback(req)
        self.resolve_cli(CLI_COMMAND[a['provider']])
        if os.name == 'nt':
            win.buzz_binary('buzz-acp')
            if a['provider'] in ('codex', 'ollama'):
                win.buzz_binary('buzz-dev-mcp')
        return a

    def apply(self, req):
        a = self.validate(req)
        with self.lock():
            if self.buzz_running():
                raise ValueError('Buzz가 아직 실행 중입니다. 종료된 뒤 다시 적용하세요.')
            raw = self.store.read_bytes()
            if revision(raw) != req['revision']:
                raise ValueError('Buzz 설정이 바뀌었습니다. 새로고침 후 다시 선택하세요.')
            records = json.loads(raw)
            target = next((r for r in records if r.get('pubkey') == req['agent_id']), None)
            if target is None:
                raise ValueError('에이전트가 더 이상 존재하지 않습니다.')
            old_profile = self.read_profile(target)
            expected = req.get('expected_account_id')
            if expected and expected != old_profile.get('account_ids', {}).get(req['provider'], 'default-' + req['provider']) and target.get('runtime') == req['provider']:
                raise ValueError('자동 전환으로 현재 계정이 바뀌었습니다. 새로고침 후 다시 저장하세요.')
            linked = target.get('persona_id')
            targets = [target] + [r for r in records if not r.get('pubkey') and r.get('slug') == linked]
            slug = 'agent-' + target['pubkey']
            if not re.fullmatch(r'agent-[a-f0-9]{64}', slug):
                raise ValueError('에이전트 공개키 형식을 확인하세요.')
            launcher = self.root / ('launch-' + slug + ('.exe' if os.name == 'nt' else ''))
            provider = req['provider']
            runtime = 'claude' if provider == 'ollama' else provider
            for r in targets:
                r.update(runtime=runtime, model=req['model'].strip(), effort_level=req.get('effort') or None,
                         provider=None, agent_command_override=None, acp_command=str(launcher),
                         agent_command=self.resolve_cli(CLI_COMMAND[provider]),
                         agent_args=clean_model_args(r.get('agent_args', []) if r.get('runtime') == runtime else
                                     ['agent', 'stdio'] if provider == 'grok' else []),
                         mcp_command='buzz-dev-mcp' if provider in ('codex', 'ollama') else '')
                # Remove stale, provider-specific model pins; preserve other user environment.
                env = r.get('env_vars')
                if isinstance(env, dict):
                    for key in ('ANTHROPIC_MODEL', 'BUZZ_ACP_MODEL', 'BUZZ_ACP_EFFORT_LEVEL',
                                'CLAUDE_CODE_EFFORT_LEVEL', 'CODEX_CONFIG', 'CODEX_HOME',
                                'CLAUDE_CONFIG_DIR', 'GROK_HOME'):
                        env.pop(key, None)
            profile = dict(old_profile, name=target['name'], pubkey=target['pubkey'], active_provider=provider)
            profile.setdefault('account_ids', {})[provider] = a['id']
            if 'fallback_ids' in req:
                profile.setdefault('fallback_ids', {})[provider] = self.fallback_ids(req)
                profile.setdefault('auto_fallback', {})[provider] = req.get('auto_fallback') in (True, 'true')
            backups = self.root / 'backups' / (datetime.datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6])
            backups.mkdir(parents=True, mode=0o700)
            backups.parent.chmod(0o700)
            backend_copy = Path(__file__).read_bytes()
            script = ('#!/bin/sh\nexec ' + shlex.join([sys.executable, str(self.root / 'manager-backend.py'),
                                                    'launch', slug]) + ' "$@"\n').encode()
            updates = [(self.root / 'manager-backend.py', backend_copy, 0o700),
                       (self.root / (slug + '.json'), (json.dumps(profile, ensure_ascii=False, indent=2) + '\n').encode(), 0o600),
                       (launcher, script, 0o700),
                       (self.store, (json.dumps(records, ensure_ascii=False, indent=2) + '\n').encode(), 0o600)]
            if os.name == 'nt':
                updates = [(p, win.launcher_bytes() if p == launcher else data, mode)
                           for p, data, mode in updates]
                updates += [(self.root / 'windows_support.py', Path(win.__file__).read_bytes(), 0o600),
                            (self.root / 'installation.txt', str(win.installation_dir()).encode('utf-8'), 0o600)]
            originals = []
            for i, (path, _, _) in enumerate(updates):
                old = path.read_bytes() if path.exists() else None
                originals.append((path, old, path.stat().st_mode & 0o777 if path.exists() else 0o600))
                if old is not None:
                    atomic_bytes(backups / (str(i) + '-' + path.name), old)
            write_json(backups / 'manifest.json', {'files': [dict(path=str(p), existed=b is not None) for p,b,_ in originals]})
            try:
                for path, data, mode in updates:
                    atomic_bytes(path, data, mode)
            except Exception:
                for path, old, mode in reversed(originals):
                    if old is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic_bytes(path, old, mode)
                raise
            return {'message': '설정을 저장했습니다.', 'backup': str(backups)}

    @staticmethod
    def fallback_ids(req):
        ids = req.get('fallback_ids', [])
        if isinstance(ids, str):
            ids = json.loads(ids)
        if not isinstance(ids, list) or len(ids) > 3 or any(not isinstance(x, str) for x in ids) or len(set(ids)) != len(ids):
            raise ValueError('예비 계정은 중복 없이 최대 3개까지 선택하세요.')
        return ids

    def validate_fallback(self, req):
        ids = self.fallback_ids(req)
        enabled = req.get('auto_fallback') in (True, 'true')
        if enabled and (req['provider'] not in ('codex', 'claude') or not ids):
            raise ValueError('자동 전환은 Codex·Claude Code 예비 계정을 선택한 뒤 켤 수 있습니다.')
        for identity in ids:
            a = self.account(identity)
            if identity == req['account_id'] or a['provider'] != req['provider']:
                raise ValueError('현재 계정을 제외하고 같은 서비스의 예비 계정을 선택하세요.')
            if not self.account_ready(a):
                raise ValueError('예비 계정에 먼저 로그인하세요.')

    @staticmethod
    def quota_state(usage, provider, model):
        if usage.get('status') != 'ok':
            return 'unknown'
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            checked = datetime.datetime.fromisoformat(usage['checked_at'].replace('Z', '+00:00'))
            if not 0 <= (now - checked).total_seconds() < 300:
                return 'unknown'
        except (KeyError, ValueError, TypeError):
            return 'unknown'
        windows = usage.get('windows', [])
        if provider == 'codex':
            primary = [w for w in windows if w.get('is_primary')]
            reserve_needed = usage.get('ordinary_blocked') or any(w.get('remaining_percent') == 0 for w in primary)
            special = 'spark' if 'spark' in model.lower() else 'reserve' if 'luna' in model.lower() and reserve_needed else None
            scoped = [w for w in windows if special and special in w.get('scope', '').lower()]
            if special == 'spark' and not scoped:
                return 'unknown'
            relevant = scoped or primary
            if not scoped and usage.get('ordinary_blocked'):
                return 'limited'
        else:
            relevant = [w for w in windows if w.get('is_primary') or
                        any(part in model.lower() and w.get('scope') == 'seven_day_' + part for part in ('opus', 'sonnet', 'fable'))]
        valid = []
        for w in relevant:
            try:
                reset = w.get('resets_at')
                if reset and datetime.datetime.fromisoformat(reset.replace('Z', '+00:00')) <= now:
                    return 'unknown'
                remaining = w['remaining_percent']
                if isinstance(remaining, bool) or not isinstance(remaining, (int, float)) or not math.isfinite(remaining):
                    return 'unknown'
                valid.append(0 if w.get('blocked') else remaining)
            except (ValueError, TypeError, KeyError):
                return 'unknown'
        if not valid:
            return 'unknown'
        return 'limited' if min(valid) <= 0 else 'available'

    def install_monitor(self):
        if os.name == 'nt':
            return win.install_monitor(self.home)
        destination = self.root / 'monitor-backend.py'
        content = Path(__file__).read_bytes()
        if not destination.exists() or destination.read_bytes() != content:
            atomic_bytes(destination, content, 0o700)
        label = 'kr.co.astravision.buzz-account-monitor'
        path = self.home / 'Library/LaunchAgents' / (label + '.plist')
        config = dict(Label=label, ProgramArguments=[sys.executable, str(destination), 'monitor'],
                      StartInterval=300, RunAtLoad=True, ProcessType='Background')
        desired = plistlib.dumps(config)
        changed = not path.exists() or path.read_bytes() != desired
        if changed:
            atomic_bytes(path, desired)
        domain = 'gui/' + str(os.getuid())
        loaded = subprocess.run(['/bin/launchctl', 'print', domain + '/' + label], capture_output=True).returncode == 0
        if changed and loaded:
            subprocess.run(['/bin/launchctl', 'bootout', domain + '/' + label], capture_output=True, check=True)
            loaded = False
        if not loaded:
            subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(path)], capture_output=True, check=True)
        return {'ok': True}

    def monitor(self):
        # One poll at a time, including manual invocations.
        fd = os.open(self.root / '.monitor.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {'skipped': True}
            return self.monitor_once()
        finally:
            os.close(fd)

    def monitor_once(self):
        accounts = [a for a in self.accounts() if a['provider'] in ('codex', 'claude')]
        with ThreadPoolExecutor(max_workers=3) as pool:
            usages = dict(zip([a['id'] for a in accounts], pool.map(lambda a: self.usage(a['id']), accounts)))
        state = dict(checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat(), usages=usages, events=[])
        changes = []
        with self.lock():
            for r in read_json(self.store, []):
                if not r.get('pubkey') or not r.get('is_active', True):
                    continue
                profile = self.read_profile(r)
                provider = r.get('runtime')
                if provider not in ('codex', 'claude') or profile.get('active_provider') == 'ollama' or not profile.get('auto_fallback', {}).get(provider):
                    continue
                current = profile.get('account_ids', {}).get(provider)
                if self.quota_state(usages.get(current, {}), provider, r.get('model', '')) != 'limited':
                    continue
                candidates = profile.get('fallback_ids', {}).get(provider, [])[:3]
                chosen = next((aid for aid in candidates if aid != current and
                               any(a['id'] == aid and a['provider'] == provider for a in accounts) and
                               self.quota_state(usages.get(aid, {}), provider, r.get('model', '')) == 'available'), None)
                if not chosen:
                    state['events'].append(r['name'] + ': 사용 가능한 예비 계정이 없습니다.')
                    continue
                profile['account_ids'][provider] = chosen
                profile['fallback_ids'][provider] = [current if x == chosen else x for x in candidates]
                path = Path(r['acp_command']).with_name(Path(r['acp_command']).name[7:].removesuffix('.exe') + '.json')
                changes.append((path, profile, path.read_bytes()))
                state['events'].append(r['name'] + ': 예비 계정으로 전환했습니다.')
            running = self.buzz_running() if changes else False
            stopped = False
            try:
                if running:
                    if os.name == 'nt':
                        win.stop_buzz()
                    else:
                        subprocess.run(['/usr/bin/osascript', '-l', 'JavaScript', '-e',
                                    'ObjC.import("AppKit"); var apps = $.NSRunningApplication.runningApplicationsWithBundleIdentifier("xyz.block.buzz.app"); for (var i = 0; i < apps.count; i++) { apps.objectAtIndex(i).terminate; }'],
                                   capture_output=True, check=True, timeout=15)
                    for _ in range(100):
                        if not self.buzz_running():
                            stopped = True
                            break
                        time.sleep(0.1)
                    if not stopped:
                        raise ValueError('Buzz가 종료되지 않아 자동 전환을 보류했습니다.')
                if changes:
                    backup = self.root / 'backups' / ('fallback-' + uuid.uuid4().hex)
                    backup.mkdir(parents=True, mode=0o700)
                    for path, profile, old in changes:
                        atomic_bytes(backup / path.name, old)
                    try:
                        for path, profile, old in changes:
                            write_json(path, profile)
                    except Exception:
                        for path, profile, old in changes:
                            atomic_bytes(path, old)
                        raise
            except Exception:
                state['events'] = ['자동 전환을 완료하지 못했습니다. Buzz 상태와 설정을 확인하세요.']
            previous = read_json(self.root / 'monitor-state.json', {})
            state['last_events'] = state['events'] or previous.get('last_events', [])
            write_json(self.root / 'monitor-state.json', state)
        return state

    def launch(self, slug, extra):
        if not re.fullmatch(r'agent-[a-f0-9]{64}', slug):
            raise ValueError('에이전트 설정 이름이 올바르지 않습니다.')
        profile = read_json(self.root / (slug + '.json'))
        env = dict(os.environ)
        if not env.get('BUZZ_PRIVATE_KEY'):
            raise ValueError('Buzz가 전달한 에이전트 신원이 없습니다.')
        basename = Path(env.get('BUZZ_ACP_AGENT_COMMAND', '')).name
        if os.name == 'nt':
            basename = win.adapter_name(basename)
        provider = {'codex-acp': 'codex', 'claude-agent-acp': 'claude', 'claude-code-acp': 'claude',
                    'grok': 'grok', 'grok-creator': 'grok'}.get(basename)
        if not provider:
            raise ValueError('이 실행 도구는 지원하지 않습니다.')
        if provider == 'claude' and profile.get('active_provider') == 'ollama':
            provider = 'ollama'
        identity = profile.get('account_ids', {}).get(provider, 'default-' + provider)
        a = self.account(identity)
        if a['provider'] != provider:
            raise ValueError('서비스와 로그인 계정이 일치하지 않습니다.')
        env = self.auth_env(a, env)
        effort = env.get('BUZZ_ACP_EFFORT_LEVEL', '')
        if provider == 'ollama':
            model = env.get('BUZZ_ACP_MODEL', '').strip()
            if not model:
                record = next((r for r in read_json(self.store, []) if r.get('pubkey') == slug[6:]), None)
                model = (record or {}).get('model', '').strip()
            if not model:
                raise ValueError('Ollama 모델이 지정되지 않았습니다. 모델을 선택하고 저장하세요.')
            env['BUZZ_ACP_MODEL'] = model
            env['BUZZ_ACP_MCP_COMMAND'] = env.get('BUZZ_ACP_MCP_COMMAND') or (str(win.buzz_binary('buzz-dev-mcp')) if os.name == 'nt' else '/Applications/Buzz.app/Contents/MacOS/buzz-dev-mcp')
            env['ENABLE_TOOL_SEARCH'] = 'false'
            for key in ('ANTHROPIC_MODEL', 'ANTHROPIC_DEFAULT_OPUS_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_HAIKU_MODEL', 'ANTHROPIC_SMALL_FAST_MODEL', 'ANTHROPIC_DEFAULT_FABLE_MODEL'):
                env[key] = model
        elif provider == 'codex':
            config = json.loads(env.get('CODEX_CONFIG') or '{}')
            if not isinstance(config, dict):
                raise ValueError('Codex 설정 형식이 올바르지 않습니다.')
            config.pop('model_reasoning_effort', None)
            if effort:
                config['model_reasoning_effort'] = effort
            if env.get('BUZZ_ACP_MODEL'):
                config['model'] = env['BUZZ_ACP_MODEL']
            config['cli_auth_credentials_store'] = 'file'
            env['CODEX_CONFIG'] = json.dumps(config)
        elif provider == 'claude' and effort:
            env['CLAUDE_CODE_EFFORT_LEVEL'] = effort
        elif provider == 'grok':
            prefix = []
            if env.get('BUZZ_ACP_MODEL'):
                prefix += ['--model', env['BUZZ_ACP_MODEL']]
            if effort:
                prefix += ['--reasoning-effort', effort]
            env['BUZZ_ACP_AGENT_ARGS'] = ','.join(prefix + clean_model_args(env.get('BUZZ_ACP_AGENT_ARGS', '').split(',')))
        harness = self.home / '.buzz/bin/buzz-acp-persistent'
        if not harness.exists():
            harness = Path('/Applications/Buzz.app/Contents/MacOS/buzz-acp')
        if os.name == 'nt':
            harness = win.buzz_binary('buzz-acp')
            raise SystemExit(win.run_cli([str(harness), *extra], env))
        os.execve(str(harness), [str(harness), *extra], env)


def main():
    manager = Manager()
    action = sys.argv[1]
    req = json.load(sys.stdin) if action in ('create', 'update', 'delete', 'apply', 'validate', 'usage') else {}
    if action == 'install-monitor':
        result = manager.install_monitor()
    elif action == 'monitor':
        result = manager.monitor()
    elif action == 'status':
        result = manager.snapshot()
    elif action == 'usage':
        result = manager.usage(req['account_id'])
    elif action == 'create':
        result = manager.create_account(req['name'], req['provider'], req.get('endpoint'))
    elif action == 'update':
        result = manager.update_account(req['account_id'], req['name'], req.get('endpoint'))
    elif action == 'delete':
        result = manager.delete_account(req['account_id'])
    elif action == 'validate':
        manager.validate(req)
        result = {'ok': True}
    elif action == 'apply':
        result = manager.apply(req)
    elif action == 'launch':
        return manager.launch(sys.argv[2], sys.argv[3:])
    elif action == 'login':
        if manager.account(sys.argv[2])['provider'] == 'codex':
            def stop_login(*_):
                raise KeyboardInterrupt()
            signal.signal(signal.SIGTERM, stop_login)
            return manager.codex_login(sys.argv[2])
        command, env = manager.login_plan(sys.argv[2])
        if os.name == 'nt':
            raise SystemExit(win.run_cli(command, env))
        os.execve(command[0], command, env)
    else:
        raise ValueError('지원하지 않는 명령입니다.')
    print(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        # Do not echo raw config, environment, CLI output, or token-bearing parse errors.
        message = str(e) if type(e) is ValueError else '로컬 설정을 처리하지 못했습니다. 파일 권한과 JSON 형식을 확인하세요.'
        print(json.dumps({'error': message}, ensure_ascii=False))
        sys.exit(1)
