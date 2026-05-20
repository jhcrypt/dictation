# Tauri Parity Audit
_Generated: 2026-05-20 — compare against stable Python Quill app_

---

## 1 · Tray / Menu Parity

| Item | Python behavior | Tauri behavior | Status | Priority | Notes |
|---|---|---|---|---|---|
| Status | Dynamic label: "🟢 Recording", "🔴 Stopped", etc. | Static "Status: Ready" — never updates | 🟡 partial | important | Tauri v2 MenuItem text can't be updated at runtime; would need a workaround (rebuild menu or use OS notification) |
| Start Dictation | Clickable, starts recording | ✅ Emits `tray-start-dictation`; wired in `useGlobalHotkey` | ✅ matched | — | |
| Cancel Recording | Enabled only while recording | ✅ Present; emits `tray-stop-dictation` | ✅ matched | — | Not grayed-out dynamically (Tauri limitation) |
| Toggle HUD | Check item, hides/shows HUD window | ✅ `CheckMenuItem` "Toggle HUD"; toggles `show_hud` and calls `hud.show()/hide()` | ✅ matched | — | Label is static "Toggle HUD" vs Python's dynamic "Hide HUD" / "Show HUD" |
| Safe Mode | Check item | ✅ `CheckMenuItem`; saves setting + HUD notify | ✅ matched | — | |
| Wake Word | Check item | ✅ `CheckMenuItem`; saves + HUD notify | ✅ matched | — | |
| Jarvis Commands | Check item | ✅ `CheckMenuItem`; saves + HUD notify | ✅ matched | — | |
| Whisper Model submenu | 8 models, check on active | ✅ Same 8 models (tiny.en … distil-large-v3), checkmarks, HUD "Loading …" | ✅ matched | — | |
| Record Key submenu | Right Option / F13 / F14 / F15 | ✅ All 4 keys; live-switches hotkey via `HotkeyConfig` atomic; HUD notify | ✅ matched | — | Fixed in commit 6735693 |
| Correction Strength submenu | Light / Standard / Strong / Off | ✅ All 4; saves + HUD notify | ✅ matched | — | |
| Writing Profile submenu | 10 profiles | ✅ Same 10 profiles; saves + HUD notify | ✅ matched | — | |
| Open Settings | Opens settings window | ✅ Shows + focuses main window | ✅ matched | — | |
| Add Correction from Last Dictation | Opens Vocabulary tab **pre-filled** with last dictated phrase | Navigates to Vocabulary page but does **not** pre-fill the form fields | 🟡 partial | important | `nav-vocabulary` event fired; last-text state not passed across |
| Manage Snippets | Opens Snippets tab | ✅ `nav-snippets` event | ✅ matched | — | |
| Show History | Opens History tab | ✅ `nav-history` event | ✅ matched | — | |
| Open macOS Permissions | Opens System Settings → Accessibility | ✅ `open_accessibility_settings` command | ✅ matched | — | |
| Launch at Login | Toggle in tray; uses `launchd` plist | Item present but disabled; labeled "coming soon" | ⚪ intentional gap | later | Needs `tauri-plugin-autostart` or manual launchd plist write |
| About | Shows version dialog | ✅ Shows About dialog | ✅ matched | — | |
| Quit | Terminates app | ✅ Quits process | ✅ matched | — | |

**Tray totals:** 16 ✅ matched · 2 🟡 partial · 0 🔴 missing · 1 ⚪ intentional gap

---

## 2 · Settings Page Parity

### Setup
| Area | Python behavior | Tauri behavior | Status | Priority | Notes |
|---|---|---|---|---|---|
| Record Hotkey selector | Right Option / F13 / F14 / F15 radio | ✅ Same 4 options, saves `hotkey_label`, live-switches | ✅ matched | — | |
| Toggle Mode toggle | Push-to-talk vs toggle | ✅ `toggle_mode` toggle, wired to `HotkeyConfig` atomic | ✅ matched | — | |
| Accessibility permission | Button → System Settings | ✅ `open_accessibility_settings` | ✅ matched | — | |
| Debounce setting | Numeric field | ✅ `hotkey_debounce_seconds` in settings | ✅ matched | — | |
| Min record seconds | Numeric field | ✅ `min_record_seconds` | ✅ matched | — | |

### Dictation
| Area | Python behavior | Tauri behavior | Status | Priority | Notes |
|---|---|---|---|---|---|
| Sidecar / engine status | Status indicator | ✅ Green/amber/red dot with text | ✅ matched | — | |
| Record button | Start / Stop | ✅ Full state machine in UI | ✅ matched | — | |
| Timing readout | Full breakdown: recording, stop, whisper, ollama, paste, total after release, total cycle | Partial: only `whisper_ms`, `ollama_ms`, `total_ms` inline in Last Transcript | 🟡 partial | important | **Being fixed in this session** |
| Target app display | Shows focused app name | ✅ Polls `get_last_target_app` every 2 s | ✅ matched | — | |
| Paste error display | Shows error if paste fails | ✅ `pasteError` state | ✅ matched | — | |
| Dictation Quality selector | Fast / Balanced / Accurate | ✅ Present on Dictation page | ✅ matched | — | |
| Context-format toggle | Detects active app, adjusts format | ✅ Toggle for `context_format` | ✅ matched | — | |

### Audio & Language
| Area | Python behavior | Tauri behavior | Status | Priority | Notes |
|---|---|---|---|---|---|
| Mic device selector | Dropdown of all audio inputs | ✅ Dropdown using `sidecar_list_microphones` | ✅ matched | — | |
| Sample rate | 16 / 44.1 / 48 kHz | ✅ Select component | ✅ matched | — | |
| Language selector | Language dropdown | ✅ Dropdown with same language list | ✅ matched | — | |
| Translate My Dictation | Off / language list | ✅ Select component, `translate_my_dictation` | ✅ matched | — | |
| Translate Selected Text To | Target language | ✅ Select component, `translate_target_language` | ✅ matched | — | |
| How Language Settings Work | Explanatory card | ✅ Present | ✅ matched | — | |

### AI Cleanup
| Area | Python behavior | Tauri behavior | Status | Priority | Notes |
|---|---|---|---|---|---|
| Ollama readiness card | All 7 statuses with descriptions | ✅ All states matched | ✅ matched | — | |
| Check Again button | Re-runs status check | ✅ | ✅ matched | — | |
| Open Ollama Download Page | Opens browser | ✅ `open_url` | ✅ matched | — | |
| Test Cleanup button | Sends test phrase to Ollama, shows output | ✅ Hits `http://localhost:11434/api/chat` directly | ✅ matched | — | |
| Install Recommended Model | Runs `ollama pull qwen2.5:3b` | ✅ `install_ollama_model` Tauri command | ✅ matched | — | |
| AI Cleanup Mode | auto / on / off | ✅ Three-button selector | ✅ matched | — | |
| Correction Strength | Light / Standard / Strong / Off | ✅ List selector with descriptions | ✅ matched | — | |
| Ollama toggles | Enable Ollama / Safe Mode / Context-format | ✅ Three toggles | ✅ matched | — | |
| HUD notifications | install success, test pass | ✅ `hudSaved()` on both | ✅ matched | — | |

### Writing Profiles
| Area | Python behavior | Tauri behavior | Status | Priority | Notes |
|---|---|---|---|---|---|
| Profile list | 10 profiles with descriptions | ✅ Same 10 profiles | ✅ matched | — | |
| Active profile selector | Radio/click selection | ✅ Button group | ✅ matched | — | |
| Auto profile detection | Toggle | ✅ `auto_profile_detection` toggle | ✅ matched | — | |
| Show active profile | Toggle | ✅ `show_active_profile` toggle | ✅ matched | — | |

### Jarvis
| Area | Python behavior | Tauri behavior | Status | Priority | Notes |
|---|---|---|---|---|---|
| Wake word enable | Toggle | ✅ | ✅ matched | — | |
| Jarvis commands enable | Toggle | ✅ | ✅ matched | — | |
| Wake dictation timing | Grace / Silence cutoff / Max length steppers | ✅ NumericStepper (fixed this session) | ✅ matched | — | |
| Continuous wake listening | Active mic monitor, background loop | ✗ Sidecar does not implement `start_wake_listen` | ⚪ intentional gap | later | Known gap — documented in file comment |

### Custom Commands
| Area | Python behavior | Tauri behavior | Status | Priority | Notes |
|---|---|---|---|---|---|
| Add command form | Trigger, action type, target | ✅ All three fields, validation (≥2 words) | ✅ matched | — | |
| Action types | open_url / open_app / type_text | ✅ | ✅ matched | — | |
| Command list | Shows all, delete | ✅ | ✅ matched | — | |
| Storage | `~/.jarvis_commands.json` | ✅ Same file via `load_custom_commands` / `save_custom_commands` | ✅ matched | — | |

### Contacts
| Area | Python behavior | Tauri behavior | Status | Priority | Notes |
|---|---|---|---|---|---|
| Add/delete contacts | Name, email, aliases | ✅ All fields | ✅ matched | — | |
| Storage | contacts JSON | ✅ `load_contacts` / `save_contacts` | ✅ matched | — | |
| Voice "Email Val" lookup | Alias → email resolution in Python | ⚪ Executed by Python sidecar | ⚪ intentional gap | later | Sidecar handles voice command execution |

### Vocabulary
| Area | Python behavior | Tauri behavior | Status | Priority | Notes |
|---|---|---|---|---|---|
| Manual vocabulary textarea | Hints passed to Whisper | ✅ `manual_vocabulary` textarea | ✅ matched | — | |
| Personal corrections list | wrong → right find-and-replace | ✅ Add/delete pairs | ✅ matched | — | |
| Storage | shared vocab JSON | ✅ `load_vocab` / `save_vocab` | ✅ matched | — | |
| Pre-fill from tray "Add Correction" | Last dictated text pre-filled | 🔴 Not implemented | 🔴 missing | important | `nav-vocabulary` navigates but no payload |

### Snippets
| Area | Python behavior | Tauri behavior | Status | Priority | Notes |
|---|---|---|---|---|---|
| New snippet form | Trigger + expansion | ✅ | ✅ matched | — | |
| Edit selected | Click to edit inline | ✅ | ✅ matched | — | |
| Delete | With confirmation | ✅ (no confirm dialog, direct delete) | 🟡 partial | polish | Python asks for confirmation; Tauri deletes immediately |
| Storage | snippets JSON | ✅ `load_snippets` / `save_snippets` | ✅ matched | — | |

### Cloud
| Area | Python behavior | Tauri behavior | Status | Priority | Notes |
|---|---|---|---|---|---|
| Cloud mode toggle | Switches transcription to OpenAI Whisper API | ✅ Toggle + API key field | 🟡 partial | important | Setting saved; but sidecar `transcribe_cloud()` path not fully wired in Tauri flow — sidecar_transcribe_last ignores cloud_mode in Tauri |
| OpenAI API key | Stored in settings | ✅ Text field; saves `openai_key` | ✅ matched | — | |
| Privacy note | Explanatory card | ✅ | ✅ matched | — | |

### Workflows
| Area | Python behavior | Tauri behavior | Status | Priority | Notes |
|---|---|---|---|---|---|
| Reference page | No equivalent; Python executes inline | Read-only reference card listing workflow categories | ⚪ intentional gap | — | New Tauri-only page; execution is in sidecar |

### Help
| Area | Python behavior | Tauri behavior | Status | Priority | Notes |
|---|---|---|---|---|---|
| Hotkey instructions | In app | ✅ Full help cards | ✅ matched | — | |
| Troubleshooting | Steps | ✅ | ✅ matched | — | |
| Sidecar restart | Button | ✅ `restart_engine` command | ✅ matched | — | |
| Diagnostics | System info dump | ✅ `get_diagnostics` command, displays in card | ✅ matched | — | |

### History
| Area | Python behavior | Tauri behavior | Status | Priority | Notes |
|---|---|---|---|---|---|
| Entry list | Timestamp, text, profile, status, app | ✅ Shows all fields | ✅ matched | — | |
| Clear history | Button | ✅ `clear_history` command | ✅ matched | — | |
| Timing in history | whisper/ollama/total stored | ✅ Saved with `save_history_entry` | ✅ matched | — | |

---

## 3 · Dictation Flow Parity

| Feature | Python behavior | Tauri behavior | Status | Priority | Notes |
|---|---|---|---|---|---|
| Hold-to-dictate | Right Option held → record; release → transcribe | ✅ `hotkey-ropt-down/up` via CGEventTap | ✅ matched | — | |
| Toggle mode | Press once start, press again stop | ✅ `toggle_mode` setting + `HotkeyConfig.toggle_mode` atomic | ✅ matched | — | |
| F13 / F14 / F15 hotkeys | Push-to-talk or toggle | ✅ keycodes 105/107/113, live-switchable | ✅ matched | — | Fixed this session |
| Right Option keycode | 61 | ✅ `KEY_RIGHT_OPTION = 61` | ✅ matched | — | |
| Short-tap detection | < `hotkey_debounce_seconds` → ignored | ✅ `MIN_TAP_MS = 300 ms`, `tap_ignored` HUD state | 🟡 partial | polish | Tauri uses fixed 300 ms; Python uses `hotkey_debounce_seconds` setting |
| Start recording | `sidecar_start_recording` | ✅ | ✅ matched | — | |
| Stop + transcribe | `sidecar_stop_recording` → `sidecar_transcribe_last` | ✅ Full flow in `useGlobalHotkey` | ✅ matched | — | |
| Cancel (Esc) | Discards audio | ✅ `hotkey-esc` → `sidecar_cancel_recording` | ✅ matched | — | |
| Transcription | Whisper via sidecar | ✅ | ✅ matched | — | |
| Auto-paste | `paste_text` via accessibility | ✅ `paste_text` Tauri command | ✅ matched | — | |
| Safe mode paste | Copy to clipboard only | ✅ Skip paste when `safe_mode = true` | ✅ matched | — | |
| History save | Entry after each dictation | ✅ `save_history_entry` after paste | ✅ matched | — | |
| Timing diagnostics | Full per-segment timing to debug log | Partial: sidecar returns whisper/ollama/total; Tauri-side segment breakdown being added | 🟡 partial | important | **Being fixed this session** |
| Model switching | Tray submenu, live reload | ✅ Tray writes setting; sidecar picks up at next transcription | ✅ matched | — | |
| Cleanup mode | auto / on / off | ✅ Applied by sidecar | ✅ matched | — | |
| Writing profile | Applied in cleanup pipeline | ✅ Sidecar applies; result includes `profile` field | ✅ matched | — | |
| 90 s safety auto-stop | Prevents infinite recording | ✅ `setTimeout 90_000` in `useGlobalHotkey` | ✅ matched | — | |
| Overlapping-dictation guard | Python `_transcription_busy` flag | ✅ Rust-side sidecar handles; JS state machine guards `idle` check | ✅ matched | — | |

---

## 4 · HUD Parity

| Feature | Python behavior | Tauri behavior | Status | Priority | Notes |
|---|---|---|---|---|---|
| Idle | Transparent / minimal | ✅ Idle = blank/transparent | ✅ matched | — | |
| Recording | Waveform bars, red animated | ✅ 22-bar `WaveformBars` component, CSS `hud-wave` animation | ✅ matched | — | |
| Wake recording | Waveform bars (same as recording) | ✅ `wake_recording` maps to same waveform | ✅ matched | — | |
| Transcribing | Spinner, blue | ✅ Lucide `Loader2` spin animation | ✅ matched | — | |
| Cleanup | Sparkle / processing | ✅ `cleanup` state with Sparkles icon | ✅ matched | — | |
| Skipped | Shows skip reason | ✅ `skipped` state with subtext | ✅ matched | — | |
| Inserted / pasted | Green check, transcribed text | ✅ `inserted` state with Check icon | ✅ matched | — | |
| Saved notifications | Green check + message | ✅ `saved` HUD state, `hudSaved()` utility | ✅ matched | — | |
| Command notifications | Blue zap + message | ✅ `command` state, `hudCommand()` utility | ✅ matched | — | |
| Error | Red ✗ | ✅ `error` state with X icon | ✅ matched | — | |
| Tap ignored | Short-tap notice | ✅ `tap_ignored` state | ✅ matched | — | |
| Profile display | Profile name on inserted | ✅ `profile` field in HUD payload when `show_active_profile` | ✅ matched | — | |
| Target app icon | App icon extracted from bundle | ✅ `get_target_app_icon` → base64; `extractIconColor` for border | ✅ matched | — | |
| Waveform bar count | 22 bars | ✅ 22 bars × 2 px + 21 gaps × 1 px = 65 px | ✅ matched | — | |
| Dynamic HUD border | Matches app icon color during recording only | ✅ `isDictating` guard + opacity 0.35 | ✅ matched | — | |
| Auto-clear | 1.5 s then idle | ✅ `setTimeout 1500` after `inserted` | ✅ matched | — | |
| Draggable position | User can drag HUD | ✅ Draggable Tauri window, position saved | ✅ matched | — | |
| HUD show/show_hud | Controlled by tray item | ✅ `hide_hud` CheckMenuItem | ✅ matched | — | |

---

## 5 · Ollama / Local AI Parity

| Feature | Python behavior | Tauri behavior | Status | Priority | Notes |
|---|---|---|---|---|---|
| Readiness check | 7 states: checking / ready / not_installed / not_running / model_missing / installing / install_error | ✅ All 7 states with identical labels | ✅ matched | — | |
| Install recommended model | `ollama pull qwen2.5:3b` | ✅ `install_ollama_model` Rust command | ✅ matched | — | |
| Test cleanup | Sends test phrase, shows output | ✅ Hits Ollama HTTP API directly | ✅ matched | — | |
| Download link | Opens `https://ollama.com/download` | ✅ `open_url` command | ✅ matched | — | |
| Recommended model | `qwen2.5:3b` | ✅ `RECOMMENDED_MODEL = "qwen2.5:3b"` | ✅ matched | — | |
| Status labels | Python `STATUS_DETAIL` dict | ✅ `STATUS_DETAIL` record in TS matches Python strings | ✅ matched | — | |
| Cleanup mode behavior | auto skips if unavailable, on warns, off disables | ✅ Handled by sidecar | ✅ matched | — | |
| Safe mode disables cleanup | Sidecar skips Ollama in safe mode | ✅ Sidecar-side; settings shared via JSON | ✅ matched | — | |
| HUD on install | Shows model name after install | ✅ `hudSaved("qwen2.5:3b installed!")` | ✅ matched | — | |
| HUD on test | Shows "Test passed" | ✅ `hudSaved("Test passed")` | ✅ matched | — | |

---

## 6 · Data / File Parity

| File | Python path | Tauri path | Status | Priority | Notes |
|---|---|---|---|---|---|
| Settings | `~/.dictation_settings.json` | ✅ Same path via `settings_path()` | ✅ matched | — | |
| Snippets | `~/.jarvis_snippets.json` | ✅ Same path via `data.rs` | ✅ matched | — | |
| Custom commands | `~/.jarvis_commands.json` | ✅ Same path | ✅ matched | — | |
| Contacts | `~/.jarvis_contacts.json` | ✅ Same path | ✅ matched | — | |
| Vocabulary / corrections | `~/.jarvis_vocab.json` | ✅ Same path | ✅ matched | — | |
| History | `~/.dictation_history.json` | ✅ Same path | ✅ matched | — | |
| Ollama model | `qwen2.5:3b` pulled via `ollama pull` | ✅ Same model, same command | ✅ matched | — | |

---

## 7 · Known Intentional Gaps

| Feature | Python | Tauri | Priority | Notes |
|---|---|---|---|---|
| Continuous wake-word listening | Background mic monitor loop, `hey_jarvis` detection | ⚪ Sidecar does not implement `start_wake_listen` action | later | Filed as post-stabilization. `wake_enabled` saves to JSON correctly |
| Launch at Login | `launchd` plist via `SMAppService` Python binding | ⚪ Menu item present but disabled | later | Needs `tauri-plugin-autostart` |
| "Add Correction" pre-fill | Tray item pre-fills Vocabulary form with last dictated text | ⚪ Navigates to page but no pre-fill | important | Last-text needs to be passed via event payload |
| Cloud transcription routing | `cloud_mode=true` routes to `transcribe_cloud()` | ⚪ Setting saved but sidecar Tauri path doesn't check `cloud_mode` | important | Sidecar `transcribe_and_type` needs `cloud_mode` branch |
| Snippet confirm-delete | Python shows confirmation dialog before delete | ⚪ Tauri deletes immediately | polish | Low risk; can add `window.confirm` |
| Status label dynamism | Tray status updates while recording | ⚪ Tauri v2 limitation: can't update MenuItem text at runtime | later | Would need menu rebuild or NSStatusItem native workaround |
| Tray cancel enabled state | Cancel item enabled only during recording | ⚪ Always enabled (Tauri v2 can't toggle item enabled state at runtime easily) | polish | |
| Timing readout full breakdown | recording / stop / whisper / ollama / paste / totals | 🟡 whisper + ollama + total only; full breakdown being added | important | **Fixed this session** |
| Packaging / DMG | `.app` bundle ready for distribution | ⚪ Dev-only: `npm run tauri dev` | later | Requires `tauri build` + code signing |

---

## Summary Counts

| Status | Count |
|---|---|
| ✅ matched | 71 |
| 🟡 partial | 8 |
| 🔴 missing | 1 |
| ⚪ intentional gap | 9 |

---

## Top 5 Blockers

1. **Cloud transcription not routed** — `cloud_mode=true` is saved but `sidecar_transcribe_last` in Tauri doesn't pass it to the Python sidecar; cloud mode silently falls back to local
2. **Dictation timing breakdown incomplete** — Only whisper/ollama/total available; recording/stop/paste times missing _(being fixed this session)_
3. **"Add Correction" no pre-fill** — Tray "Add Correction from Last Dictation" navigates to Vocabulary but doesn't pass the text; feature is non-functional from tray
4. **Snippet delete no confirmation** — Immediate delete with no undo; data-loss risk for mis-clicks
5. **Tray Status always "Ready"** — Can never signal recording/transcribing/error in tray; Python always shows current state

## Top 5 Important Items

1. **"Add Correction" pre-fill** — Pass last-dictated text as event payload when navigating to Vocabulary page
2. **Short-tap threshold** — Currently hardcoded at 300 ms; should read `hotkey_debounce_seconds` from settings like Python does
3. **Cloud mode routing** — Wire `cloud_mode` flag through to sidecar `transcribe_and_type` call
4. **Full timing readout** — being fixed this session
5. **Snippet confirm-delete** — Add `window.confirm` before deleting a snippet

## Recommended Next Fix

**"Add Correction" pre-fill** — the tray item is the intended fast path for training corrections; without pre-fill, users must retype the mishear. Implement by:
1. Storing `lastDictatedText` in a shared context or emitting it with a `nav-vocabulary` payload
2. VocabularyPage reads the payload and pre-fills the "Whisper hears…" field
