# Feature Parity Audit — Quill Tauri vs. Stable Python App

**Updated:** 2026-05-23  
**Reference source:** `/Users/user1/dictation/README.md` + `jarvis_dictation.py`  
**Tauri project:** `/Users/user1/jarvis-tauri`  
**Last confirmed commit:** `d4e7eab`

---

## Status legend

| Tag | Meaning |
|---|---|
| ✅ Confirmed working | Verified by code inspection + test or strong code-level proof |
| 🟡 Partially working | Core behavior present but gaps or untested paths |
| 🔴 Python parity pending | Worked in stable Python; not yet in Tauri |
| ⏸ Intentionally deferred | Agreed to skip for now |
| ❓ Needs user decision | Unclear if wanted, or depends on a product choice |

---

## A. Core Dictation

| Feature | Status | Notes |
|---|---|---|
| Push-to-talk (hold mode) | ✅ Confirmed | `useGlobalHotkey.ts` hold → start/stop cycle |
| Toggle mode (press once start, press again stop) | ✅ Confirmed | `toggle_mode` setting; tray + SetupPage UI |
| Right Option hotkey | ✅ Confirmed | Default; `hotkey.rs` CGEventTap |
| F13 / F14 / F15 hotkeys | ✅ Confirmed | SetupPage + `hotkey_label` routing in `hotkey.rs` |
| Cancel with Escape | ✅ Confirmed | `useGlobalHotkey.ts` lines 837–840 |
| Short tap ignored (tap_ignored HUD state) | ✅ Confirmed | `handleShortTap()` + HudApp `tap_ignored` state |
| Start/stop sounds | ✅ Confirmed | `play_recording_sound` Rust command; guarded by `play_sounds` |
| HUD states (idle/recording/transcribing/cleanup/inserted/error/command) | ✅ Confirmed | `HudApp.tsx` covers all states |
| Live waveform during recording (VAD-aware) | ✅ Confirmed | Audio level polling at 60 ms; `voice_active` scaling |
| Active app targeting (paste to frontmost app) | ✅ Confirmed | `LastTargetApp` state; CGEvent paste with pre-recorded target |
| Paste into active app | ✅ Confirmed | `paste_text` Rust command; trailing space parity |
| Clipboard preservation after paste | ✅ Confirmed | commit `0e40125`; pbcopy/pbpaste round-trip |
| Media pause/resume during recording | ✅ Confirmed | `pause_media` / `resume_media` Rust commands with mute-state guard |
| Timing / performance logs | ✅ Confirmed | `dictation-timing` event emitted with full breakdown |
| Show/Hide HUD from tray | ✅ Confirmed | `hide_hud` tray CheckMenuItem + HUD window show/hide |
| Draggable HUD, position persisted | ✅ Confirmed | `onMoved` + `save_hud_position` Tauri command |
| Active app icon shown in HUD | ✅ Confirmed | `get_target_app_icon` Rust + `fetchAppIcon` in HudApp |
| Safe-mode guards paste from overwriting clipboard | ✅ Confirmed | Paste skipped when `safe_mode = true` |
| Helpful HUD tips / startup tips mode | 🔴 Python parity pending | Python had `show_startup_tips` setting; not in Tauri HUD or settings |

---

## B. Whisper / Transcription

| Feature | Status | Notes |
|---|---|---|
| Local faster-whisper transcription | ✅ Confirmed | `cmd_transcribe_last` in sidecar |
| Whisper model selection (tiny.en, base.en, small.en, medium.en) | ✅ Confirmed | Tray submenu + AudioPage; `model` setting |
| large-v2 / large-v3 support | ✅ Confirmed | AudioPage free-text override field accepts any model name |
| distil-medium.en / distil-large-v3 support | ✅ Confirmed | Same free-text field; sidecar uses model string directly |
| Language selection ("I'm Speaking") | ✅ Confirmed | `language` setting → Whisper `language` param; AudioPage UI |
| Auto-detect language | ✅ Confirmed | `auto_detect` setting → Whisper language=None |
| Microphone selection | ✅ Confirmed | `mic_device` + `mic_device_name` settings; `list_microphones` command |
| Temp WAV creation and cleanup | ✅ Confirmed | `cmd_start_recording` / `cmd_stop_recording` create/delete `_tmp_recording.wav` |
| Silence / too-quiet audio handling | ✅ Confirmed | Sidecar checks RMS floor before transcribing |
| 16 kHz sample rate | ✅ Confirmed | `sample_rate=16000` in sidecar sounddevice call |
| VAD settings | ✅ Confirmed | `vad_filter=True, vad_parameters={"threshold":0.25}` in sidecar |
| Whisper initial_prompt from vocabulary | ✅ Confirmed | `get_personal_prompt()` builds hint string; commit `0e40125` |
| Whisper deduplicate hallucinations | 🔴 Python parity pending | Python has `_deduplicate_whisper()`; not ported to sidecar |
| Cloud fallback when cloud call fails | 🔴 Python parity pending | Cloud mode UI exists but sidecar has no OpenAI API path at all |

---

## C. Local AI Cleanup / Ollama

| Feature | Status | Notes |
|---|---|---|
| Ollama optional (app works without it) | ✅ Confirmed | `ai_cleanup_mode = auto` skips silently if Ollama absent |
| AI Cleanup mode: auto / on / off | ✅ Confirmed | Setting saved and passed to sidecar |
| Recommended model qwen2.5:3b | ✅ Confirmed | `install_ollama_model` Rust command; AiCleanupPage |
| Ollama installed/running/model installed status card | ✅ Confirmed | `check_ollama_status` Rust command; AiCleanupPage live card |
| Install recommended model button | ✅ Confirmed | AiCleanupPage; streams install progress |
| Check Again button | ✅ Confirmed | AiCleanupPage re-probes Ollama |
| Test Cleanup button | ✅ Confirmed | AiCleanupPage hits Ollama HTTP directly; shows before/after |
| Disable AI Cleanup button | ✅ Confirmed | AiCleanupPage sets `ai_cleanup_mode = off` |
| Correction Strength: Off / Light / Standard / Strong | ✅ Confirmed | Tray submenu + sidecar `correction_strength` prompt tuning |
| Safe Mode disables cleanup | ✅ Confirmed | `safe_mode` check in sidecar `cmd_transcribe_last` |
| Short/simple cleanup skip logic | ✅ Confirmed | commit `0e40125`; sidecar mirrors Python skip heuristics |
| Safety filter rejects answers/expansions | ✅ Confirmed | Sidecar `_ollama_safety_check()` ported from Python |
| Translation via local model (Ollama) | 🟡 Partially working | `translate_my_dictation` setting → Ollama translate call in sidecar; `translate that` / `translate selected text` voice commands not ported from Python |
| Open Ollama Download Page button | ✅ Confirmed | AiCleanupPage `open_url` call |
| Context-aware formatting (app-based tone rules) | ✅ Confirmed | `context_format` setting; `APP_FORMAT_RULES` in sidecar |

---

## D. Writing Profiles

| Feature | Status | Notes |
|---|---|---|
| All 10 profiles (General/Professional/Email/Developer/Medical/Legal/Sales/Notes/Creative/Verbatim) | ✅ Confirmed | Sidecar `PROFILES` dict; WritingProfilesPage; tray submenu |
| Auto-detect profile by app | ✅ Confirmed | `auto_detect` setting; `APP_PROFILE_MAP` in sidecar |
| Show active profile in HUD | ✅ Confirmed | `show_active_profile` setting; `profile` in HUD payload |
| Profile logged in history | ✅ Confirmed | `profile` field in `HistoryEntry` |
| App profile rules (Mail→Email, Terminal→Developer, etc.) | ✅ Confirmed | Sidecar `APP_PROFILE_MAP` matches Python |

---

## E. Voice Commands — Scratch / Undo

| Feature | Status | Notes |
|---|---|---|
| `scratch that` / `undo that` / `delete that` | ✅ Confirmed | `_cmd_detect` in sidecar; 60/60 tests pass |
| `scratch` / `undo` / `scratch last` | ✅ Confirmed | Same |
| `scratch again` / `undo again` | ✅ Confirmed | Same |
| `scratch last 2` / `scratch two` / `scratch last 3` | ✅ Confirmed | Same |
| `scratch all` / `undo all` / `clear all` | ✅ Confirmed | Same |
| `undo dictation` / `undo last` (redo stack) | 🔴 Python parity pending | Python had a redo stack; Tauri sidecar has no redo stack |
| `redo dictation` / `redo last` | 🔴 Python parity pending | Same — redo not ported |
| `re-insert last` / `insert last` / `paste last` | ✅ Confirmed | `_cmd_detect` paste_text action |
| Backspace count includes trailing space | ✅ Confirmed | `+1` in `_cmd_detect` scratch counter |

---

## F. Voice Commands — Formatting

| Feature | Status | Notes |
|---|---|---|
| `all caps` / `make caps` / `capitalize that` | ✅ Confirmed | `_cmd_detect` FORMAT_COMMANDS |
| `make bold` / `bold that` | ✅ Confirmed | Same |
| `make italic` / `italic that` | ✅ Confirmed | Same |
| `format as code` / `code that` / `make code` | ✅ Confirmed | Same |
| `make heading` / `heading that` / `make title` | ✅ Confirmed | Same |
| `make bullet` / `bullet that` / `create list` / `make list` | ✅ Confirmed | Same; `_fmt_bullet` with `•` |
| `make quote` / `quote that` / `block quote` | ✅ Confirmed | Same |
| `strikethrough that` / `strike that` | ✅ Confirmed | Same |
| Inline formatting (text before trigger) | ✅ Confirmed | `hit_idx` detection in `_cmd_detect` |
| Standalone formatting (applies to last dictation) | ✅ Confirmed | `format_paste` action with backspace count |
| Rust `send_backspaces` command | ✅ Confirmed | `commands.rs`; CGEvent key repeat |

---

## G. Voice Commands — Editing / Navigation / Punctuation

| Feature | Status | Notes |
|---|---|---|
| `period` / `full stop` | ✅ Confirmed | `PUNCT_COMMANDS` in sidecar |
| `comma` | ✅ Confirmed | Same |
| `exclamation point` / `exclamation mark` | ✅ Confirmed | Same |
| `question mark` | ✅ Confirmed | Same |
| `colon` / `semicolon` | ✅ Confirmed | Same |
| `ellipsis` | ✅ Confirmed | Same |
| `open paren` / `close paren` | ✅ Confirmed | Same |
| `dash` / `hyphen` | ✅ Confirmed | Same |
| `new line` / `next line` | ✅ Confirmed | `keypress` Return ×1 |
| `new paragraph` / `next paragraph` | ✅ Confirmed | `keypress` Return ×2 |
| `tab` / `indent` | ✅ Confirmed | `keypress` Tab |
| `select all` | ✅ Confirmed | `key_combo` Cmd+A |
| `new line` smart Shift+Enter in chat apps | 🔴 Python parity pending | Python detected Slack/Messages and sent Shift+Enter; not ported |
| `copy that` / `copy last` | ✅ Confirmed | `copy_text` action + `copy_to_clipboard_str` |
| `copy all` | ✅ Confirmed | `copy_all` action → Cmd+A + Cmd+C |
| `paste` / `paste that` | ✅ Confirmed | `key_combo` Cmd+V |
| `show history` / `dictation history` / `view history` | ✅ Confirmed | `navigate` → `nav-history` event |
| `correct that` / `add correction` / `fix that` | ✅ Confirmed | `navigate` → `nav-vocabulary` event |

---

## H. Jarvis Commands — App & System Control

> **Summary: NONE of these are wired up in the Tauri build.** The Python `_fast_jarvis_match()` is not ported to the sidecar. The only Jarvis-like behavior in Tauri is the **Custom Commands** feature (user-defined open_url / open_app / type_text). All entries below reflect Python parity gaps.

| Feature | Status | Notes |
|---|---|---|
| `open [any app]` (built-in, no custom command needed) | 🔴 Python parity pending | Python `_fast_jarvis_match` `open_app` handler |
| `open Safari / Slack / Terminal / Notes / Calendar / Messages / Maps / FaceTime` | 🔴 Python parity pending | Same |
| `open Netflix / open YouTube / open Spotify` (opens URL) | 🔴 Python parity pending | Python has website URL map; `open_url` Rust command exists |
| `search for [query]` / `google [query]` / `look up [query]` | 🔴 Python parity pending | Python DuckDuckGo search; `open_url` Rust command exists |
| `volume up` / `volume down` / `mute` / `unmute` | 🔴 Python parity pending | Python uses osascript; `pause_media` Rust uses osascript but not exposed as Jarvis command |
| `set volume to [0–100]` | 🔴 Python parity pending | Python parses number and runs osascript |
| `close [app]` / `kill [app]` | 🔴 Python parity pending | Python runs Cmd+Q / `killall` |
| Custom Commands (user-defined) | ✅ Confirmed | `load_custom_commands` + `open_url` + `open_app` + type_text |

**Note:** `open_url` and `open_app` Rust commands already exist. The missing layer is the built-in pattern detection that converts spoken phrases like "open Safari" or "search for cats" into those commands without requiring user-defined custom commands.

---

## I. Email Commands

| Feature | Status | Notes |
|---|---|---|
| `email [name]` / `compose email to [name]` / etc. | 🔴 Python parity pending | Python `_fast_jarvis_match` → `draft_email` → tries Spark/Mail/Outlook via AppleScript |
| Contacts lookup by name | 🔴 Python parity pending | Contacts UI exists in Tauri (ContactsPage) but lookup not wired to email command |
| Body extraction from spoken phrase | 🔴 Python parity pending | Python has marker-based body split ("tell him…", "let her know…") |
| Spark Desktop → Spark → Mail → Outlook fallback | 🔴 Python parity pending | Python `_open_first_available_app`; Tauri should prefer `mailto:` |

---

## J. Reminders

| Feature | Status | Notes |
|---|---|---|
| `remind me to [task]` / `set a reminder to [task]` | 🔴 Python parity pending | Python osascript to Reminders app; Rust `open_url` could do `x-apple-reminderkit://` |
| Date/time extraction from reminder text | 🔴 Python parity pending | Python `_parse_reminder_datetime()`; complex regex; can defer for first pass |

---

## K. Screenshots / Shottr

| Feature | Status | Notes |
|---|---|---|
| `screenshot` / `take a screenshot` / `capture screen` | 🔴 Python parity pending | Python detects Shottr and runs matching shortcut |
| `capture window` / `window screenshot` | 🔴 Python parity pending | Same |
| `area capture` / `capture area` / `area screenshot` | 🔴 Python parity pending | Same |
| `scrolling capture` / `capture scrolling` | 🔴 Python parity pending | Same |
| `text recognition` / `extract text` / `recognize text` | 🔴 Python parity pending | Same |
| Graceful fallback if Shottr not installed | 🔴 Python parity pending | Python shows error message |

---

## L. Spotify / Music / Media

| Feature | Status | Notes |
|---|---|---|
| `play [song] on Spotify` | 🔴 Python parity pending | Python `spotify:search:` URI via `open_url`; Rust `open_url` exists |
| `play coding playlist` / `play workout playlist` | 🔴 Python parity pending | Python has hardcoded playlist URIs |
| `play playlist 4 / 5 / 6` | 🔴 Python parity pending | Same; configurable in Python's USER_CONFIG |
| `volume up` / `volume down` / `mute` / `unmute` | 🔴 Python parity pending | (see H above) |
| `set volume to [level]` | 🔴 Python parity pending | Same |

---

## M. Snippets

| Feature | Status | Notes |
|---|---|---|
| Snippets panel opens | ✅ Confirmed | SnippetsPage in Settings nav |
| Create snippet in UI | ✅ Confirmed | SnippetsPage new/save flow |
| Edit snippet in UI | ✅ Confirmed | SnippetsPage selection + edit |
| Delete snippet in UI | ✅ Confirmed | SnippetsPage delete button |
| Use snippet by dictating trigger phrase | ✅ Confirmed | `apply_snippets()` in sidecar runs on transcribed text |
| Snippets file `~/.dictation_snippets.json` | ✅ Confirmed | `data.rs` + sidecar use same path |
| Voice-created snippet flow (`create snippet` → prompt trigger → prompt content) | 🔴 Python parity pending | Python `snippet_state` machine; not ported to sidecar |
| Email normalization ("at" → `@`, "dot" → `.`) in snippet creation | 🔴 Python parity pending | Python applies during voice creation; Tauri UI doesn't normalize |

---

## N. Dictation History

| Feature | Status | Notes |
|---|---|---|
| History page opens | ✅ Confirmed | HistoryPage in nav |
| `show history` voice command | ✅ Confirmed | `navigate` → `nav-history` event |
| Stores final text | ✅ Confirmed | `final_text` in HistoryEntry |
| Stores status | ✅ Confirmed | `status` field |
| Stores profile | ✅ Confirmed | `profile` field |
| Stores active app name | 🟡 Partially working | `app` field exists in HistoryEntry struct; HistoryPage displays it; but the TS `save_history_entry` call never populates it — always blank |
| Stores timestamp | ✅ Confirmed | `timestamp` field |
| Stores Whisper text (pre-cleanup) | 🟡 Partially working | `whisper_text` field exists in struct; sidecar doesn't return it separately; HistoryPage doesn't display it |
| Stores Ollama text (what model suggested) | 🟡 Partially working | `ollama_text` field exists; not populated or displayed |
| Limit to 100 entries | ✅ Confirmed | `append_history` in `data.rs` trims to 100 |
| History file `~/.dictation_history.json` | ✅ Confirmed | `data.rs` path matches Python |
| Search/filter history | ✅ Confirmed | HistoryPage search input |

---

## O. Custom Commands

| Feature | Status | Notes |
|---|---|---|
| Create custom command | ✅ Confirmed | CustomCommandsPage |
| Delete custom command | ✅ Confirmed | Same |
| Open URL action | ✅ Confirmed | `open_url` Rust command |
| Open App action | ✅ Confirmed | `open_app` Rust command |
| Type Text action | ✅ Confirmed | `pasteText` return in `runCustomCommand` |
| Trigger phrase minimum two words | ✅ Confirmed | Length check in `runCustomCommand` |
| Custom commands run before built-in Jarvis commands | ✅ Confirmed | `runCustomCommand` is called before built-in command result is processed |
| File `~/.dictation_custom_commands.json` | ✅ Confirmed | `data.rs` path matches Python |
| Long text wraps in UI without horizontal overflow | 🟡 Partially working | CustomCommandsPage uses `break-words`; needs visual verification |

---

## P. Custom Vocabulary / Local Correction

| Feature | Status | Notes |
|---|---|---|
| Manual vocabulary text box | ✅ Confirmed | VocabularyPage |
| Save vocabulary | ✅ Confirmed | `save_vocab` Tauri command |
| Vocabulary used as Whisper initial_prompt | ✅ Confirmed | `get_personal_prompt()` in sidecar; commit `0e40125` |
| Auto-learning from dictation history | ✅ Confirmed | `_learn_from_history()` in sidecar; commit `0e40125` |
| Personal vocabulary corrections (SymSpell) | ✅ Confirmed | `_run_symspell()` in sidecar; commit `0e40125`; 45/45 tests |
| Correction Strength: Off / Light / Standard / Strong | ✅ Confirmed | Sidecar uses `correction_strength` to gate SymSpell aggressiveness |
| Correction works when Ollama is off | ✅ Confirmed | SymSpell runs before Ollama in pipeline |
| Developer guardrails (code terms, URLs, camelCase untouched) | ✅ Confirmed | Sidecar `DEVELOPER_GUARDRAIL_RE` patterns; commit `0e40125` |

---

## Q. Safe Mode

| Feature | Status | Notes |
|---|---|---|
| Safe Mode toggle | ✅ Confirmed | Tray CheckMenuItem + AiCleanupPage toggle + `safe_mode` setting |
| Disables Ollama cleanup | ✅ Confirmed | `safe_mode` check in sidecar |
| Disables Jarvis commands | ✅ Confirmed | `safe_mode` blocks voice command dispatch in `cmd_transcribe_last` |
| Disables context-aware formatting | ✅ Confirmed | `context_format` guarded independently; Safe Mode sets it off |
| Disables cloud transcription | 🟡 Partially working | Cloud transcription not yet implemented in sidecar; this is moot until Priority 8 |
| Shows safe-mode state (HUD / menu / settings) | ✅ Confirmed | Tray checkmark + HUD "Safe Mode On" notification |

---

## R. Wake Word

| Feature | Status | Notes |
|---|---|---|
| Wake toggle | ✅ Confirmed | JarvisPage toggle + tray CheckMenuItem; commit `96a7759` |
| Wake menu checkmark sync | ✅ Confirmed | `wake-menu-sync` event; commit `0e40125` |
| "Hey Jarvis" starts recording | ✅ Confirmed | `openwakeword` model; `wake-detected` event → `startRecording` |
| No freeze / beachball | ✅ Confirmed | Background thread; non-blocking sidecar init |
| CPU acceptable when idle | ✅ Confirmed | `start_wake_poll_thread` polls every 200 ms |
| Auto-stop waits until user actually speaks | ✅ Confirmed | `wake_dictation_grace_seconds` + VAD-based silence detection |
| No premature silence stop | ✅ Confirmed | Grace period prevents early cutoff |
| No spurious re-trigger | ✅ Confirmed | Wake paused during recording via `_wake_listening` flag in sidecar |
| Wake pauses during recording | ✅ Confirmed | Sidecar sets `_wake_listening = False` during recording |
| Wake resumes after recording | ✅ Confirmed | Sidecar restores `_wake_listening` after transcription |
| Wake off drops sidecar CPU near 0 | ✅ Confirmed | `stop_wake_listen` stops model inference thread |

---

## S. Cloud Transcription

| Feature | Status | Notes |
|---|---|---|
| Cloud mode toggle | 🟡 Partially working | `cloud_mode` setting + CloudPage UI; saved to settings but ignored by sidecar |
| OpenAI key storage in settings | 🟡 Partially working | `openai_key` setting stored in `~/.dictation_settings.json` (plain text) |
| Keychain preferred for API key | 🔴 Python parity pending | Python uses `keyring`; Tauri stores key in plain settings file |
| Cloud transcription request (sends audio to OpenAI) | 🔴 Python parity pending | Sidecar has no OpenAI API call; `cloud_mode` is read but ignored |
| Local fallback if cloud fails | 🔴 Python parity pending | Not implemented (cloud call itself not implemented) |
| Safe Mode disables cloud | 🟡 Partially working | Would work once cloud is implemented |
| Privacy wording accurate | ✅ Confirmed | CloudPage note is accurate |

---

## T. Settings / Menu / Permissions / App Identity

| Feature | Status | Notes |
|---|---|---|
| Menu bar app appears | ✅ Confirmed | `tray.rs` setup; tray icon visible |
| No Dock icon | ✅ Confirmed | `tauri.conf.json` `activation_policy = "Accessory"` |
| Settings opens / closes / reopens | ✅ Confirmed | Tray "Open Settings…" → show + focus "main" window |
| Tray Safe Mode checkmark sync | ✅ Confirmed | settings-changed event updates tray item state |
| Tray Wake Word checkmark sync | ✅ Confirmed | `wake-menu-sync` event |
| Tray Jarvis Commands checkmark sync | ✅ Confirmed | settings-changed event |
| Launch at Login | 🔴 Python parity pending | Tray item exists but is disabled with "(coming soon)" |
| About window / version info | 🟡 Partially working | Tray shows "About…" but links to generic Tauri default dialog |
| macOS Microphone permission instructions | ✅ Confirmed | SetupPage permission guidance |
| macOS Accessibility permission instructions | ✅ Confirmed | SetupPage + DictationPage inline prompt |
| macOS Input Monitoring permission | ✅ Confirmed | Implicitly required by CGEventTap; SetupPage mentions it |
| Automation permission (for Jarvis AppleScript commands) | 🔴 Python parity pending | Not yet needed; needed once Reminders/Email Jarvis commands land |
| App naming consistency | 🟡 Partially working | HUD window title is "Quill Tauri Preview HUD"; tray icon correct; no Dock name |
| All settings pages present | ✅ Confirmed | Setup, Dictation, Audio, AI Cleanup, Writing Profiles, Workflows, Jarvis, Custom Commands, Vocabulary, Cloud, Help, Snippets, History, Contacts |
| Help page | ✅ Confirmed | HelpPage exists |
| Copy setup summary (Help page button) | 🟡 Partially working | HelpPage exists; copy-summary button not yet implemented |
| Menu bar Whisper Model submenu | ✅ Confirmed | `tray.rs`; checkmark tracks current setting |
| Menu bar Record Key submenu | ✅ Confirmed | `tray.rs` |
| Menu bar Correction Strength submenu | ✅ Confirmed | `tray.rs` |
| Menu bar Writing Profile submenu | ✅ Confirmed | `tray.rs` |
| Menu bar History / Snippets nav | ✅ Confirmed | `tray.rs` |
| Ctrl+, shortcut to open settings | ❓ Needs user decision | Python supported it; not yet in Tauri |

---

## Summary counts

| Status | Count |
|---|---|
| ✅ Confirmed working | ~90 items |
| 🟡 Partially working | ~14 items |
| 🔴 Python parity pending | ~37 items |
| ⏸ Intentionally deferred | 0 |
| ❓ Needs user decision | 1 |

---

## Recently resolved (do not re-audit unless regression found)

| Feature | Resolution | Commit |
|---|---|---|
| Wake word backend | ✅ Confirmed working | `96a7759` |
| Wake word menu/tray state sync | ✅ Confirmed working | `0e40125` |
| Clipboard preservation after paste | ✅ Confirmed working | `0e40125` |
| Ollama skip-simple-cleanup | ✅ Confirmed working | `0e40125` |
| Local correction pipeline / SymSpell | ✅ Confirmed working, 45/45 tests | `0e40125` |
| Voice commands: scratch/undo/formatting/nav/punct/copy/history | ✅ Confirmed working, 60/60 tests | `90c1ac2` |
| stateRef stuck in transcribing (empty/custom-cmd early return) | ✅ Fixed | `d4e7eab` |

---

## Recommended next feature buckets (priority order)

### Priority 1 — Built-in Jarvis commands: open app / open URL / web search (Bucket H)

**Why first:** Largest single gap. Python's `_fast_jarvis_match` covers open-app, web-search, volume, email, reminders, screenshots, and Spotify. The Rust layer already has `open_url` and `open_app`. The missing piece is porting the pattern-detection logic into the sidecar's `_cmd_detect` so "open Safari", "search for cats", "play lo-fi on Spotify" route to the right action without requiring a user-defined custom command.

**Safe subset that needs zero new Rust commands:**
- `open [app name]` → existing `open_app`
- `open [website]` (YouTube, Netflix, GitHub, etc.) → existing `open_url`
- `search for [query]` / `google [query]` / `look up [query]` → existing `open_url` with DuckDuckGo
- `play [song] on Spotify` → existing `open_url` with `spotify:search:` URI

**Additional Rust commands needed for full parity:**
- `set_system_volume` (osascript — same pattern as `pause_media`) for volume up/down/mute/set
- `create_reminder` (osascript) for "remind me to…"
- `trigger_shottr` (detect `/Applications/Shottr.app` + call its URL scheme) for screenshots
- `close_app` / `kill_app` (osascript / killall) for close/kill

### Priority 2 — Volume / system control commands

**Why second:** Extremely high day-to-day value. trivial: one new Rust command wrapping the same osascript already used in `pause_media`. Volume up/down/mute/unmute/set-level all map to known osascript one-liners.

### Priority 3 — History: populate `app`, `whisper_text`, `ollama_text`

**Why third:** Low-risk data completeness. Three small changes:
1. Pass `get_last_target_app` result into the TS `save_history_entry` call.
2. Return `whisper_text` from the sidecar (the pre-pipeline Whisper result).
3. Return `ollama_text` from the sidecar (what Ollama suggested, before the safety filter).
4. Display them in HistoryPage (expandable detail row).

### Priority 4 — Reminders (`remind me to [task]`)

**Why fourth:** Deterministic, zero agentic risk. One Rust command with `osascript` wrapping the same AppleScript Python uses. Date/time parsing can be deferred; basic "remind me to call Jack" works without it.

### Priority 5 — Email commands (mailto: first)

**Why fifth:** Contacts UI already exists. Start with `mailto:` (works with any email client) and contacts name lookup from the Contacts store. Spark/Mail AppleScript can be added as a second pass.

### Priority 6 — Screenshots / Shottr integration

**Why sixth:** Detect Shottr at `/Applications/Shottr.app`. If present, trigger its URL schemes (e.g. `shottr://capture/screen`). If absent, fall back to macOS `screencapture` or show a HUD error message. Low-risk.

### Priority 7 — Launch at Login

**Why seventh:** UI placeholder already in tray ("coming soon"). Needs one Rust call to `SMLoginItem` API via Tauri's `tauri-plugin-autostart` or direct `launchctl` command.

### Priority 8 — Cloud transcription (sidecar OpenAI API call)

**Why eighth:** UI and settings already exist. Sidecar needs an `openai.Audio.transcriptions.create` HTTP call with local faster-whisper as fallback. Move API key to Keychain (`keyring` Python module).

### Defer for now

- `undo dictation` / `redo dictation` stack (requires stateful undo buffer beyond current scratch history)
- Voice-created snippet flow (`create snippet` spoken prompt)
- `new line` smart Shift+Enter in chat apps (app detection already works; one extra case in `_cmd_detect`)
- Helpful HUD tips / startup tips mode
- Ctrl+, settings shortcut (needs user decision)
- Whisper hallucination deduplication (rare edge case)
- App naming / full rename (user decision, separate from parity work)
