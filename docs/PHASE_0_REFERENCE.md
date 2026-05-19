# Jarvis Dictation — Phase 0 Reference

Frozen: 2026-05-16  
Source: `/Users/user1/dictation/src/jarvis_dictation.py`  
Git tag: `phase0-reference-freeze` (commit `869eba8`)  
Version: v6.1.18 / v6.3.0 (stabilize branch)  
Reference copy: `../reference/jarvis_dictation_v6.1.18_reference.py`

---

## Features Inventory

### 1. Dictation (core)
- Hold **Right Option** (or F13/F14/F15) to record; release to transcribe and paste
- Toggle mode: tap to start, tap to stop
- Offline transcription via **faster-whisper** (local Whisper models)
- Optional **OpenAI cloud** transcription (`cloud_mode`)
- Silence detection with configurable thresholds
- Minimum recording duration guard (`min_record_seconds`)
- Hotkey debounce (`hotkey_debounce_seconds`)
- Safe mode (no paste — copies to clipboard only)

### 2. Hotkey
- Configurable: Right Option | F13 | F14 | F15
- Implemented via macOS Quartz event tap (suppression tap)
- Keyboard listener managed by pynput + Quartz fallback
- Restart listener on settings window open/close

### 3. Wake Word ("Hey Jarvis" / "Hey Val")
- OpenWakeWord ONNX model (`hey_jarvis`)
- Configurable grace, silence, max duration, silence RMS thresholds
- Can be enabled/disabled via settings
- Escape cancels active wake-word dictation

### 4. Paste
- Posts transcribed text to frontmost app via **Cmd+V**
- Clipboard content saved and restored after paste
- Clipboard verified before paste attempt
- `safe_mode` copies to clipboard only (no auto-paste)

### 5. Ollama AI Cleanup
- Local Ollama model (`llama3.2` by default) refines raw Whisper text
- Three modes: `auto` | `on` | `off`
- Auto mode skips cleanup for short phrases, commands, questions, repetitive text
- Correction strength: Minimal | Standard | Strong
- Async worker queue — non-blocking
- Status detection and model pull support

### 6. Translation
- **Translate My Dictation To**: translates output of every dictation
- **Translate Selected Text To**: triggered by voice command on clipboard selection
- Separate settings: `translate_my_dictation` vs `translate_target_language`
- Supported languages: English, French, Spanish, German, Italian, Portuguese

### 7. Writing Profiles
- Profiles: General | Professional | Casual | Technical | Email | Creative
- Auto-detection by frontmost app name
- Manual override per session
- Affects Ollama prompt style and formatting

### 8. Email Drafts
- Voice command: "email [contact name]" / "send email to [name]"
- Opens Spark Desktop → Spark → Mail → Outlook (first available)
- AppleScript-based composition
- Contact lookup from `~/.dictation_contacts.json`

### 9. Reminders
- Voice command: "remind me to [task]"
- Creates reminder via AppleScript in Reminders.app

### 10. Contacts
- Stored in `~/.dictation_contacts.json`
- Fields: name, email, aliases
- UI page for add/delete
- Used for email draft target resolution

### 11. Corrections (Personal Vocabulary)
- Wrong→right word pairs stored in settings JSON (`corrections` key) / applied at transcription time
- `apply_corrections(text)` runs find-and-replace
- UI page: add, list, delete corrections

### 12. Custom Commands
- Stored in `~/.dictation_custom_commands.json`
- Actions: `open_url` | `open_app` | `type_text`
- Trigger phrase matched in transcribed text
- UI page: add, list, delete

### 13. Snippets
- Stored in `~/.dictation_snippets.json`
- Trigger → expansion text
- Applied after transcription via `apply_snippets(text)`
- In-memory cache invalidated on save

### 14. Vocabulary / Word Learning
- Stored in `~/.dictation_vocabulary.json`
- Word frequency counts learned from dictation
- Manual vocabulary list (newline-separated) in settings
- Used as Whisper `initial_prompt`

### 15. History
- Stored in `~/.dictation_history.json`
- Per-entry: raw whisper text, ollama text, final text, app, status, profile, timestamp
- Cleared via settings UI

### 16. Dictation Quality / Model Selection
- Quality presets: Fast | Balanced | Accurate
  - Fast → `tiny.en` / `tiny`
  - Balanced → `small.en` / `small`
  - Accurate → `medium.en` / `medium`
- Advanced model override: free-text model name field
- Language-aware: English-only models (`.en`) auto-blocked when non-English selected
- Distil-Whisper models skip `initial_prompt`

### 17. Settings UI
- Pages: Setup | Dictation | Audio & Language | AI Cleanup | Writing Profiles | Jarvis | Custom Commands | Contacts | Vocabulary | Cloud | Help/Storage
- Sidebar navigation
- Dark-themed rounded UI (Tkinter Canvas-based custom widgets)
- Draggable window (no native title bar)

### 18. Menu Bar
- macOS NSStatusBar icon (PyObjC)
- States: idle (white) | recording (red) | transcribing (yellow)
- Menu items: Start/Stop | Toggle HUD | Toggle Safe Mode | Toggle Wake | Toggle Jarvis | Launch at Login | Settings | Snippets | History | About | Permissions | Model | Hotkey | Correction Strength | Writing Profile | Quit

### 19. HUD (Heads-Up Display)
- Floating transparent overlay window
- Shows: app icon, state label, transcript preview, marquee animation
- Wave animation during recording
- Draggable, repositionable

### 20. Native Commands (Jarvis intents)
- `open_url` — open URL in browser
- `open_app` — launch app by name
- `open_file` / `open_folder` — Finder open
- `type_text` — paste arbitrary text
- `set_volume` / `set_brightness` — AppleScript system control
- `restart_app` — relaunch Jarvis
- Translation of selected clipboard text
- Email drafting
- Reminder creation

### 21. Startup / Crash Logging
- Writes `~/jarvis_startup_debug.log` before any imports
- Log rotation at 100 KB
- Uncaught exception hook

### 22. OpenAI Key (Keychain)
- Stored in macOS Keychain (falls back to settings JSON)
- Set/get via `_keychain_get` / `_keychain_set`

---

## Settings Keys (`~/.dictation_settings.json`)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `model` | string | `"small.en"` | Whisper model name |
| `mic_device` | int | `2` | Microphone device index |
| `sample_rate` | int | `48000` | Audio sample rate |
| `hotkey_label` | string | `"Right Option"` | Recording hotkey (`"Right Option"` \| `"F13"` \| `"F14"` \| `"F15"`) |
| `show_hud` | bool | `true` | Show floating HUD overlay |
| `toggle_mode` | bool | `true` | Tap-to-toggle instead of hold |
| `cloud_mode` | bool | `false` | Use OpenAI instead of local Whisper |
| `openai_key` | string | `""` | OpenAI API key (also stored in Keychain) |
| `context_format` | bool | `true` | Apply context-aware formatting |
| `auto_detect` | bool | `true` | Auto-detect spoken language |
| `jarvis_enabled` | bool | `true` | Enable Jarvis intent detection |
| `use_ollama` | bool | `true` | Enable Ollama AI cleanup |
| `play_sounds` | bool | `true` | Play audio feedback sounds |
| `show_startup_tips` | bool | `true` | Show startup tips |
| `first_run_complete` | bool | `false` | First-run onboarding done |
| `onboarding_shown_version` | string | `""` | Version string of last shown onboarding |
| `min_record_seconds` | float | `0.3` | Minimum recording length before processing |
| `hotkey_debounce_seconds` | float | `0.18` | Debounce window for hotkey presses |
| `safe_mode` | bool | `false` | Copy-only mode (no auto-paste) |
| `ai_cleanup_mode` | string | `"auto"` | Ollama mode: `"auto"` \| `"on"` \| `"off"` |
| `correction_strength` | string | `"Standard"` | Ollama prompt strength: `"Minimal"` \| `"Standard"` \| `"Strong"` |
| `writing_profile` | string | `"General"` | Active writing profile |
| `auto_profile_detection` | bool | `true` | Auto-detect profile from frontmost app |
| `show_active_profile` | bool | `true` | Show active profile in HUD |
| `wake_dictation_grace_seconds` | float | `2.0` | Post-wake-word silence grace |
| `wake_dictation_silence_seconds` | float | `2.0` | Silence to end wake dictation |
| `wake_dictation_max_seconds` | float | `45.0` | Max wake dictation duration |
| `wake_dictation_silence_rms` | float | `0.025` | RMS threshold for silence detection |
| `translate_my_dictation` | string | `"Off"` | Dictation output translation target (`"Off"` or language) |
| `dictation_quality` | string | `"Balanced"` | Quality preset: `"Fast"` \| `"Balanced"` \| `"Accurate"` |
| `debug_logging` | bool | `false` | Enable verbose debug logging |
| `language` | string | `"en"` | Input language code (e.g. `"en"`, `"fr"`) |
| `translate_target_language` | string | `"English"` | Target for selected-text translation commands |
| `manual_vocabulary` | string | `""` | Newline-separated custom vocabulary words |
| `hud_x` | int | `606` | HUD window X position |
| `hud_y` | int | `0` | HUD window Y position |
| `wake_enabled` | bool | `false` | Enable Hey Jarvis wake word |
| `assistant_name` | string | `"Val"` | Assistant name used in prompts |

---

## Data Files

| File | Format | Purpose |
|------|--------|---------|
| `~/.dictation_settings.json` | JSON object | All app settings |
| `~/.dictation_contacts.json` | JSON array of `{name, email, aliases}` | Email contacts |
| `~/.dictation_custom_commands.json` | JSON array of `{trigger, action, target}` | Voice-triggered commands |
| `~/.dictation_snippets.json` | JSON object `{trigger: expansion}` | Text expansion snippets |
| `~/.dictation_vocabulary.json` | JSON object `{word_counts: {...}}` | Learned word frequencies |
| `~/.dictation_history.json` | JSON array of history entries | Dictation history log |

---

## Python Dependencies (key)

| Package | Purpose |
|---------|---------|
| `faster-whisper` | Local speech-to-text |
| `pyaudio` | Audio capture |
| `pynput` | Keyboard listener |
| `pyobjc` | macOS menu bar, AppleScript |
| `tkinter` | UI framework |
| `openwakeword` | Hey Jarvis wake word detection |
| `symspellpy` | Spell correction |
| `ollama` | Local LLM AI cleanup |

---

## What the Tauri Migration Must NOT Break

- `~/.dictation_settings.json` — must remain readable by the Python engine during transition
- `~/.dictation_contacts.json`, `~/.dictation_history.json`, `~/.dictation_vocabulary.json` — same
- Right Option hotkey behavior
- Paste reliability (clipboard save/restore)
- Ollama cleanup chain
