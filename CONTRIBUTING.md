# Contributing

Open an issue with your macOS version, app version, provider CLI version, and steps to reproduce. Remove account names, tokens, sign-in codes, and private agent data from logs and screenshots.

For code changes, run `./scripts/test.sh` and `BUZZ_INSTALL=0 ./build.sh` on macOS before opening a pull request. Keep tests isolated from real accounts and do not query live subscriptions in CI.

Translations live in `Resources/Translations.json`. Preserve placeholders such as `{0}` and `%.1f%%`. Korean keys are the source text; English and Vietnamese values must both be present. User-provided account names, agent identities, model IDs, and provider protocol fields must not be translated.

Never commit runtime account files, credentials, environment files, or app build output. If a change touches account switching, include tests for failed quota checks and preservation of the agent’s identity, model, and effort.
