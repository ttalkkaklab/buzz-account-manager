<p align="center"><img src="Resources/AppIcon.png" width="128" alt="Ttalkkak Man mascot"></p>

# Buzz Account Manager

**Give each Buzz agent its own subscription account, model, and reasoning effort.**

[Download for macOS](https://github.com/ttalkkaklab/buzz-account-manager/releases/latest) · [한국어](README.ko.md) · [Tiếng Việt](README.vi.md) · [Report a bug](https://github.com/ttalkkaklab/buzz-account-manager/issues)

A native SwiftUI companion for [Buzz Desktop](https://github.com/block/buzz). Manage Codex, Claude Code, and Grok accounts, or connect an Ollama server. Interface languages: **English, Korean, and Vietnamese**, switchable without restarting.

This is an independent community project, not an official app from Buzz or any AI provider.

## What you can do

- Assign separate subscription accounts to individual agents while preserving their Buzz identity and team.
- Choose a model and reasoning effort from one screen.
- Copy the Codex device sign-in code directly from the login window.
- See Codex and Claude Code remaining usage on account and agent screens; expand details for additional limits and reset times.
- Configure up to **three fallback accounts per agent**. A background task checks usage every five minutes and can switch when the applicable limit is exhausted.
- Use local Ollama models that support tool calls through the Claude ACP adapter.

Quota checks do not generate model responses. Remaining usage is the percentage reported by the provider, not an exact token balance. Grok quota lookup is not supported. Model availability and subscription access are determined by the provider.

## Install

The downloadable build targets **Apple Silicon, macOS 14 or later**. You also need:

- Buzz Desktop installed at `/Applications/Buzz.app`, with managed agents configured.
- Xcode Command Line Tools, including `/usr/bin/python3` (`xcode-select --install`).
- The CLI and ACP adapter for your provider: `codex` and `codex-acp`, `claude` and `claude-agent-acp`, or `grok`.
- For Ollama: a running server, a tool-capable local model, and `claude-agent-acp`.

1. Download the ZIP from [Releases](https://github.com/ttalkkaklab/buzz-account-manager/releases/latest).
2. Unzip it and move **Buzz Account Manager.app** into `~/Applications` (create this folder if needed).
3. Open the app. Select **Subscription accounts → Add account**, then sign in.
4. Select an agent, choose its account, model, and effort, then click **Save and restart Buzz**.

The build is ad-hoc signed and **not Apple-notarized**. If macOS blocks it, review the app in System Settings → Privacy & Security, or build from source. No subscription credentials are included in the download.

## Automatic account switching

On an agent screen, choose up to three signed-in fallback accounts from the same provider, enable automatic switching, and save. It is off by default.

The monitor runs every five minutes while your macOS user is logged in and the Mac is awake, even when this app is closed. It switches only when a fresh, successful quota response says the current model’s applicable limit is exhausted and a fallback has available quota. Failed, stale, or ambiguous checks do not trigger a switch.

The old account moves into the selected fallback slot. Recovery of its quota alone does not switch it back. Model and effort stay unchanged; the new account must still have access to that model.

**Saving agent settings or automatically switching accounts restarts Buzz. This can interrupt responses from all agents. Interrupted requests are not replayed.**

## Local data and credentials

The app uses the provider CLI’s authentication storage. Added accounts have separate directories and CLI sessions. The default CLI account is preserved.

| Data | Location |
| --- | --- |
| Account registry | `~/.config/buzz-agents/account-manager.json` |
| Separate CLI profiles | `~/.config/buzz-agents/accounts/` |
| Agent account assignments | `~/.config/buzz-agents/agent-[public-key].json` |
| Backups | `~/.config/buzz-agents/backups/` |
| Cached quota results and switch events | `~/.config/buzz-agents/monitor-state.json` |
| Five-minute monitor | `~/Library/LaunchAgents/kr.co.astravision.buzz-account-monitor.plist` |

The monitor stores quota results, account IDs, timestamps, and event messages, not authentication tokens. Quota requests go to the provider using the selected account’s credentials. This app does not add telemetry or a central account server.

Separate directories are **not a security sandbox**: agents still run as the same macOS user. Existing custom CLI configuration may have its own authentication and network settings.

## Build and test

SwiftUI/AppKit plus Python’s standard library. No Python package installation is required.

```sh
git clone https://github.com/ttalkkaklab/buzz-account-manager.git
cd buzz-account-manager
./scripts/test.sh
BUZZ_INSTALL=0 ./build.sh
```

The bundle is written to `build/Buzz Account Manager.app`. Running `./build.sh` without `BUZZ_INSTALL=0` also installs it into `~/Applications`.

Tests cover account isolation, settings preservation, rollback, quota interpretation, automatic switching, login-code parsing, and all three translation catalogs. Provider protocols and Buzz’s local settings format can change; full account login and model execution require your own installed CLIs and subscriptions.

## Language and contributions

Use the **Language** menu at the bottom of the sidebar. The selection is saved per Mac. System default selects a supported macOS preferred language, or English if none match. User-provided names and model IDs are preserved. External CLI logs and sign-in websites use their own language settings.

Translations are in [`Resources/Translations.json`](Resources/Translations.json). Bug fixes, language improvements, and compatibility reports are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md); please never attach tokens, credentials, or private agent configuration to an issue.

## License

[MIT](LICENSE). Provider CLIs, Buzz, and Ollama are separate projects with their own licenses. The Ttalkkak Man icon was generated using the built-in Codex image tool; its source image and prompt are included in this repository.
