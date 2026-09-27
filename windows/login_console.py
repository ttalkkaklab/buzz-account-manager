import sys
import json
from pathlib import Path
from backend import Manager
from windows_support import run_cli
try:
    command, env = Manager().login_plan(sys.argv[1])
    raise SystemExit(run_cli(command, env))
except Exception:
    key = '로그인을 시작하지 못했습니다. 계정과 CLI 설치를 확인하세요.'
    language = sys.argv[2] if len(sys.argv) > 2 else 'en'
    try:
        catalog = json.loads(Path(__file__).with_name('Translations.json').read_text(encoding='utf-8'))
        key = catalog.get(key, {}).get(language, key)
    except (OSError, ValueError):
        pass
    print(key)
    raise SystemExit(1)
