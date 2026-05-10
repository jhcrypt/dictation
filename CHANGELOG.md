# Changelog

## v6.1.10 — Hotkey UI Cleanup
- Simplified supported record keys to Right Option, F13, F14, F15.
- Kept Right Option as the recommended default.
- Removed confusing left-side and Command/Control hotkey options from the UI.
- Hotkey recovery added — app continues if preferred key is unavailable.

## v6.1 — Writing Profiles
- Added writing profiles: General, Professional, Email, Developer, Medical, Legal, Sales, Notes, Creative, and Verbatim.
- Added app-based profile detection (auto-switches profile based on frontmost app).
- Added menu bar and Settings profile selection.
- Jarvis long dictation improved — silence detection stops recording cleanly.

## v6.0 — Mac Menu Bar Professional
- Added macOS menu bar controller.
- Added packaging kit for building a `.app` bundle.
- Professional Settings/About window polish.
- Removed microphone test feature (caused repeated crashes).

## v5.9 — Safety + History
- Added Ollama safety protections.
- Added short-phrase bypass (skips AI cleanup for very short transcriptions).
- Added richer dictation history metadata.
- Professional window and button refinements.

## v5.8 — Stability Polish
- Fixed Option-key crash by using a safe queue between Quartz and Tkinter.
- Added recording debounce and minimum recording duration guards.
- Prevented overlapping transcription jobs.
- Standardized terminal log output.
- Made start/stop sounds settings-aware.

## v5.7 — Core Foundations
- Local Whisper transcription (tiny.en, base.en, small.en).
- Optional OpenAI cloud transcription.
- Ollama local AI cleanup.
- Jarvis wake-word detection.
- Snippets manager.
- Dictation history.
- Right Option push-to-dictate.
- macOS menu bar integration.
