#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
APP="$HOME/Applications/Buzz Account Manager.app"
BUILD="$(pwd)/build/Buzz Account Manager.app"
mkdir -p "$BUILD/Contents/MacOS" "$BUILD/Contents/Resources"
xcrun swiftc -swift-version 5 -O -parse-as-library -framework SwiftUI -framework AppKit Sources/App.swift Sources/Localization.swift -o "$BUILD/Contents/MacOS/BuzzAccountManager"
cp Resources/Translations.json "$BUILD/Contents/Resources/Translations.json"
cp Resources/backend.py "$BUILD/Contents/Resources/backend.py"
ICONSET="$(pwd)/build/AppIcon.iconset"
mkdir -p "$ICONSET"
for SIZE in 16 32 128 256 512; do
    sips -z "$SIZE" "$SIZE" Resources/AppIcon.png --out "$ICONSET/icon_${SIZE}x${SIZE}.png" >/dev/null
    DOUBLE=$((SIZE * 2))
    sips -z "$DOUBLE" "$DOUBLE" Resources/AppIcon.png --out "$ICONSET/icon_${SIZE}x${SIZE}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$BUILD/Contents/Resources/AppIcon.icns"
cp Resources/AppIcon.png "$BUILD/Contents/Resources/AppIcon.png"
cat > "$BUILD/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>BuzzAccountManager</string>
<key>CFBundleIdentifier</key><string>kr.co.astravision.buzz-account-manager</string>
<key>CFBundleName</key><string>Buzz 계정 관리</string>
<key>CFBundleDisplayName</key><string>Buzz 계정 관리</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>1.4.5</string>
<key>CFBundleVersion</key><string>11</string>
<key>CFBundleDevelopmentRegion</key><string>en</string>
<key>CFBundleLocalizations</key><array><string>ko</string><string>en</string><string>vi</string></array>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
for LANG in ko en vi; do
    mkdir -p "$BUILD/Contents/Resources/$LANG.lproj"
done
printf '"CFBundleDisplayName" = "Buzz 계정 관리";\n"CFBundleName" = "Buzz 계정 관리";\n' > "$BUILD/Contents/Resources/ko.lproj/InfoPlist.strings"
printf '"CFBundleDisplayName" = "Buzz Account Manager";\n"CFBundleName" = "Buzz Account Manager";\n' > "$BUILD/Contents/Resources/en.lproj/InfoPlist.strings"
printf '"CFBundleDisplayName" = "Quản lý tài khoản Buzz";\n"CFBundleName" = "Quản lý tài khoản Buzz";\n' > "$BUILD/Contents/Resources/vi.lproj/InfoPlist.strings"
codesign --force --deep --sign - "$BUILD"
if [[ "${BUZZ_INSTALL:-1}" == "1" ]]; then
    mkdir -p "$HOME/Applications"
    ditto "$BUILD" "$APP"
    codesign --verify --deep --strict "$APP"
else
    APP="$BUILD"
fi
printf '%s\n' "$APP"
