#!/usr/bin/env python3
"""Refuse to install an app bundle older than the one already installed."""
import os
from pathlib import Path
import plistlib
import sys

FORCE = 'BUZZ_INSTALL_FORCE'


def bundle_version(bundle):
    """Return CFBundleVersion as an int, or None when it cannot be read."""
    info = Path(bundle) / 'Contents/Info.plist'
    if not info.exists():
        return None
    try:
        return int(plistlib.loads(info.read_bytes())['CFBundleVersion'])
    except (KeyError, ValueError, plistlib.InvalidFileException):
        return None


def downgrade_error(candidate, installed):
    """Return the refusal message, or None when installing is allowed."""
    current = bundle_version(installed)
    if current is None:
        return None
    version = bundle_version(candidate)
    if version is None or version >= current:
        return None
    return (f'Refusing to replace build {current} with older build {version}. '
            f'Build from the integrated source, or set {FORCE}=1 to install this build anyway.')


def main(argv, environ):
    if environ.get(FORCE) == '1':
        return 0
    message = downgrade_error(argv[1], argv[2])
    if message is None:
        return 0
    print(message, file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv, os.environ))
