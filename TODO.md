# Dictation App — TODO

## ✅ Done
- [x] Working local dictation app (Whisper, offline, no API keys)
- [x] Hotkey recording (Ctrl+S hold to record, release to transcribe)
- [x] Floating HUD with status dot, app name detection, draggable
- [x] `base.en` model for speed on Intel Mac
- [x] `symspellpy` post-correction — fixes garbled/misheard words
- [x] `initial_prompt` to improve Whisper accuracy
- [x] GitHub repo created

## 🔲 Up Next
- [ ] Create downloadable `.app` for Mac (py2app or PyInstaller)
- [ ] Brainstorm + implement easy features (see below)

## 💡 Feature Ideas
- [ ] Personal phrase history — learn your common phrases over time for better correction
- [ ] App-aware word lists — load different vocabulary depending on active app (Claude, Notes, email, etc.)
- [ ] n-gram prediction — frequency map of your word pairs/triples for smarter completions
- [ ] Toggle between `base.en` (fast) and `small.en` (accurate) from the HUD
- [ ] Mute/pause button in HUD
- [ ] Sound feedback on start/stop recording

## 📦 Packaging Notes
- All dependencies must be pure Python or have wheels (no ollama, no external binaries)
- `symspellpy` ✅ pure Python, bundles cleanly
- `faster-whisper` ✅ works with py2app/PyInstaller
- Target: single `.app` drag-to-Applications install
