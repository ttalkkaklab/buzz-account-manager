# Buzz 계정 관리

[English](README.md) · 한국어 · [Tiếng Việt](README.vi.md)

[macOS 다운로드](https://github.com/ttalkkaklab/buzz-account-manager/releases/latest) · MIT 라이선스

macOS 14 이상과 Apple Silicon용 배포본입니다. Buzz Desktop과 사용할 서비스의 CLI·ACP 어댑터가 필요합니다. ZIP을 풀고 앱을 `~/Applications`에 옮기세요. `/usr/bin/python3`를 사용하므로 Xcode Command Line Tools도 필요합니다. 배포본은 ad-hoc 서명만 포함하며 Apple 공증은 받지 않았습니다. macOS가 실행을 막으면 시스템 설정의 개인정보 보호 및 보안에서 앱을 확인하거나 소스로 빌드하세요.

이 프로젝트는 Buzz용 독립 도구입니다. Buzz와 각 AI 서비스 개발사의 공식 앱이 아닙니다.

각 Mac의 Buzz 에이전트마다 구독 계정·모델·effort를 선택하는 macOS 앱입니다.
SwiftUI 화면과 Python 표준 라이브러리로 만들었으며 별도 서버 설치 없이 실행합니다.

## 사용

`~/Applications/Buzz Account Manager.app`을 실행합니다.

1. 왼쪽 **구독 계정 → 계정 추가**에서 서비스와 계정 이름을 선택합니다.
2. CLI 안내에 따라 로그인 페이지를 열고 원하는 계정으로 로그인합니다. 앱은 비밀번호를 받지 않습니다.
3. 왼쪽에서 에이전트를 선택하고 서비스·계정·모델·effort를 지정합니다.
4. **저장하고 Buzz 재시작**을 누릅니다. 실행 중인 모든 Buzz 에이전트의 응답이 중단될 수 있습니다.

기본 계정은 현재 CLI 로그인을 그대로 사용합니다. 새 계정은 별도 디렉토리에 로그인하므로
기본 로그인을 덮어쓰지 않습니다. 계정별 CLI 설정과 세션도 별도 경로를 사용합니다.
로그인 정보가 있다는 표시가 구독 유효성이나 모델 접근 권한까지 보장하지는 않습니다.

## 로그인 코드와 잔량

Codex 로그인 창은 일회용 코드를 입력란에 표시합니다. **복사 → 로그인 페이지 열기**를 누르고
페이지의 코드 입력란에 붙여 넣으세요. 로그인 성공·취소·만료 뒤에는 코드를 지웁니다.
Claude 모델 목록에서 **Fable**을 선택할 수 있습니다. 모델 사용 권한과 크레딧 조건은 해당 계정에 따릅니다.

**구독 계정** 화면을 열면 각 계정의 잔량을 조회합니다. **잔량 새로고침**으로 모두 다시 조회하거나 **이 계정 잔량 새로고침**으로 하나만 조회할 수 있습니다.
기본 화면에는 Codex 일반 한도와 Claude Code의 5시간·7일 한도만 표시합니다.
**자세히 보기**를 펼치면 Spark·Reserve·모델별 한도와 초기화 시각, 크레딧을 볼 수 있습니다.
초기화 시각이 지난 값은 재조회 안내를 표시합니다. 다시 로그인하면 이전 잔량을 지우고 새 로그인으로 조회합니다.

- Codex: 계정별·모델별 구독 한도의 남은 비율, 초기화 시각, 별도 크레딧과 서비스 제한 상태
- Claude: 5시간·7일 등 서비스가 반환하는 한도의 남은 비율과 초기화 시각
- Grok: 현재 설치된 CLI에 계정 잔량 조회가 없어 미지원 안내 표시

구독 한도의 비율을 정확한 토큰 개수로 환산하지 않습니다. 실패하거나 값이 없으면 잔량 대신
조회 상태를 표시합니다. 화면의 값은 적힌 조회 시각 기준이며 백그라운드 조회 결과가 30초마다 반영됩니다.
Claude 로그인이 만료됐으면 해당 계정으로 다시 로그인한 뒤 잔량을 새로고침하세요.

Codex는 계정별 `app-server`의 `account/rateLimits/read`를 호출합니다. Claude는 선택한 계정의
파일 또는 Keychain 인증정보를 메모리에서 읽어 공식 OAuth 사용량 주소로 HTTPS 요청을 보냅니다.
토큰을 화면·조회 결과·로그에 넣거나 별도로 저장하지 않습니다. 모델 생성 요청이나 유료 토큰
소비 요청은 보내지 않습니다. 잔량 조회 결과는 앱 메모리와 로컬 모니터 상태 파일에 보관합니다.

## Ollama

에이전트의 AI 서비스에서 **Ollama**를 선택하면 이 Mac에 설치된 로컬 모델을 고를 수 있습니다.
Ollama 서버가 실행 중이어야 하며 기본 주소는 `http://127.0.0.1:11434`입니다.
다른 서버는 **계정 추가 → Ollama**에서 이름과 서버 주소를 입력해 등록합니다.
모델 다운로드와 서버 설치는 자동으로 실행하지 않습니다.

Claude Code ACP 어댑터와 Ollama의 Anthropic 호환 API로 연결합니다. 별도 Claude 설정 경로를
사용하고 상속된 구독 인증정보를 제거합니다. 로컬 모델은 구독 잔량을 차감하지 않습니다.
임베딩 전용·클라우드 모델은 제외하며 저장 전에 도구 호출 지원 여부를 확인합니다.
Effort는 모델 기본값을 사용합니다.

## 저장 구조

- 계정 목록: `~/.config/buzz-agents/account-manager.json`
- 새 계정 경로: `~/.config/buzz-agents/accounts/[서비스]-[ID]/`
- 에이전트 연결: `~/.config/buzz-agents/agent-[공개키].json`
- 실행 진입점: `~/.config/buzz-agents/launch-agent-[공개키]`
- 백업: `~/.config/buzz-agents/backups/[시각]-[ID]/`

Codex는 `CODEX_HOME`, Claude는 `CLAUDE_CONFIG_DIR`, Grok은 `GROK_HOME`을 사용합니다.
Claude의 별도 디렉토리는 별도 Keychain 서비스 이름으로 연결됩니다.
앱의 계정 목록에는 로그인 경로·이름과 Ollama 서버 주소를 저장합니다. 토큰은 CLI가 보관합니다.
Buzz 신원 키는 Buzz Desktop이 Keychain에서 읽어 실행 프로세스에 전달합니다.

같은 macOS 사용자로 실행하므로 계정 경로 분리는 에이전트 사이의 보안 격리를 뜻하지 않습니다.

## 설정 적용

앱은 로그인 정보와 모델 값을 검사하고 Buzz가 종료된 것을 확인한 뒤 설정을 저장합니다.
조회 후 다른 설정이 바뀌었으면 저장을 거부합니다. 프로세스 종료 시각 같은 실행 상태 변화는
충돌로 처리하지 않습니다. 이름·공개키·팀·지침·병렬도와 다른 에이전트의 설정은 유지합니다.

변경 전 파일은 권한 `600`으로 백업합니다. 저장 중 오류가 나면 이번 변경을 되돌립니다.
복구할 때는 Buzz를 종료하고 백업의 `manifest.json`에 적힌 경로로 각 파일을 복원합니다.
`existed: false`인 항목은 이번 저장에서 새로 만든 파일입니다.

새 계정의 설정을 복사하거나 API 키를 생성하지 않습니다. 실행 시 상속된 API 인증 환경변수를
제거하고 선택한 로그인 경로를 지정합니다. 사용자가 별도 CLI 설정 파일에 직접 추가한
서드파티 인증이나 실행 옵션까지 모두 검사하는 기능은 아닙니다.

모델 목록은 Codex·Grok의 로컬 캐시를 읽습니다. Claude는 CLI 모델 별칭을 제공합니다.
직접 입력한 모델의 존재와 실제 지원 여부는 CLI가 실행 시 확인합니다.
Effort는 Buzz 설정과 함께 Codex의 `CODEX_CONFIG`, Claude의 `CLAUDE_CODE_EFFORT_LEVEL`,
Grok의 `--reasoning-effort`에도 전달합니다.

ACP 실행 파일은 일반 설치 경로와 Buzz의 `node-tools/bin`, `~/.npm-global/bin`에서 찾습니다. 저장 시 확인한 절대 경로를 사용해 Finder로 실행한 앱에서도 같은 어댑터를 찾습니다.

## 빌드와 검사

Xcode Command Line Tools와 `/usr/bin/python3`를 사용합니다.
빌드 대상은 Apple Silicon이며 macOS 14 이상 UI API를 사용합니다.
Apple Developer ID 공증 대신 로컬 실행용 ad-hoc 서명을 합니다.

```bash
./build.sh
python3 -m unittest discover -s tests -v
xcrun swiftc -D TESTING -swift-version 5 -parse-as-library -framework SwiftUI -framework AppKit Sources/App.swift Sources/Localization.swift tests/LoginParsingTests.swift -o /tmp/buzz-login-tests
/tmp/buzz-login-tests
```

빌드 결과는 `build/Buzz Account Manager.app`과 `~/Applications/Buzz Account Manager.app`입니다.
다른 Mac에는 ZIP과 `scripts/install_app.py`로 설치합니다. 공증은 포함하지 않습니다.

검증 범위: 격리된 임시 디렉토리에서 계정 생성·설정 반영·다른 에이전트 보존·충돌 차단·실패 복구·
서비스별 환경변수와 effort 전달을 검사했습니다. 설치한 앱에서 서비스 전환·모델·effort 목록과
계정 추가 화면을 확인했습니다. 실제 새 계정의 로그인 완료와 그 계정으로 모델 응답을 받는
절차는 사용자의 로그인이 필요하므로 실행하지 않았습니다.

## 자동 구독 계정 전환

에이전트 상세 화면에서 같은 서비스의 **예비 계정 1~3**을 선택하고 **한도 소진 시 예비 계정으로 자동 전환**을 켠 뒤 저장하세요. 예비 계정은 먼저 로그인해야 합니다. 현재 계정과 중복 계정은 선택할 수 없습니다. 자동 전환은 기본적으로 꺼져 있습니다.

macOS LaunchAgent가 5분마다 Codex·Claude Code 계정 잔량을 조회합니다. 앱을 닫아도 Mac에 로그인한 동안 동작합니다. 잠자기 중에는 조회하지 않으며 깨어나면 예약 조회를 재개합니다. Grok은 잔량 조회를 제공하지 않고 Ollama는 로컬 모델이므로 자동 구독 전환 대상에서 제외합니다.

현재 모델에 적용되는 한도가 소진되면 예비 계정을 순서대로 확인해 잔량이 있는 계정으로 바꿉니다. 전환 전 계정은 선택된 예비 계정의 자리에 들어갑니다. 한도가 회복됐다는 이유만으로 원래 계정으로 되돌아가지는 않습니다. 모델과 effort는 유지하며 모델의 실제 이용 권한은 서비스가 실행 시 확인합니다.

조회 실패·만료된 조회값·초기화 시각이 지난 응답은 전환 근거로 사용하지 않습니다. 사용할 예비 계정이 없으면 현재 계정을 유지합니다. 여러 에이전트를 동시에 바꿔야 하면 Buzz를 한 번만 종료하고 다시 실행합니다. 이때 모든 에이전트의 진행 중인 응답이 중단될 수 있으며 중단된 요청을 자동 재전송하지는 않습니다.

에이전트 상세 화면 상단에서 **현재 구독 계정 잔량**을 볼 수 있습니다. 기본 잔량을 먼저 표시하며 **자세히 보기**로 세부 한도를 펼칩니다. 자동 조회 결과와 현재 계정은 열린 앱에 30초 간격으로 반영됩니다. 아직 저장하지 않은 계정 선택은 현재 계정 잔량을 바꾸지 않습니다.

백그라운드 상태는 `~/.config/buzz-agents/monitor-state.json`, 예약 설정은 `~/Library/LaunchAgents/kr.co.astravision.buzz-account-monitor.plist`에 저장합니다. 상태 파일에는 계정 ID·잔량·조회 시각·전환 알림을 기록하며 인증 토큰은 기록하지 않습니다. 전환 전 프로필은 `~/.config/buzz-agents/backups/fallback-*/`에 백업합니다.

## 언어 선택

왼쪽 아래 **언어** 메뉴에서 한국어, English, Tiếng Việt 또는 시스템 설정을 선택합니다. 선택한 언어는 이 Mac에 저장되고 열린 화면에도 바로 적용됩니다. 시스템 설정은 macOS의 선호 언어 목록에서 지원 언어를 찾으며 해당 언어가 없으면 영어를 표시합니다.

계정명·에이전트명·모델 ID와 effort 값은 바꾸지 않습니다. 앱의 안내·잔량·오류는 선택한 언어로 표시하며 외부 CLI가 직접 출력한 로그와 로그인 웹페이지는 해당 서비스의 언어 설정을 따릅니다. macOS가 관리하는 앱 메뉴 이름은 시스템 언어를 따릅니다.
