# Jarvis Dictation

> **Private, Mac-first voice dictation** with local Whisper transcription, optional Ollama AI cleanup, writing profiles, wake word support, and a native menu bar controller.

[![Platform](https://img.shields.io/badge/Platform-macOS-black?style=flat-square&logo=apple)]()
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python)]()
[![Whisper](https://img.shields.io/badge/Transcription-faster--whisper-orange?style=flat-square)]()
[![Ollama](https://img.shields.io/badge/AI%20Cleanup-Ollama%20(optional)-blueviolet?style=flat-square)]()
[![License](https://img.shields.io/badge/License-See%20LICENSE-lightgrey?style=flat-square)]()

---

## Table of Contents

- [What It Does](#what-it-does)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Writing Profiles](#writing-profiles)
- [Jarvis Commands](#jarvis-commands)
- [Hotkeys](#hotkeys)
- [Project Structure](#project-structure)
- [Version History](#version-history)
- [Contributing](#contributing)
- [Security](#security)

---

## What It Does

Jarvis Dictation is a fully local, privacy-first voice dictation app for macOS. Everything runs on your machine — no cloud, no subscription, no data leaving your computer.

You press a hotkey, speak, release, and your words are transcribed and typed directly into whatever app is in focus. Optionally, a local Ollama model can clean up the transcript (punctuation, formatting, grammar) before it's inserted.

It lives in your Mac menu bar and stays out of the way until you need it.

---

## Features

- 🎙️ **Local transcription** via `faster-whisper` — no internet required
- 🍎 **Native macOS menu bar** controller with status icons
- ✍️ **10 writing profiles** — auto-switches based on the frontmost app
- 🤖 **Optional Ollama AI cleanup** — grammar, punctuation, formatting via local LLM
- 🔔 **Wake word detection** via `openwakeword` — hands-free trigger
- ⌨️ **Jarvis voice commands** — formatting and editing by voice
- 📜 **Dictation history** — searchable log of past transcriptions
- 🔒 **100% private** — everything stays on device
- 🛠️ **Packagable as `.app`** — run it like a native Mac application

---

## Requirements

| Requirement | Version / Notes |
|---|---|
| **macOS** | Required (uses Quartz HID, PyObjC, menu bar APIs) |
| **Python** | 3.11 (strictly — other versions not tested) |
| **conda** | Recommended — use the `dictation` environment |
| **Ollama** | Optional — install from [ollama.com](https://ollama.com) for AI cleanup |
| **Microphone** | Any input device; Right Option key recommended as hotkey |

---

## Installation

### 1. Clone the repo

```bash
git clone https://github.com/jhcrypt/dictation.git
cd dictation
```

### 2. Create the conda environment

```bash
conda create -n dictation python=3.11
conda activate dictation
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. (Optional) Install Ollama for AI cleanup

Download and install from [https://ollama.com](https://ollama.com), then pull a model:

```bash
ollama pull llama3
```

### 5. Run

```bash
python src/jarvis_dictation.py
```

The app will appear in your macOS menu bar.

---

## Usage

### Basic dictation

1. Make sure your target app is in focus (VS Code, Notes, browser, etc.)
2. **Hold** the hotkey (default: **Right Option**)
3. **Speak** your text
4. **Release** the key
5. Transcription types automatically into the focused app

### Menu bar

Click the menu bar icon to access:
- Recording status
- Writing profile selection
- Settings (hotkey, Ollama model, cleanup toggle)
- Dictation history
- About / Quit

---

## Writing Profiles

Profiles adjust how Jarvis formats and cleans up your dictation. The app can **auto-detect the active profile** based on the frontmost application.

| Profile | Best For | Auto-detected Apps |
|---|---|---|
| **General** | Everyday dictation | Default fallback |
| **Professional** | Formal documents, reports | Word, Pages, Google Docs |
| **Email** | Email composition | Mail, Outlook, Gmail |
| **Developer** | Code comments, docs, commit messages | VS Code, Xcode, Terminal |
| **Medical** | Clinical notes, terminology | Medical apps |
| **Legal** | Legal documents, contracts | Legal apps |
| **Sales** | CRM notes, outreach | Salesforce, HubSpot |
| **Notes** | Quick notes, lists | Notes, Notion, Bear |
| **Creative** | Creative writing, storytelling | Ulysses, Scrivener |
| **Verbatim** | Exact transcription, no cleanup | Any app |

You can also manually select a profile from the menu bar at any time.

---

## Jarvis Commands

Voice commands for formatting and navigation, triggered mid-dictation:

| Command | Action |
|---|---|
| `"new line"` | Insert newline |
| `"new paragraph"` | Insert double newline |
| `"period"` / `"full stop"` | Insert `.` |
| `"comma"` | Insert `,` |
| `"question mark"` | Insert `?` |
| `"exclamation mark"` | Insert `!` |
| `"open bracket"` / `"close bracket"` | Insert `(` / `)` |
| `"delete that"` | Delete last dictated word |
| `"scratch that"` | Delete entire last utterance |
| `"caps on"` / `"caps off"` | Toggle capitalization mode |

> Commands work in **dual-mode** — they function in both dictation and command mode (added in v6.1.10+).

---

## Hotkeys

| Key | Role |
|---|---|
| **Right Option** *(recommended)* | Hold to record, release to transcribe |
| **F13** | Alternative record key |
| **F14** | Alternative record key |
| **F15** | Alternative record key |

> Left-side modifier keys (Left Option, Command, Control) are **not supported** — the Quartz HID tap architecture requires right-side keys to avoid system conflicts and SIGILL crashes.

Hotkey can be changed in Settings from the menu bar.

---

## Project Structure

```
dictation/
│
├── 📁 src/                              # Main application source
│   ├── jarvis_dictation.py              # ← Current production entry point
│   ├── dictate_icon.png                 # Menu bar icon — idle state
│   ├── icon_idle.png                    # Menu bar icon — idle
│   ├── icon_recording.png               # Menu bar icon — recording
│   └── icon_transcribing.png            # Menu bar icon — transcribing
│
├── 📁 docs/                             # Documentation
│
├── 📁 packaging/mac/                    # macOS .app bundle build kit
│
├── 📁 tools/                            # Dev utilities and helper scripts
│
├── 📄 dictate_v4.py                     # Legacy — v4 baseline
├── 📄 dictate_v5.7.1.py                 # Legacy — v5.7.1
├── 📄 dictate_v5.7.3.py                 # Legacy — v5.7.3
├── 📄 dictate_v5_9_3_safety_history_professional.py  # Legacy — v5.9.3
├── 📄 dictate_v6_0_4_history_transparency.py         # Legacy — v6.0.4
├── 📄 jarvis_dictation.py               # Legacy root copy (use src/ version)
├── 📄 jarvis_dictation_v6_1_17_icon_restore.py       # Legacy — v6.1.17
├── 📄 jarvis_dictation_v6_1_18_spark_desktop.py      # Legacy — v6.1.18
├── 📄 v6_1_18_spark_desktop.patch       # Patch file for v6.1.18
│
├── 📄 frequency_dictionary_en_82_765.txt  # SymSpell dictionary for spell correction
├── 📄 icnsFile_...Gnome_Sound_Recorder.icns  # macOS app icon
│
├── 📄 requirements.txt                  # Python dependencies
├── 📄 CHANGELOG.md                      # Full version history
├── 📄 CONTRIBUTING.md                   # Contribution rules and architecture notes
├── 📄 SECURITY.md                       # Security policy
├── 📄 LICENSE                           # License
├── 📄 README.md                         # This file
└── 📄 .gitignore                        # Excludes conda env, secrets, __pycache__
```

> **Use `src/jarvis_dictation.py` as the entry point.** Root-level `.py` files are versioned archives kept for reference.

---

## Version History

| Version | Highlights |
|---|---|
| **v6.1.18** | Spark desktop integration |
| **v6.1.17** | Icon restore fix |
| **v6.1.10** | Hotkey UI cleanup — simplified to Right Option / F13–F15 |
| **v6.1** | Writing profiles, app-based auto-detection, menu bar profile selection |
| **v6.0** | macOS menu bar controller, `.app` packaging kit, professional settings UI |
| **v5.9** | Ollama safety protections, short-phrase bypass, dictation history |
| **v5.7** | Wake word detection, Ollama cleanup integration |
| **v4** | Baseline — local Whisper, hotkey dictation |

Full changelog in [`CHANGELOG.md`](CHANGELOG.md).

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for full rules. Key points:

- Use **Python 3.11** in the `dictation` conda environment
- Test the terminal version before packaging: `python src/jarvis_dictation.py`
- Syntax check before committing: `python -m py_compile src/jarvis_dictation.py`
- **Do not call Tkinter directly from Quartz, PyObjC, or sounddevice callbacks** — use the queue/main-loop pattern
- **Do not change the hotkey/input system** without careful testing — the Quartz HID tap architecture is the result of many crash-fixing iterations
- Keep Right Option as the default recommended hotkey

---

## Security

See [`SECURITY.md`](SECURITY.md) for the full security policy.

All audio processing is 100% local. No data is transmitted externally. The optional Ollama cleanup also runs entirely on-device.

---

<div align="center">
  <strong>Jarvis Dictation · Private by design · Mac-first · Built for speed</strong>
</div>
