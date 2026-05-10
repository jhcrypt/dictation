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

## Step 7 — Install Ollama (optional)

Download and install from [https://ollama.com](https://ollama.com).

Then pull a model:

```bash
ollama pull llama3.2:1b
```

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
