# Installation Guide

## Requirements

- Intel Mac (x86_64)
- macOS 12 Monterey or later
- Python 3.11 (via Miniconda)
- 4 GB RAM minimum (8 GB recommended for `small.en` model)
- [Ollama](https://ollama.com) — optional, for local AI cleanup

---

## Step 1 — Install Miniconda

```bash
curl -O https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-x86_64.sh
bash Miniconda3-latest-MacOSX-x86_64.sh
```

Restart your terminal after installing.

---

## Step 2 — Clone the repo

```bash
git clone https://github.com/jhcrypt/dictation
cd dictation
```

---

## Step 3 — Create the conda environment

```bash
conda create -n dictation python=3.11
conda activate dictation
```

---

## Step 4 — Install dependencies

```bash
pip install -r requirements.txt
```

---

## Step 5 — Download Whisper models

The app will download models automatically on first use. To pre-download them:

```bash
python -c "
from faster_whisper import WhisperModel
WhisperModel('tiny.en')
WhisperModel('base.en')
"
```

---

## Step 6 — Download wake word models

```bash
python -c "from openwakeword.utils import download_models; download_models()"
```

---

## Step 7 — Set up Local AI Cleanup (optional)

**Jarvis Dictation works without this step.** Dictation, hotkeys, snippets, Jarvis commands, and history all work without Ollama. Local AI Cleanup is an optional enhancement that polishes dictated text on your Mac after Whisper transcribes it.

### Install Ollama

Download and install from [https://ollama.com](https://ollama.com).

### Install the recommended model

After installing Ollama, open a terminal and run:

```bash
ollama pull qwen2.5:3b
```

This downloads the recommended model (~2 GB). You only need to do this once.

> **Tip:** You can also install the model directly from inside the app. Open Settings → **AI Cleanup** → click **Install Recommended Model**. The app will pull the model for you after you click the button.

### Start Ollama

Ollama runs as a background server. Launch it from your Applications folder, or run:

```bash
ollama serve
```

### Verify in the app

Open Settings → **AI Cleanup**. The status card will show one of:

| Status | Meaning |
|---|---|
| **✓ Local AI Cleanup ready** | Everything is set up correctly |
| **⚠ Ollama not installed** | Download from ollama.com |
| **⚠ Ollama installed but not running** | Start Ollama from Applications |
| **⚠ Recommended model not installed** | Click "Install Recommended Model" |

Click **Check Again** after making changes to refresh the status.

---

## Step 8 — Grant macOS permissions

See [PERMISSIONS.md](PERMISSIONS.md) for the full list.

---

## Running from source

```bash
conda activate dictation
python src/jarvis_dictation.py
```

---

## Building the Mac App

```bash
conda activate dictation
pip install pyinstaller
cd packaging/mac
chmod +x build_mac_app.sh
./build_mac_app.sh
```

Output: `packaging/mac/dist/JarvisDictation.app`

After building, copy the app to `/Applications` and grant permissions to the **JarvisDictation.app** bundle specifically in System Settings.

> **Note:** Permissions granted to Terminal/Python are separate from permissions granted to the packaged `.app`. You must grant them again after building.

---

## Optional dependencies

| Package | Purpose |
|---|---|
| `ollama` | Local AI cleanup — requires Ollama server running |
| `pyinstaller` | Building the packaged `.app` — dev only |
