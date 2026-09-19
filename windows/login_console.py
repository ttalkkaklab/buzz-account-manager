import sys
from backend import Manager
from windows_support import run_cli
try:
    command, env = Manager().login_plan(sys.argv[1])
    raise SystemExit(run_cli(command, env))
except Exception:
    print('로그인을 시작하지 못했습니다. 계정과 CLI 설치를 확인하세요.')
    raise SystemExit(1)
