# Changelog

## v6.2.4 — Distil Model Fix

### Fix: distil-whisper models now transcribe correctly
- `distil-medium.en` and `distil-large-v3` were producing `,.` instead of real text.
- Root cause: distil models were not trained with `initial_prompt` conditioning. Passing the personal vocabulary prompt caused them to return empty output silently.
- Fix: prompt is now suppressed for all distil models. Transcription works correctly.

### Previous: UI Polish (v6.2.3)

## v6.2.3 — UI Polish

### Rounded corners — consistent throughout
- All cards, containers, inputs, buttons, and list rows now use the same corner radius, matching the AI Cleanup action buttons.
- Fixed `_rounded_card_canvas` and `_rr` so the inner frame is inset from canvas edges — rounded arcs are now visible on all cards (previously the inner frame covered them, making cards appear square).
- Custom Commands, Contacts, and Corrections list rows are now visually rounded containers.
- URL / APP / TYPE badges in Custom Commands are Canvas-drawn rounded pills.

### Button alignment & sizing
- AI Cleanup 2×2 button grid rebuilt with `place()` geometry — all four buttons are now pixel-identical in width and height regardless of label length.
- Responsive layout: buttons fill the full row width with no dead space on the right.
- All action button text is bold for uniform visual weight across dark and accent buttons.

### Help page
- "Restart Now" and "Later" buttons are now Canvas-drawn with rounded corners.
- "Copy setup summary" converted to a full-width rounded button.
- Added 24 px breathing room at the bottom of the Help page.

### Snippets window
- Delete and Save Changes button bar height increased so bottom corners are no longer clipped.

### Previous: Language & Translation Controls (v6.2.2)

## v6.2.2 — Language & Translation Controls

### New: Translate My Dictation To
- New dropdown in Settings → Audio & Language: **Off / English / French / Spanish / German / Italian / Portuguese**.
- When set, every dictated sentence is translated to the chosen language after transcription using your local Ollama model.
- Default is **Off** — normal same-language dictation is unchanged.
- Translation is entirely post-transcription; it does not affect Jarvis commands, snippets, or formatting.
- Example: I'm Speaking = English + Translate My Dictation To = French → typed output is in French.

### Fixes: Audio & Language settings reliability
- **Dropdowns now stick** — model and language changes no longer snap back to the previous value after selection. A reentrancy guard prevents the Tkinter trace from double-firing and undoing the selection.
- **Restart Now saves first** — clicking "Restart Now" in the Audio & Language panel now flushes the current dropdown values to disk before relaunching, so the newly chosen model and language are actually applied after restart.
- **Auto-correct incompatible model + language** — selecting a non-English language while an English-only (`.en`) model is chosen automatically switches to the nearest multilingual equivalent (e.g. `small.en → small`) and shows a visible warning label.
- **Menu bar Whisper Model checkmark** — multilingual models (`tiny`, `base`, `small`, `medium`) were missing from the menu bar model list; the checkmark now shows correctly for all models including multilingual ones.
- **Menu bar checkmarks refresh on save** — previously the model/hotkey/strength/profile checkmarks in the menu bar only updated the next time you opened the menu. They now update the instant you click Save Changes.

### UI: Audio & Language page reordered
- **I'm Speaking** now appears above **Speech Model** — the speaking language should be chosen before selecting a model, since the model must match the language.
- Updated **Speech Model** helper text: "English-only models end in .en. Use multilingual models for French, Spanish, and other languages."
- **How language settings work** info card added at the bottom of the page, explaining the role of each setting clearly.

### Previous: Workflows & Offline Clarity (v6.1.19)

#### Workflows page
- Added a new **Workflows** sidebar page in Settings (between Cloud and Help).
- Six instruction cards explain every voice pattern: Basic Dictation, Email Drafts, Reminders, Translation, System Controls, and Contacts.
- Each card shows command examples styled as a distinct block with a **Copy examples** button.

#### Offline-first messaging
- Added **Offline-first** card to the Setup page listing what works without internet and what requires it.
- Added **Works offline** card to the Help page with a full itemised breakdown (available offline vs. may need internet).
- Support summary (Copy setup summary) now opens with the offline-first privacy statement.

#### Storage & Cleanup polish
- Confirmation dialog added before any clear action (History, Vocabulary, Log).
- Clear buttons renamed to **Clear History**, **Clear Vocabulary**, and **Clear Log**.
- HUD status confirmation shown after each successful clear ("History cleared.", etc.).
- Added description line under the Storage & Cleanup section heading.

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
