#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m unittest discover -s tests -v
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
xcrun swiftc -D TESTING -swift-version 5 -parse-as-library -framework SwiftUI -framework AppKit Sources/App.swift Sources/Localization.swift tests/LoginParsingTests.swift -o "$TEST_DIR/login-tests"
"$TEST_DIR/login-tests"
xcrun swiftc -D TESTING Sources/Localization.swift tests/LocalizationTests.swift -o "$TEST_DIR/localization-tests"
"$TEST_DIR/localization-tests"
