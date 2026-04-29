# Handoff Notes for Claude AI

## Project
Local Whisper dictation app for Mac. Floating HUD, hotkey Ctrl+S to record, releases to transcribe and type into any active app. 100% offline.

## What Was Working Before This Session
- `python dictate.py` inside the `dictate` conda environment
- Used `small.en` Whisper model
- Typed transcribed text into any active app (VSCode, browser, TextEdit, etc.)
- HUD showed recording/transcribing/idle states
- The working original file is at `backup/dictate.py` (small.en version)

## What Was Done This Session

### 1. GitHub repo created
- Repo: https://github.com/jhcrypt/dictation
- Authenticated via `gh auth login`
- `git init` run inside `/Users/artyzen22/Desktop/dictation`
- Committed `dictate.py` (new version) and `TODO.md`
- Later committed `backup/` folder with 3 versions

### 2. `dictate.py` was overwritten
- The working `dictate.py` (base.en, no ollama) was replaced with a new version
- New version added `symspellpy` post-correction and `initial_prompt`
- The original `base.en` version was already gone before this session started
- The `small.en` version is preserved at `backup/dictate.py` — this was the last known working file

### 3. Dependencies installed in wrong Python environments
- `pynput`, `symspellpy` etc. were installed into `/Library/Frameworks/Python.framework/Versions/3.11` (system Python)
- The app runs inside a conda environment called `dictate` using miniconda Python
- This caused `No module named 'pynput'` errors when running with the wrong Python
- `numpy<2` was installed into miniconda to fix a NumPy 2.x conflict with torch/ctranslate2

### 4. Permissions rabbit hole
- Spent time trying to add raw Python binaries to macOS Accessibility — not possible, macOS only accepts .app bundles
- iTerm is in both Input Monitoring and Accessibility
- The "This process is not trusted" warning from pynput is cosmetic and was present in the original working version too

### 5. Current state of local files
```
dictation/
├── dictate.py              ← broken/modified version (has ollama code somehow)
├── TODO.md                 ← new file, fine
├── HANDOFF.md              ← this file
├── backup/
│   ├── dictate.py          ← LAST KNOWN WORKING VERSION (small.en, no ollama)
│   ├── dictate_small_en.py ← same as above, copy
│   └── dictate_symspell.py ← new version with symspellpy
├── list_devices.py
├── test_hotkey.py
├── test_mic.py
├── test_mic2.py
└── test_recording.wav
```

## How to Restore
1. `conda activate dictate`
2. `cp backup/dictate.py dictate.py`
3. `python dictate.py`
4. Verify it types into other apps again

## What Was Actually Wanted
- Keep `backup/` files as untouched local backups
- Add `symspellpy` post-correction to fix misheard words (no LLM, no ollama)
- Add `initial_prompt` to Whisper for better accuracy
- Push to GitHub repo
- All without breaking the working version

## TODO List (from conversation)
- [x] Working dictation app
- [x] Create GitHub repo (https://github.com/jhcrypt/dictation)
- [ ] Brainstorm easy implementable features
- [ ] Create downloadable .app for Mac
- [ ] symspellpy post-correction (implemented but untested due to breakage)
- [ ] Toggle between base.en and small.en from HUD
- [ ] App-aware word lists per active application
- [ ] Personal phrase history/learning

## Notes for Claude
- User is on Intel Mac, miniconda Python 3.11, conda env named `dictate`
- Always run as `conda activate dictate && python dictate.py`
- Do NOT install packages outside the conda environment
- Do NOT overwrite `dictate.py` without backing up first
- The "not trusted" pynput warning is normal and was present when app was working
- symspellpy dictionary path: `/Users/artyzen22/miniconda3/lib/python3.11/site-packages/symspellpy/frequency_dictionary_en_82_765.txt`
