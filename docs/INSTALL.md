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

**Option A — inside the app (easiest):**

Open Settings → **AI Cleanup** → click **Install Recommended Model**. The app will pull the model for you after you click the button.

**Option B — terminal:**

```bash
ollama pull qwen2.5:3b
```

This downloads the recommended model (~2 GB). You only need to do this once.

### Start Ollama

Ollama runs as a background server. Launch it from your Applications folder, or run:

```bash
ollama serve
```

### Verify in the app — page instructions

Open Settings → **AI Cleanup**. The status card at the top shows your current state:

| Status | What to do |
|---|---|
| **✓ Local AI Cleanup ready** | You're set — click **Test Cleanup** to confirm |
| **⚠ Ollama not installed** | Click **Open Ollama Download Page**, install Ollama, launch it, then click **Check Again** |
| **⚠ Ollama installed but not running** | Open Ollama from Applications, then click **Check Again** |
| **⚠ Recommended model not installed** | Make sure Ollama is running, then click **Install Recommended Model** |

Click **Check Again** after making any changes to refresh the status.

#### Step-by-step for each state

**If status shows "⚠ Ollama not installed":**
1. Click **Open Ollama Download Page** — installs Ollama for macOS
2. Launch Ollama from your Applications folder
3. Return to Settings → **AI Cleanup** → click **Check Again**
4. If model is still missing, click **Install Recommended Model**

**If status shows "⚠ Ollama installed but not running":**
1. Open Ollama from your Applications folder (runs as a menu bar icon)
2. Click **Check Again**

**If status shows "⚠ Recommended model not installed":**
1. Make sure Ollama is running (menu bar icon visible)
2. Click **Install Recommended Model** — downloads `qwen2.5:3b` (~2 GB) in the background
3. Do not close the app while downloading — the status card updates automatically when done

**If status shows "✓ Local AI Cleanup ready":**
1. Click **Test Cleanup** — sends a sample phrase through the model and shows the result live
2. Dictation will now be polished automatically after every recording

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
