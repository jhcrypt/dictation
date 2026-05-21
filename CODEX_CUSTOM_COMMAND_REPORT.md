Files changed:
- `src/hooks/useGlobalHotkey.ts`

Diff summary:
- Added runtime custom-command types:
  - `CustomCommandAction`
  - `RuntimeCustomCommand`
- Added helper functions in the dictation controller:
  - `normalizeTrigger(text)`
  - `runCustomCommand(spokenText)`
- Added custom-command dispatch inside `stopAndTranscribe()` after successful/non-empty transcript:
  - loads commands via `invoke("load_custom_commands")`
  - exact trigger match (normalized, min 2 words)
  - executes `open_url` and `open_app` directly
  - maps `type_text` to substituted `textToPaste`
- Preserved existing dictation paste path for non-match.
- Updated downstream HUD/history fields to use substituted text/status when applicable.

Jarvis Commands gate present: Yes

Gate location:
- `src/hooks/useGlobalHotkey.ts` inside `stopAndTranscribe()` in the successful transcription branch, immediately before `runCustomCommand(trimmed)`:
  - `if (settingsRef.current.jarvis_enabled === true) { ... }`
  - when false, custom dispatch is skipped and normal dictation paste path continues unchanged.

How trigger matching works:
- Spoken text normalization: `trim()`, lowercase, remove trailing punctuation `[.,!?]`.
- Command trigger normalization uses same function.
- Match rule is exact equality on normalized string.
- Trigger must have at least 2 words to be considered.

Supported action types:
- `open_url`
- `open_app`
- `type_text`

Manual test result:
- `npm run tauri dev` starts successfully (Vite + Tauri app process + hotkey listener active).
- Full interaction tests (speaking trigger phrases, toggling Jarvis Commands setting, verifying clipboard/sounds in live app) require in-app/UI interaction and microphone input; these cannot be fully executed from this non-interactive CLI session.
- Behavior inferred from code:
  - If trigger matches `open_url`/`open_app`, action executes and normal paste is skipped.
  - If trigger matches `type_text`, substituted text follows existing paste path.
  - If no trigger matches, existing paste path remains unchanged.
  - Dispatch touches only transcription->command decision logic; paste/clipboard internals are unchanged.
  - Wake-word logic remains untouched.
  - Dispatch is now gated by `settingsRef.current.jarvis_enabled === true`.

npx tsc result:
- `npx tsc --noEmit` passed (exit code 0).

cargo check result:
- `cd src-tauri && cargo check` passed (exit code 0).

Any concerns:
- None from compile/static checks after adding the Jarvis Commands gate.
- Manual voice-driven behavioral verification still requires interactive microphone/UI testing in the running app session.