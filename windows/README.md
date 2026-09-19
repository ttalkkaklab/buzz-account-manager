# Buzz Account Manager — Windows Preview

Windows 10/11 x64용 설치 프로그램입니다. Python 실행 환경을 포함하며 설치 화면에서 D: 등 원하는 드라이브의 폴더를 선택할 수 있습니다.

## 사용 순서

1. Windows용 Buzz를 설치하고 사용할 에이전트를 만드세요.
2. Buzz에서 사용할 CLI와 ACP 어댑터를 설치하세요. Codex는 `codex`와 `codex-acp`, Claude와 Ollama는 `claude-agent-acp`, Grok은 `grok`이 필요합니다. 구독 로그인에는 해당 서비스 CLI도 필요합니다.
3. Account Manager의 **계정 관리**에서 계정을 추가하고 **선택 계정 로그인**을 누르세요. 로그인은 별도 터미널 창에서 진행합니다. Ollama는 서버 주소를 입력하세요.
4. 로그인 후 **새로고침**을 누르세요.
5. Buzz를 종료한 뒤 **에이전트 설정**에서 계정과 모델을 선택하고 저장하세요.
6. Buzz를 다시 실행하세요.

모델 목록에 원하는 모델이 없으면 모델 ID를 직접 입력할 수 있습니다. Windows 화면은 한국어를 사용합니다.

## 실행 파일을 찾지 못할 때

CLI를 추가로 설치한 뒤 **새로고침**을 누르세요. 앱은 Windows에 저장된 최신 PATH도 읽습니다. Windows 앱 패키지의 연결 폴더는 SSH에서 접근이 거부될 수 있습니다. 이 경우 해당 CLI의 일반 설치판을 별도 폴더에 설치하고 사용자 PATH에 추가하세요.

Buzz를 다른 드라이브에 설치했다면 설치 프로그램이 기록한 위치를 자동으로 찾습니다. 압축을 풀어 설치한 경우에는 `BUZZ_INSTALL_DIR`에 `buzz-acp.exe`가 있는 폴더를 지정하세요. Buzz 실행 파일이 없으면 에이전트 설정 저장을 중단하고 오류를 표시합니다.

## 자동 전환

예비 계정을 최대 3개 선택하고 자동 전환을 켜면 Windows 작업 스케줄러가 로그인한 사용자 권한으로 5분마다 잔량을 조회합니다. 사용할 계정의 잔량이 소진되면 Buzz에 종료를 요청한 뒤 계정을 바꿉니다. 진행 중인 응답이 끊길 수 있으며 전환 후 Buzz는 직접 다시 실행해야 합니다. Buzz가 종료되지 않으면 전환하지 않습니다.

## 저장 위치

- 앱: `%LOCALAPPDATA%\Programs\Buzz Account Manager`
- 계정·프로필·백업: `%USERPROFILE%\.config\buzz-agents`
- Buzz 에이전트 설정: `%APPDATA%\xyz.block.buzz.app\agents\managed-agents.json`

계정 정보는 이 컴퓨터에 저장합니다. 설치 파일에는 사용자 계정이나 인증정보가 없습니다. 프로그램을 제거해도 계정과 설정 백업은 보존합니다. 이 앱으로 지정한 실행기를 계속 사용하려면 앱이 설치되어 있어야 합니다. 제거 전 Buzz에서 에이전트 실행기를 기본값으로 되돌리세요.

## 검증 범위

이 빌드는 Windows 시험판이며 코드 서명이 없습니다. macOS에서 회귀 테스트 59개를 통과했습니다. 실제 Windows에서 앱 실행과 에이전트 목록 표시, 설정 사전 검사, CLI와 Buzz 실행 파일 탐색, 작업 스케줄러 등록을 확인했습니다. 새 계정의 구독 로그인과 Buzz 메시지 응답은 검증하지 않았습니다.

## 소스에서 빌드

macOS 빌드 도구: Python 3, Go, NSIS (`brew install makensis`).

```sh
python3 windows/build.py
```

빌드 스크립트는 Python 공식 사이트에서 고정 버전의 Windows embeddable package를 받고 SHA-256을 검사합니다. Python 라이선스는 설치 폴더의 `runtime/LICENSE.txt`에 있습니다.
