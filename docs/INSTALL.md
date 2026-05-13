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

### Setup entirely inside the app

1. Open the app, then go to **Settings → AI Cleanup**.
2. The status card at the top tells you exactly what to do.

---

#### If status shows "⚠ Ollama not installed"

1. Click **Open Ollama Download Page** inside the app.
2. Download and install Ollama for macOS.
3. Launch **Ollama** from your Applications folder.
4. Return to Settings → **AI Cleanup** and click **Check Again**.

#### If status shows "⚠ Recommended model not installed"

1. Make sure Ollama is running (its icon appears in the menu bar).
2. Click **Install Recommended Model** — the app downloads `qwen2.5:3b` (~2 GB).
3. Wait for the status card to update — do not close the app during the download.

#### If status shows "⚠ Ollama installed but not running"

1. Open **Ollama** from your Applications folder.
2. Click **Check Again** in Settings → AI Cleanup.

#### If status shows "✓ Local AI Cleanup ready"

You're done. Click **Test Cleanup** to confirm everything is working — you'll see a sample phrase go in and the cleaned result come out.

---

### Alternative: terminal setup

If you prefer the terminal:

```bash
# Install Ollama from https://ollama.com, then:
ollama pull qwen2.5:3b
ollama serve
```

Then open Settings → **AI Cleanup** → click **Check Again**.

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
