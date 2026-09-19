# 다른 Mac에 설치하기

설치할 그 Mac에서 `./build.sh`로 직접 빌드하는 쪽이 제일 깔끔합니다. 이 앱은 Apple 공증 없이
로컬 실행용 ad-hoc 서명만 하기 때문에, 빌드한 앱을 ZIP으로 옮기면 Gatekeeper에 막히는 일이 생깁니다.

## 먼저 확인할 세 가지

```bash
sw_vers -productVersion   # 14.0 이상이어야 합니다
uname -m                  # arm64 = Apple Silicon, x86_64 = Intel
xcode-select -p           # 경로가 나오면 Command Line Tools가 있습니다
```

- **macOS 14.0 이상**입니다. 앱 번들의 `LSMinimumSystemVersion`이 14.0이라 그 아래에서는 실행되지 않습니다.
- **Xcode Command Line Tools가 필요합니다.** 빌드에 `xcrun swiftc`를 쓰고, 앱이 백엔드를 실행할 때 쓰는
  `/usr/bin/python3`도 Tools가 없으면 설치 창부터 띄웁니다. 없으면 `xcode-select --install`로 먼저 까세요.
- **macOS 27에서는 전체 Xcode까지 필요합니다.** 그 세대 SDK에서는 SwiftUI의 `@State`가 프로퍼티
  래퍼가 아니라 매크로입니다. 컴파일에 `libSwiftUIMacros.dylib` 플러그인이 있어야 하는데 Command Line
  Tools에는 이게 없어서, `./build.sh`가 `external macro implementation type 'SwiftUIMacros.StateMacro'
  could not be found` 에러 92개로 멈춥니다(macOS 27 + CLT 27 실측. 26도 같은 SDK 세대라 같을 겁니다).
  macOS 14·15에서는 Tools만으로 빌드됩니다. 미리 확인하려면:

  ```bash
  ls /Library/Developer/CommandLineTools/usr/lib/swift/host/plugins/   # SwiftUIMacros가 보이면 그대로 진행
  ```

  안 보이면 App Store에서 Xcode를 깔고 두 줄을 실행하세요. 라이선스 동의는 사람이 직접 해야 합니다.

  ```bash
  sudo xcodebuild -license accept
  sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
  ```
- **Python은 3.9 이상**이면 됩니다. 앱이 `/opt/homebrew/bin/python3` → `/usr/local/bin/python3` →
  Command Line Tools → `/usr/bin/python3` 순으로 실행되는 첫 Python을 고릅니다. macOS 14의
  `/usr/bin/python3`가 3.9.6이라 따로 깔 건 없습니다.

## 방법 1 — 설치할 Mac에서 빌드 (권장)

```bash
git clone https://github.com/ttalkkaklab/buzz-account-manager.git
cd buzz-account-manager
./build.sh
```

`build.sh`가 `~/Applications/Buzz Account Manager.app`에 설치하고 서명까지 검사한 뒤 설치 경로를 출력합니다.
같은 Mac에서 만든 앱에는 격리 속성이 붙지 않아 Finder에서 바로 열립니다. 설치 없이 빌드만 하려면
`BUZZ_INSTALL=0 ./build.sh`를 쓰세요.

## 방법 2 — ZIP으로 옮기기

빌드한 Mac에서 압축하고:

```bash
ditto -c -k --keepParent "build/Buzz Account Manager.app" ~/Desktop/BuzzAccountManager.zip
```

받는 Mac에서 설치합니다. 저장소를 받지 않았다면 `scripts/install_app.py` 파일 하나만 같이 옮겨도 됩니다.

```bash
python3 scripts/install_app.py ~/Downloads/BuzzAccountManager.zip
```

스크립트가 서명을 검사한 뒤 `~/Applications`에 넣고, 이미 있던 앱은
`~/.config/buzz-agents/app-backups/<날짜>/`로 옮겨 둡니다.

**아키텍처를 맞춰야 합니다.** `build.sh`에는 아키텍처 옵션이 없어서 빌드한 Mac에 맞는 바이너리가 나옵니다.
Apple Silicon에서 만든 앱은 Intel Mac에서 열리지 않습니다. 계열이 다르면 옮기지 말고 방법 1로 각자 빌드하세요.
지금까지 확인한 건 Apple Silicon 빌드입니다.

## Gatekeeper가 막을 때

`build.sh`는 `codesign --sign -`으로 ad-hoc 서명만 합니다. 공증이 없으니 AirDrop·메일·브라우저로 받은
ZIP에는 격리 속성(`com.apple.quarantine`)이 붙고, 앱을 열면 "손상되었기 때문에 열 수 없습니다"가 뜹니다.
속성을 지우면 그다음부터는 그냥 열립니다.

```bash
xattr -dr com.apple.quarantine "$HOME/Applications/Buzz Account Manager.app"
```

`scp`나 `rsync`로 옮긴 파일에는 이 속성이 붙지 않습니다.

## 설치 확인

```bash
/usr/bin/python3 "$HOME/Applications/Buzz Account Manager.app/Contents/Resources/backend.py" status
```

에이전트와 계정 목록이 담긴 JSON이 나오면 설치된 겁니다. Buzz를 아직 깔지 않았거나 에이전트를 만들기
전이라면 `Buzz를 설치하고 에이전트를 만든 뒤 새로고침하세요`가 나옵니다. 이때도 앱 설치는 끝난 상태이고,
Buzz에서 에이전트를 만든 다음 같은 명령으로 다시 확인하면 됩니다.
