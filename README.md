# Cryptic Dictation App

A powerful local voice dictation app for Mac with AI-powered commands, wake word detection, and smart formatting.

## Features

- 🎙️ **Hold Right ⌘** to record and transcribe
- 🤖 **Hey Jarvis** wake word (hands-free)
- 🧠 **AI Commands** — open apps, search web, compose emails, control volume
- ✂️ **Smart Editing** — scratch that, scratch last 2/3, undo
- 💅 **Smart Formatting** — bold, italic, code, heading, bullet lists
- 📚 **Personal Learning** — gets smarter the more you use it
- 🌍 **Multi-language** — 13 languages supported
- ⏸️ **Media Control** — pauses Spotify/Music while dictating

---

## Requirements

- macOS 12+ (Monterey or later)
- Python 3.11
- Conda (Miniconda or Anaconda)
- Homebrew (optional)

---

## Installation

### Step 1 — Install Miniconda (if not already installed)

**Intel Mac:**
```bash
curl -O https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-x86_64.sh
bash Miniconda3-latest-MacOSX-x86_64.sh
```

**M1/M2 Mac:**
```bash
curl -O https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh
bash Miniconda3-latest-MacOSX-arm64.sh
```

Restart terminal after installing.

---

### Step 2 — Clone the repo

```bash
git clone https://github.com/jhcrypt/dictation
cd dictation
```

---

### Step 3 — Create conda environment

```bash
conda create -n dictation python=3.11
conda activate dictation
```

---

### Step 4 — Install dependencies

```bash
pip install faster-whisper symspellpy pynput sounddevice numpy openwakeword onnxruntime Pillow
```

---

### Step 5 — Download wake word models

```bash
python3 -c "from openwakeword.utils import download_models; download_models()"
```

---

### Step 6 — Grant permissions

Go to **System Settings → Privacy & Security** and enable:
- ✅ **Microphone** — for your terminal app
- ✅ **Accessibility** — for your terminal app
- ✅ **Input Monitoring** — for your terminal app

---

### Step 7 — Run

```bash
conda activate dictation
python dictate_v2.py
```

---

## M1/M2 Mac Additional Setup

After cloning or pulling, run the M1 setup script:

```bash
bash m1_setup.sh
```

This automatically fixes:
- Symspell dictionary path
- Microphone device index
- Audio sensitivity threshold
- Cross-platform compatibility

Then run:
```bash
/Users/$USER/miniconda3/envs/dictation/bin/python dictate_v2.py
```

---

## Usage

| Action | How |
|--------|-----|
| Dictate | Hold **Right ⌘**, speak, release |
| Wake word | Say **"Hey Jarvis"** |
| Cancel | Press **Escape** |
| Settings | Press **Ctrl+D** or menu bar |
| Scratch last | Say **"scratch that"** |
| Scratch last 2 | Say **"scratch last two"** |
| Bold text | Say **"make bold"** after dictating |
| Open app | Say **"open YouTube"** |
| Search | Say **"search for Python tutorials"** |
| Volume | Say **"volume up"** / **"volume down"** |
| Email | Say **"send email to John saying hello"** |
| Language | Say **"switch to Spanish"** |

---

## Troubleshooting

**Symspell dictionary not found:**
```bash
python3 -c "
import symspellpy, os, re
path = os.path.join(os.path.dirname(symspellpy.__file__), 'frequency_dictionary_en_82_765.txt')
with open('dictate_v2.py') as f: content = f.read()
content = re.sub(r'\"[^\"]*frequency_dictionary_en_82_765\.txt\"', f'\"{path}\"', content)
with open('dictate_v2.py', 'w') as f: f.write(content)
print('Fixed:', path)
"
```

**Wrong microphone device:**
```bash
python3 -c "import sounddevice as sd; print(sd.query_devices())"
```
Note the input device number, then update in settings or run:
```bash
python3 -c "
with open('dictate_v2.py') as f: c = f.read()
c = c.replace('MIC_DEVICE  = 2', 'MIC_DEVICE  = 0')  # change 0 to your device number
with open('dictate_v2.py', 'w') as f: f.write(c)
"
```

**Accessibility permission error:**
Go to System Settings → Privacy & Security → Accessibility → Add Terminal

**App crashes on startup (M1):**
```bash
bash m1_setup.sh
```

---

## Models

| Model | Speed | Accuracy | Best For |
|-------|-------|----------|---------|
| tiny.en | ⚡⚡⚡ | ★★★ | Fast machines, simple dictation |
| base.en | ⚡⚡ | ★★★★ | Good balance |
| small.en | ⚡ | ★★★★★ | Best accuracy (recommended) |
| medium.en | 🐢 | ★★★★★ | High-end machines only |

Switch models anytime from the menu bar or Settings.

