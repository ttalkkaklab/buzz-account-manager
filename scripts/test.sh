#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m unittest discover -s tests -v
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
xcrun swiftc -D TESTING -swift-version 5 -parse-as-library -framework SwiftUI -framework AppKit Sources/App.swift Sources/Controls.swift Sources/Localization.swift tests/LoginParsingTests.swift -o "$TEST_DIR/login-tests"
"$TEST_DIR/login-tests"
cp tests/fixtures/navigation_backend.py "$TEST_DIR/backend.py"
xcrun swiftc -D TESTING -swift-version 5 -parse-as-library -framework SwiftUI -framework AppKit Sources/App.swift Sources/Controls.swift Sources/Localization.swift tests/NavigationTests.swift -o "$TEST_DIR/navigation-tests"
python3 - "$TEST_DIR" <<'PYTHON'
import os, pathlib, subprocess, sys
root = pathlib.Path(sys.argv[1])
(root / 'home').mkdir()
subprocess.run([str(root / 'navigation-tests')], env=dict(os.environ, HOME=str(root / 'home')), check=True)
PYTHON
xcrun swiftc -D TESTING Sources/Localization.swift tests/LocalizationTests.swift -o "$TEST_DIR/localization-tests"
"$TEST_DIR/localization-tests"
