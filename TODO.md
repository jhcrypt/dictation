# Dictation App — TODO

## ✅ Done
- [x] Working local dictation app (Whisper, offline, no API keys)
- [x] Floating HUD with status dot, app name detection, draggable
- [x] symspellpy post-correction — fixes garbled/misheard words
- [x] GitHub repo created (https://github.com/jhcrypt/dictation)
- [x] Voice commands: "scratch that", "new line", "new paragraph", "tab"
- [x] Voice commands: "select all", "copy that", "copy all", "paste"
- [x] Punctuation commands: "period", "comma", "question mark", etc.
- [x] Cancel recording with Escape
- [x] Ctrl+Z to scratch last dictation
- [x] Settings panel (Ctrl+,) — model switcher + hotkey picker
- [x] App-aware new line (Shift+Enter in chat apps)
- [x] Paste via clipboard (faster, more reliable than typing)
- [x] Configurable hotkey (Right Command, F13, F14, etc.)

## 🔲 Up Next
- [ ] Create downloadable `.app` for Mac (py2app — PyInstaller has tkinter font crash on macOS)
- [ ] Custom word replacements — JSON file for brand names/jargon Whisper gets wrong
- [ ] Silence auto-stop — stop recording automatically after X seconds of silence
- [ ] Dictation history panel — log of everything dictated, searchable
- [ ] Auto-start on login (launch agent)
- [ ] Language selection in menu bar

## 📦 Packaging Notes
- All dependencies must be pure Python or have wheels (no ollama, no external binaries)
- symspellpy ✅ pure Python, bundles cleanly
- faster-whisper ✅ works with py2app/PyInstaller
- Target: single `.app` drag-to-Applications install
