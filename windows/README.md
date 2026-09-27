# Buzz Account Manager — Windows Preview

Windows 10/11 x64용 설치 프로그램입니다. Python 실행 환경을 포함하며 설치 화면에서 D: 등 원하는 드라이브의 폴더를 선택할 수 있습니다.

## 사용 순서

1. Windows용 Buzz를 설치하고 사용할 에이전트를 만드세요.
2. Buzz에서 사용할 CLI와 ACP 어댑터를 설치하세요. Codex는 `codex`와 `codex-acp`, Claude와 Ollama는 `claude-agent-acp`, Grok은 `grok`이 필요합니다. 구독 로그인에는 해당 서비스 CLI도 필요합니다.
3. 왼쪽 **계정 설정**에서 **계정 추가**를 누르세요. 구독 계정은 별도 콘솔 창에서 로그인하며, Ollama·로컬 OpenAI 호환 Codex 서버는 주소를 입력합니다.
4. 로그인 콘솔을 닫으면 계정 목록이 자동으로 갱신됩니다. 서비스별 필터, 계정 정보 수정, 목록 삭제, 숨긴 기본 계정 복원을 사용할 수 있습니다. 삭제는 인증 파일을 보존합니다.
5. **에이전트 설정**에서 계정·모델·effort와 순서 있는 예비 계정을 선택하고 저장하세요. 저장은 검증 후 실행 중인 Buzz에 종료를 요청합니다. 모든 에이전트의 응답이 중단될 수 있습니다.
6. Buzz를 다시 실행하세요.

모델 목록에 원하는 모델이 없으면 **모델 ID 직접 입력**을 켜세요(Ollama 제외). **일반 설정 → 언어**에서 한국어·English·Tiếng Việt·시스템 설정을 선택하면 즉시 반영됩니다. 언어는 `HKCU\Software\Buzz Account Manager\DisplayLanguage`에 저장합니다.

Ctrl+1·2·3으로 계정·에이전트·일반 설정을 이동합니다. 도구 모음의 **새로고침** 또는 F5는 현재 로컬 상태를 다시 읽습니다. 잔량은 전체 또는 계정별로 조회하며, 기본 한도·자세히 보기·초기화/조회 시각을 표시합니다.

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

이 빌드는 Windows 시험판이며 코드 서명이 없습니다. 격리된 가짜 계정으로 화면 이동·삭제 취소/확정·기본 계정 복원·세 언어 전환을 확인했습니다. 실제 구독 로그인·Buzz 종료 후 저장·예약 작업 설치·실제 OS 150%/200% DPI는 미검증입니다. 운영 PC에서 검증할 때는 USERPROFILE·HOME·HOMEDRIVE/HOMEPATH·APPDATA·LOCALAPPDATA를 자식 프로세스에서 모두 격리하세요. 환경변수 격리만으로 Buzz 프로세스 종료나 예약 작업 설치가 차단되지는 않습니다. 언어 레지스트리는 검증 전 값을 보관하고 복원하세요.

## 소스에서 빌드

macOS 빌드 도구: Python 3, Go, NSIS (`brew install makensis`).

```sh
python3 windows/build.py
```

빌드 스크립트는 Python 공식 사이트에서 고정 버전의 Windows embeddable package를 받고 SHA-256을 검사합니다. Python 라이선스는 설치 폴더의 `runtime/LICENSE.txt`에 있습니다.
