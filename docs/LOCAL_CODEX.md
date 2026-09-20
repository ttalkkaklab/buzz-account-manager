# Local Codex accounts

Choose Codex when adding an account, enable the local OpenAI-compatible server option, and enter the server URL (for example `http://127.0.0.1:11235`). The server must support Responses API tool calls. The optional `/v1` suffix is normalized.

Local accounts use `/v1/models` for readiness and model selection. They do not need ChatGPT login tokens. The account gets its own `config.toml`, and the managed launcher pins the local provider in `CODEX_CONFIG` alongside the selected model. Subscription accounts retain their existing authentication checks. Local accounts cannot participate in subscription quota fallback.

An accessible model catalog does not prove that Responses API or tool calls work. Verify those with the intended model before switching an agent.

The backend `create` request accepts an optional positive integer `model_context_window` for local Codex accounts. For the verified 20b server, use `131072`. It is saved in the account's root `config.toml` and pinned in the managed launcher's `CODEX_CONFIG`, overriding inherited context limits. Other local servers keep their default unless explicitly configured; do not assume that every server supports 128K. This sets the context limit, but does not supply missing model metadata: install a verified `model_catalog_json` separately when required.

## Verification without real accounts

Run `./scripts/test.sh` and `BUZZ_INSTALL=0 ./build.sh`. The full test suite creates a temporary local HTTP server and a temporary account home, validates and applies an account without `auth.json`, and checks the launcher environment, identity preservation, unavailable servers, unknown models, and fallback boundaries. It does not modify actual agent accounts.

## Installation boundary

`BUZZ_INSTALL=0 ./build.sh` only builds the app under `build/`. The default build additionally copies the app to `~/Applications/Buzz Account Manager.app`. Opening the app calls `install-monitor`, which installs `monitor-backend.py` and its launch agent. A successful account apply copies the bundled backend to `~/.config/buzz-agents/manager-backend.py` and updates the agent launcher and configuration, after requiring Buzz to be closed.

Building alone does not update the installed manager backend. Obtain the required operational approval before installing, opening the new production app, or applying account changes.
