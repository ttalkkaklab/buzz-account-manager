# Windows UX verification — 2026-09-27

Base: `078f5d2ee1f96bba6c7f8bf6ff264be1ee50d745`, PR #5 branch `feat/account-delete-and-provider-tabs`.
Specification: the 411-line UX_SPEC.md supplied in Buzz event `68769e0db5991781f7164ac78db7218b8153dfcb247122e8bbc6944827d7077d`, SHA-256 `a746d5059c3435f26768b3919f5b6ebb915ff0701f091c7338a6fd3d704ad05f`.
The corrected §5.2 checklist has **19 rows**, not 17.

| # | Spec line | Requirement | Implementation | Verification |
|---|---:|---|---|---|
| 1 | 369 | Shared catalog and dynamic translations | Localization.ps1; build.py payload constants | PASS: keys en/vi, prefix/suffix, literal placeholder runtime tests |
| 2 | 370 | Immediate language selection | Apply-Language; Render-General | PASS: real WinForms selection ko/en/vi and screenshots; registry restored |
| 3 | 371 | Localized ISO dates | Display-Date | PASS: fractional ISO date runtime test; synthetic quota display |
| 4 | 372 | Icon rail | E192/E716/E713 bitmaps, tooltips, accessible names, Ctrl+1/2/3 | PASS: glyphs visible at native 96 DPI; actual 150%/200% UNVERIFIED |
| 5 | 373 | Content switching | Dock=Fill page panels | PASS: rail button clicks |
| 6 | 374 | Provider filters | RadioButton group and visible account counts | PASS: Grok 1 → 0 → 1, empty state and restore |
| 7 | 375 | Provider cards/account blocks | Render-Accounts vertical flow | PASS: all-provider screenshots and scrolling |
| 8 | 376 | Usage view | Add-Quota | 부분 — `PBM_SETSTATE` 색 미반영. Synthetic 15.5% fixture, date, low-usage text and details verified; live quota UNVERIFIED |
| 9 | 377 | Provider badges | Badge/Provider-Color | PASS: rendered shared colors and names |
| 10 | 378 | Hidden default restore | Filtered disclosure and restore action | PASS: hidden default Grok restored |
| 11 | 379 | Delete confirmation | MessageBox YesNo, Button2 | PASS: No preserves count; Yes hides account; auth file SHA unchanged |
| 12 | 380 | Add/edit dialogs | Show-AccountDialog | PASS: isolated server add and label edit containing literal `{0}` |
| 13 | 381 | Login completion | HasExited, 1000 ms timer; localized console | PASS with harmless child process; real provider sign-in UNVERIFIED |
| 14 | 382 | Stop Buzz before agent save | validate → stop-buzz → status polling → apply | Implemented, mocked dispatch PASS; **미검증 — 운영 Buzz 종료 위험** |
| 15 | 383 | Three ordered fallbacks | ComboBox ×3, duplicate/current exclusion | Code reviewed; live automatic switching UNVERIFIED |
| 16 | 384 | Agent list | Two-column ListView | PASS: real agent screen fixture |
| 17 | 385 | Refresh | Header button and F5 | PASS: button refresh; keyboard shortcut code reviewed |
| 18 | 386 | Localized error title | Show-Error | Code reviewed; catalog test PASS |
| 19 | 387 | Documentation | Windows README and three root READMEs | Updated and reviewed |

## Runtime evidence and boundaries

- OS: Microsoft Windows 11 Pro, 25H2, build **26200.9550** (CIM Caption/Version plus CurrentVersion DisplayVersion/UBR; registry ProductName alone incorrectly says Windows 10).
- GUI payload uses the build's pinned Python 3.13.12 embeddable archive, verified SHA-256. Python unit suite uses installed Python 3.14.
- Each child process receives isolated APPDATA, USERPROFILE, HOME, HOMEDRIVE, HOMEPATH and LOCALAPPDATA. Fixtures are outside the repository. All account homes are fake, and Ollama uses unreachable localhost port 9. No real managed-agent file was read.
- Account edit save invokes only `update`. The distinct agent save invokes `stop-buzz` and optionally `install-monitor`; **neither operation was exercised against the real system**. No automatic switching checkbox + save test was performed.
- Existing scheduled task `Buzz Account Manager Monitor-zeans` was already present/Ready. Its `/Query /XML` bytes were identical before/after GUI verification. No task was installed, deleted or changed.
- DisplayLanguage value was absent before the test and absent again after restoration/readback. Other registry values were retained.
- Production metadata only: managed-agents.json LastWriteTime **2026-09-27 12:19:42 KST**, account-manager.json **2026-09-25 08:10:23 KST**, both before the initial baseline run ending **2026-09-27 20:57:36 KST**.
- 150%/200% captures are explicitly **synthetic Form.Scale layout exercises**, not proof of OS DPI behavior. Actual display-scale switching was not performed on this active shared desktop. Native DPI and glyph visibility were checked at 96 DPI.
- The themed ProgressBar did not display the requested low-usage color on this desktop; the specified orange percentage-text fallback is visible. Subscription quota data was synthetic, not queried from a provider.
- Installer/NSIS build and live login/model execution were not run. New en/vi copy follows the supplied draft specification and still needs the team's translation review.

## Full Python suite and baseline comparison

Run through an isolated-environment subprocess: `python -m unittest discover -s tests -v`.

| State | Tests | Failures | Errors | Skipped |
|---|---:|---:|---:|---:|
| Base 078f5d2, non-executable launcher-byte fixture supplied | 73 | 6 | 10 | 1 |
| Changed tree, same harness | 77 | 6 | 10 | 1 |

The four added tests pass on Windows: catalog keys, mocked stop-buzz dispatch, payload catalog inclusion, and PowerShell localization runtime. Previously passing tests remain passing. This is **not an all-green suite claim**. The MacBook lead accepted these baseline limitations in event `ca951ca0953858754c0eb30561132327b808bd4f34db8d6130834b8cefc916fa` and will verify macOS regression separately.

| Existing limitation | Count | Cause | Follow-up |
|---|---:|---|---|
| Path.home RuntimeError | 10 | Tests deliberately clear the environment, removing USERPROFILE; Windows has no pwd fallback | Separate platform-boundary test design; do not weaken clear=True |
| POSIX permission assertions | 2 | NTFS mode values do not implement the asserted POSIX 0600/0700 semantics | Platform-specific assertions |
| CLI path fixtures | 2 | registered_paths reads Windows registry PATH; tests expect macOS/npm-global fixture paths | Mock Windows discovery boundary |
| osascript expectation | 2 | Tests hard-code /usr/bin/osascript; Windows uses powershell.exe | Platform-specific expectations |

The latter two failures compare mocked `subprocess.run` arguments (`'powershell.exe' != '/usr/bin/osascript'`), directly showing no real process shutdown was dispatched by those tests. The temporary `Resources/agent-launcher.exe` byte fixture is **not a product binary and must not be committed**.

## PR #7 review follow-up — M1/M2/M3

- M1: backend calls restore the captured active form's original Enabled and UseWaitCursor values. In the isolated account-add modal, an invalid Ollama endpoint produced a real backend error/MessageBox; native IsWindowEnabled confirmed the main window stayed disabled afterward while the account modal was enabled. Closing the modal re-enabled the main window.
- M2: agent selection queues Render-Content with BeginInvoke. Across 60 alternating native mouse clicks on two fixture agents, an additional SelectedIndexChanged handler observed the list still alive; after pumping messages the old list was disposed and the requested agent remained selected. No crash occurred during this run.
- M3: row 8 is explicitly partial because PBM_SETSTATE coloring was not reflected by the themed progress bar.
- The six environment variables remain isolated for every test child. DisplayLanguage was absent before and after restoration/readback; scheduled-task XML was byte-identical. Agent save, Buzz shutdown and monitor installation were not invoked.
- Evidence runner and output: `.scratch/Senior_ACCOUNT_REVIEW_DRIVER_20260927.ps1` and `.scratch/Senior_ACCOUNT_REVIEW_SANDBOX_20260927/review-gui-result.txt` in the originating Windows workspace. Full Python suite remains 77 tests, 6 failures, 10 errors, 1 skip, matching the accepted portability baseline.
