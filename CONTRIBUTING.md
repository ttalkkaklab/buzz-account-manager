# Contributing

Open an issue with your macOS version, app version, provider CLI version, and steps to reproduce. Remove account names, tokens, sign-in codes, and private agent data from logs and screenshots.

For code changes, run `./scripts/test.sh` and `BUZZ_INSTALL=0 ./build.sh` on macOS before opening a pull request. Keep tests isolated from real accounts and do not query live subscriptions in CI.

Translations live in `Resources/Translations.json`. Preserve placeholders such as `{0}` and `%.1f%%`. Korean keys are the source text; English and Vietnamese values must both be present. User-provided account names, agent identities, model IDs, and provider protocol fields must not be translated.

Never commit runtime account files, credentials, environment files, or app build output. If a change touches account switching, include tests for failed quota checks and preservation of the agent’s identity, model, and effort.

Every Python test module must import `sandbox` before loading application code;
`tests/test_sandbox.py` fails the suite when a module forgets.
`python -m unittest discover -s tests -v` automatically replaces HOME, USERPROFILE,
APPDATA, LOCALAPPDATA, HOMEDRIVE/HOMEPATH, and temporary directories with disposable
paths. A Python audit hook refuses writes, directory creation, atomic replacement,
removal, truncation, permission changes, symbolic and hard links, and the Windows
`CopyFile2` fast path outside that sandbox, including an accidentally restored
APPDATA. Relative names given against a directory descriptor, as `shutil.rmtree`
does on POSIX, are resolved through that descriptor, and refused when the platform
cannot name it.
This guards accidental Python writes; it does not sandbox arbitrary subprocesses.
Keep subprocess fixtures isolated and mock live process/task operations.

When changing this protection, run the full suite from a shell whose APPDATA and
other user directories already point to temporary folders. Put a canary at
`APPDATA/xyz.block.buzz.app/agents/managed-agents.json` and verify its hash before
and after the suite. Never validate isolation changes against real agent data.
The suite includes a fresh-process regression test for this inherited-APPDATA
canary and attempts to restore that path after bootstrap.
