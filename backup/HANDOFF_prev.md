# Handoff Notes for Claude AI

## Project
Local Whisper dictation app for Mac. Floating HUD, hotkey Ctrl+S to record, releases to transcribe and type into any active app. 100% offline.

## GitHub Repo
https://github.com/jhcrypt/dictation

## Environment
- Intel Mac, macOS 15.7.1
- conda env: `dictate` (Python 3.11, miniconda)
- Always run: `conda activate dictate && python dictate.py`
- MIC_DEVICE = 2 (MacBook Pro Microphone, 48000Hz sample rate)

## Current Working State
- `small.en` Whisper model
- Hold Ctrl+S to record, release to transcribe and type
- symspellpy post-correction enabled
- initial_prompt set for better accuracy
- Tested working in: Mail, Claude Desktop, Notes

## File Structure
```
dictation/
├── dictate.py              ← current working version
├── TODO.md
├── HANDOFF.md
├── backup/
│   ├── dictate.py                ← small.en version
│   ├── dictate_small_en.py       ← copy
│   ├── dictate_symspell.py       ← symspell version
│   └── dictate_working_v2.py     ← latest backup
├── list_devices.py
├── test_hotkey.py
├── test_mic.py
├── test_mic2.py
└── test_recording.wav
```

## Dependencies (all in conda env `dictate`)
- faster-whisper
- sounddevice
- pynput
- numpy (<2)
- symspellpy

## Key Config (top of dictate.py)
- MODEL = "small.en"
- MIC_DEVICE = 2
- SAMPLE_RATE = 48000
- symspell dict: ~/miniconda3/lib/python3.11/site-packages/symspellpy/frequency_dictionary_en_82_765.txt

## Known Issues / Notes
- pynput "not trusted" warning is cosmetic, app works fine
- Do NOT install packages outside conda env
- Do NOT overwrite dictate.py without backing up first
- Ctrl+S may conflict in some apps (Claude Desktop) — future: make hotkey configurable

## TODO List
- [x] Working dictation app
- [x] Create GitHub repo (https://github.com/jhcrypt/dictation)
- [x] symspellpy post-correction
- [ ] Brainstorm easy implementable features
- [ ] Create downloadable .app for Mac
- [ ] Toggle between base.en and small.en from HUD
- [ ] Configurable hotkey
- [ ] App-aware word lists per active application
- [ ] Personal phrase history/learning
- [ ] Ollama post-correction (explored, optional)

## How to Start Next Session
1. Upload this HANDOFF.md to Claude
2. Optionally share latest dictate.py or say "fetch from GitHub"
3. Claude can fetch raw file via:
   https://raw.githubusercontent.com/jhcrypt/dictation/main/dictate.py
