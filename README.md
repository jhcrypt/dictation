# Jarvis Dictation

Private, Mac-first voice dictation with local Whisper transcription, optional Ollama cleanup, writing profiles, snippets/history, and Jarvis-style commands.

---

## Features

- **Right Option push-to-dictate** — hold to record, release to transcribe and type
- **Local Whisper transcription** — fully offline, no cloud required
- **Optional Ollama cleanup** — local AI polishing with configurable writing profiles
- **Writing Profiles** — General, Professional, Email, Developer, Medical, Legal, Sales, Notes, Creative, and Verbatim
- **Jarvis wake-word dictation** — say "Hey Jarvis" for hands-free recording
- **Snippets** — store and insert reusable text blocks by voice
- **Dictation history** — browse and reuse past transcriptions
- **Safe Mode** — bypass AI cleanup when you need raw output
- **macOS menu bar utility** — lives in the menu bar, out of your way
- **Private by default** — no data leaves your Mac unless you enable cloud mode

---

## Screenshots

_Coming soon._

---

## Requirements

- macOS 12 Monterey or later (Intel Mac)
- Python 3.11
- Conda (Miniconda or Anaconda)
- [Ollama](https://ollama.com) (optional — for AI cleanup)

---

## Installation

### 1. Install Miniconda

```bash
curl -O https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-x86_64.sh
bash Miniconda3-latest-MacOSX-x86_64.sh
```

Restart your terminal after installing.

### 2. Clone the repo

```bash
git clone https://github.com/jhcrypt/dictation
cd dictation
```

### 3. Create the conda environment

```bash
conda create -n dictation python=3.11
conda activate dictation
```

### 4. Install dependencies

```bash
pip install faster-whisper sounddevice numpy openwakeword onnxruntime \
            Pillow symspellpy keyring pyobjc ollama
```

### 5. Download wake word models

```bash
python -c "from openwakeword.utils import download_models; download_models()"
```

### 6. Grant macOS permissions

Go to **System Settings → Privacy & Security** and grant:

- **Microphone** — to your terminal app (iTerm2, Terminal, etc.)
- **Accessibility** — to your terminal app
- **Input Monitoring** — to your terminal app

See [docs/PERMISSIONS.md](docs/PERMISSIONS.md) for full details.

---

## Running from Source

```bash
conda activate dictation
python src/jarvis_dictation.py
```

The app appears in your menu bar. No Dock icon.

---

## Building the Mac App

See [docs/INSTALL.md](docs/INSTALL.md) for detailed instructions.

Quick start:

```bash
conda activate dictation
pip install pyinstaller
cd packaging/mac
chmod +x build_mac_app.sh
./build_mac_app.sh
```

The built app will be at `packaging/mac/dist/JarvisDictation.app`.

> After building, grant Microphone, Accessibility, and Input Monitoring permissions to **JarvisDictation.app** separately in System Settings.

---

## macOS Permissions

| Permission | Why |
|---|---|
| Microphone | Records your voice |
| Accessibility | Types transcribed text into other apps |
| Input Monitoring | Detects the global record hotkey |
| Automation | Controls apps like Reminders, Spark, Spotify |

See [docs/PERMISSIONS.md](docs/PERMISSIONS.md).

---

## Writing Profiles

Select a writing profile in Settings or via the menu bar. The AI cleanup will match the style to your profile:

| Profile | Best For |
|---|---|
| General | Everyday dictation |
| Professional | Business writing |
| Email | Email composition |
| Developer | Code notes, technical writing |
| Medical | Clinical documentation |
| Legal | Legal memos and briefs |
| Sales | Sales emails, pitches |
| Notes | Quick bullet notes |
| Creative | Stories, creative writing |
| Verbatim | Exact transcription, no cleanup |

---

## Hotkeys

| Action | Key |
|---|---|
| Start / stop recording | **Right Option** (recommended) |
| Cancel recording | **Escape** |
| Undo last dictation | **Ctrl+Z** |
| Open Settings | **Ctrl+,** |

**Optional record keys:** F13, F14, F15

Change the record key anytime from Settings.

---

## Troubleshooting

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

---

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md).

---

## License

MIT License. See [LICENSE](LICENSE).
