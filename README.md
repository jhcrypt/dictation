# Jarvis Dictation — Complete User Manual

100% offline voice dictation for macOS. Hold a key, speak, release — your words appear wherever the cursor is. No cloud required, no subscription, no data leaving your Mac.

---

## Table of Contents

1. [Overview](#overview)
2. [Requirements](#requirements)
3. [Installation](#installation)
4. [First Launch & Permissions](#first-launch--permissions)
5. [The HUD](#the-hud)
6. [Core Dictation](#core-dictation)
7. [Record Keys & Hotkeys](#record-keys--hotkeys)
8. [AI Cleanup — Ollama](#ai-cleanup--ollama)
9. [Writing Profiles](#writing-profiles)
10. [Context-Aware Formatting](#context-aware-formatting)
11. [Voice Commands — Scratch & Undo](#voice-commands--scratch--undo)
12. [Voice Commands — Formatting](#voice-commands--formatting)
13. [Voice Commands — Editing & Navigation](#voice-commands--editing--navigation)
14. [Voice Commands — Text Operations](#voice-commands--text-operations)
15. [Jarvis Commands — App & System Control](#jarvis-commands--app--system-control)
16. [Snippets](#snippets)
17. [Dictation History](#dictation-history)
18. [Custom Commands](#custom-commands)
19. [Custom Vocabulary](#custom-vocabulary)
20. [Safe Mode](#safe-mode)
21. [Hey Jarvis Wake Word](#hey-jarvis-wake-word)
22. [Cloud Transcription](#cloud-transcription)
23. [Menu Bar Reference](#menu-bar-reference)
24. [Settings Panel — All Pages](#settings-panel--all-pages)
25. [Privacy & Security](#privacy--security)
26. [Building the App from Source](#building-the-app-from-source)
27. [Troubleshooting](#troubleshooting)

---

## Overview

Jarvis Dictation is a macOS menu bar app that transcribes your voice using [Whisper](https://github.com/openai/whisper) running entirely on your Mac and types the result into any app — no internet connection required.

On top of transcription it offers:

- Local AI cleanup via [Ollama](https://ollama.com) tuned by 10 writing profiles
- A full library of voice commands for editing, formatting, and controlling your Mac
- A voice-activated assistant ("Jarvis") for opening apps, searching, composing emails, controlling media, and more
- Snippets, dictation history, custom commands, and a personal vocabulary

---

## Requirements

| Requirement | Detail |
|---|---|
| macOS | 10.15 Catalina or later (Intel or Apple Silicon) |
| Python | 3.11 (via Conda) |
| Conda | Miniconda or Anaconda |
| Ollama | Optional — local AI cleanup |
| OpenAI API key | Optional — cloud transcription fallback |

---

## Installation

### 1 — Install Miniconda

```bash
curl -O https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-x86_64.sh
bash Miniconda3-latest-MacOSX-x86_64.sh
```

Restart your terminal after installing.

### 2 — Clone the repo

```bash
git clone https://github.com/jhcrypt/dictation
cd dictation
```

### 3 — Create the conda environment

```bash
conda create -n dictation python=3.11
conda activate dictation
```

### 4 — Install dependencies

```bash
pip install faster-whisper sounddevice numpy openwakeword onnxruntime \
            Pillow symspellpy keyring pyobjc ollama
```

### 5 — Download wake word models (optional)

Only required if you plan to use "Hey Jarvis" hands-free mode:

```bash
python -c "from openwakeword.utils import download_models; download_models()"
```

### 6 — Run from source

```bash
conda activate dictation
python src/jarvis_dictation.py
```

The app appears in your menu bar. There is no Dock icon.

---

## First Launch & Permissions

macOS requires explicit permission for three system features. On first launch the app will prompt for each one. You can also grant them manually:

**System Settings → Privacy & Security**

| Permission | Why it is needed |
|---|---|
| **Microphone** | Records your voice |
| **Accessibility** | Types transcribed text into other apps |
| **Input Monitoring** | Detects the global record hotkey |
| **Automation** | Controls apps like Reminders, Spotify, Spark (only used by Jarvis commands) |

> If the app was just built or reinstalled, macOS may not show a prompt automatically. Go to System Settings → Privacy & Security → Accessibility and add Jarvis Dictation manually.

---

## The HUD

The HUD (Heads-Up Display) is a floating pill that appears at the top of your screen whenever you dictate. It shows you exactly what the app is doing at every step.

### HUD states

| State | Colour | Meaning |
|---|---|---|
| **Idle** | Gray | Ready to record |
| **Recording** | Red + animated waveform | Actively capturing your voice |
| **Transcribing** | Blue | Whisper is processing the audio |
| **Processing** | Blue | Ollama is cleaning up the text |
| **Done** | Green (brief flash) | Text was pasted successfully |
| **Message** | Varies | Jarvis confirmation, error, or status |

### HUD details

- **Draggable** — click and drag the HUD to reposition it anywhere on screen. Position is remembered between sessions.
- **Active app icon** — shows the icon of the app that will receive your dictation.
- **Profile badge** — shows the active writing profile (e.g. "Developer").
- **Marquee scroll** — long messages scroll across the HUD automatically.
- **Show/Hide** — toggle from the menu bar or Settings → Dictation.
- **Startup tips mode** — when enabled, shows friendly guidance ("Speak now…") instead of technical status.

---

## Core Dictation

### How it works

1. Place your cursor in any text field in any app.
2. Hold (or press) your record key — the HUD turns red and the waveform animates.
3. Speak naturally in complete sentences.
4. Release (or press again) the record key.
5. Whisper transcribes the audio, Ollama optionally cleans it up, and the text is pasted at the cursor.

### Toggle mode vs. hold mode

| Mode | Behaviour |
|---|---|
| **Toggle mode** (default) | Press once to start, press again to stop |
| **Hold mode** | Hold the key to record, release to stop |

Toggle mode is the recommended default. Change in Settings → Dictation.

### Audio quality tips

- Speak in complete phrases — Whisper performs best with natural sentence structure.
- Pause briefly before releasing the key so the final word is captured.
- If the HUD shows "quiet audio", speak louder or move the microphone closer.
- Background music and noise can reduce accuracy. Use macOS Voice Isolation (Control Centre → Mic Mode) if available.

### Whisper models

| Model | Speed | Accuracy | Recommended for |
|---|---|---|---|
| `tiny.en` | Fastest | Lower | Testing only |
| `base.en` | Fast | Good | Intel Macs, quick notes |
| `small.en` | Moderate | Best balance | **Recommended default** |
| `medium.en` | Slow | High | When accuracy matters most |
| `large-v2 / large-v3` | Very slow | Highest | Fast Apple Silicon only |
| `distil-medium.en` | Moderate | High | Apple Silicon |
| `distil-large-v3` | Moderate | Highest | Apple Silicon |

Switch models from the menu bar → **Whisper Model** or Settings → **Audio**.

### Spell correction

Symspell runs on the transcribed text before pasting. Correction strength can be set per session:

| Strength | Effect |
|---|---|
| **Off** | No correction |
| **Light** | Fixes obvious typos only |
| **Standard** | Balanced (recommended) |
| **Strong** | Aggressive correction — may alter rare words |

Change from the menu bar → **Correction Strength** or Settings → **AI Cleanup**.

### Media pause

When you start recording, Jarvis Dictation automatically mutes and pauses any playing media (Spotify, Apple Music, system audio). Media resumes when the recording stops.

---

## Record Keys & Hotkeys

The record key is a global hotkey that works in any app, even when Jarvis Dictation is not focused.

### Available keys

| Key | Notes |
|---|---|
| **Right Option** | Recommended default. Does not interfere with left Option shortcuts. |
| **F13** | Available on extended keyboards |
| **F14** | Available on extended keyboards |
| **F15** | Available on extended keyboards |

Change from the menu bar → **Record Key** or Settings → **Dictation**.

> **Why not Command or Control?** These keys are heavily used by macOS and other apps. Assigning them as a global record key causes conflicts and was found unreliable on many Mac keyboards.

### Cancel a recording

Press **Escape** at any time while recording to discard the audio without transcribing.

---

## AI Cleanup — Local AI Cleanup (Optional)

> **Jarvis Dictation works without this.** Dictation, hotkeys, snippets, Jarvis commands, and history all work without Ollama. Local AI Cleanup is an optional enhancement.

[Ollama](https://ollama.com) runs a local language model on your Mac to polish Whisper's raw transcription. No internet connection is used. Your voice never leaves your Mac.

### What Local AI Cleanup does

- Fixes punctuation, capitalisation, and spacing.
- Applies the active writing profile's tone and style.
- Preserves your words — it does not add, invent, or substantially rewrite content.

### What it does NOT do

- It does not answer questions or act as a chatbot.
- It does not correct normal manual typing — only dictated text.
- It is bypassed automatically for very short phrases (one or two words).
- Any result that changes meaning, word count, or answers a question is rejected and the original Whisper text is used instead.

### Setting it up

1. Install Ollama from [https://ollama.com](https://ollama.com).
2. Open Settings → **AI Cleanup** in the app.
3. The status card will show what is missing. Click **Install Recommended Model** to pull `qwen2.5:3b`.
4. Click **Check Again** after making changes to refresh the status.

Or install the model manually:

```bash
ollama pull qwen2.5:3b
```

### Cleanup mode

| Mode | Behaviour |
|---|---|
| **auto** (default) | Use Local AI Cleanup if available; skip silently if not |
| **on** | Always try to use it; show a warning if unavailable |
| **off** | Never use Local AI Cleanup |

### Correction strength

| Strength | Behaviour |
|---|---|
| **Off** | Disabled; raw Whisper text is used |
| **Light** | Minimal corrections — punctuation and obvious errors only |
| **Standard** | Balanced cleanup (recommended) |
| **Strong** | More thorough rewriting while still preserving meaning |

---

## Writing Profiles

Profiles tune the cleanup style for different types of work. Select a default in Settings → **Writing Profiles** or from the menu bar → **Writing Profile**.

| Profile | Best for | What it does |
|---|---|---|
| **General** | Everyday dictation | Balanced cleanup, preserves your wording |
| **Professional** | Business writing, reports | Clear and polished without sounding stiff |
| **Email** | Email composition | Complete sentences, polite professional tone; no greetings or sign-offs added unless you say them |
| **Developer** | Code notes, technical writing | Preserves technical terms, commands, filenames, paths, variable names, acronyms, and casing exactly |
| **Medical** | Clinical notes | Preserves clinical terminology, medication names, measurements, and dictated structure |
| **Legal** | Legal memos, briefs | Precise formal language; preserves names, dates, clauses, and citations |
| **Sales** | Sales emails, pitches | Concise, client-friendly, and persuasive while preserving factual meaning |
| **Notes** | Quick bullet notes | Clean note format; bullets only if you clearly dictated a list |
| **Creative** | Stories, creative writing | Improves flow and readability while preserving your voice |
| **Verbatim** | Exact transcription | Minimal cleanup — fixes only punctuation, spacing, and obvious recognition errors |

### Auto-detection by app

When **Auto-detect profile by app** is enabled, the profile switches automatically based on which app is in focus:

| App | Auto profile |
|---|---|
| Mail, Spark, Spark Desktop, Outlook, Gmail | Email |
| Terminal, iTerm, VS Code, Xcode | Developer |
| Notes, Notion, Obsidian | Notes |
| Word, Pages | Professional |
| Slack, Messages, Teams | General |

---

## Context-Aware Formatting

When **Context-aware formatting** is enabled (Settings → AI Cleanup), Jarvis Dictation applies light formatting adjustments based on the active app — independent of the writing profile. For example, email clients receive a formal tone pass, and developer tools preserve technical casing.

This is separate from Writing Profiles and layered on top. Disable it in Settings if you want the profile to be the only influence.

---

## Voice Commands — Scratch & Undo

Say these commands instead of dictating text. They take effect immediately — no typing needed.

### Delete last dictation

| Say | Effect |
|---|---|
| `scratch that` | Deletes the last dictated phrase |
| `undo that` | Same as scratch that |
| `delete that` | Same as scratch that |
| `scratch` | Same as scratch that |
| `undo` | Same as scratch that |
| `scratch last` | Same as scratch that |

### Delete multiple dictations

| Say | Effect |
|---|---|
| `scratch again` | Deletes one more previous phrase |
| `undo again` | Same as scratch again |
| `scratch last 2` / `scratch two` | Deletes the last 2 phrases |
| `scratch last 3` / `scratch three` | Deletes the last 3 phrases |
| `scratch all` / `undo all` / `clear all` | Deletes all session dictation |

### Undo / redo stack

| Say | Effect |
|---|---|
| `undo dictation` / `undo last` | Removes the last pasted phrase and steps back in the undo stack |
| `redo dictation` / `redo last` | Re-pastes the next phrase in the redo stack |
| `re-insert last` / `insert last` / `paste last` | Re-pastes the most recent dictation at the current cursor position |

---

## Voice Commands — Formatting

These commands format either the text you just dictated (inline) or the previous phrase (standalone).

**Inline example:** say *"the quick brown fox all caps"* → types `THE QUICK BROWN FOX`

**Standalone example:** say *"all caps"* alone → reformats the last dictated phrase

| Say | Effect | Example output |
|---|---|---|
| `all caps` / `make caps` / `capitalize that` | UPPERCASE | `THE QUICK BROWN FOX` |
| `make bold` / `bold that` | Markdown bold | `**the quick brown fox**` |
| `make italic` / `italic that` | Markdown italic | `*the quick brown fox*` |
| `format as code` / `code that` / `make code` | Inline code | `` `the quick brown fox` `` |
| `make heading` / `heading that` / `make title` | Markdown heading | `# The quick brown fox` |
| `make bullet` / `bullet that` / `create list` / `make list` | Bulleted list | `• The quick brown fox` |
| `make quote` / `quote that` / `block quote` | Block quote | `> The quick brown fox` |
| `strikethrough that` / `strike that` | Strikethrough | `~~the quick brown fox~~` |

---

## Voice Commands — Editing & Navigation

| Say | Effect |
|---|---|
| `new line` / `next line` | Inserts a new line. In chat apps (Slack, Claude, Discord, Messages, Teams, WhatsApp, Telegram) uses Shift+Enter to avoid sending |
| `new paragraph` | Inserts two new lines |
| `tab` / `indent` | Inserts a tab character |
| `select all` | Selects all text in the active document (Cmd+A) |

### Punctuation by voice

Say any of these alone to insert the symbol directly:

| Say | Inserts |
|---|---|
| `period` / `full stop` | `.` |
| `comma` | `,` |
| `exclamation point` / `exclamation mark` | `!` |
| `question mark` | `?` |
| `colon` | `:` |
| `semicolon` | `;` |
| `ellipsis` | `...` |
| `open paren` | `(` |
| `close paren` | `)` |
| `dash` | ` — ` |
| `hyphen` | `-` |

---

## Voice Commands — Text Operations

| Say | Effect |
|---|---|
| `copy that` / `copy last` | Copies the last dictated phrase to the clipboard |
| `copy all` | Selects all text in the active field and copies it |
| `paste` / `paste that` | Triggers Cmd+V — pastes whatever is on the clipboard |
| `show history` / `dictation history` / `view history` | Opens the Dictation History window |

---

## Jarvis Commands — App & System Control

Jarvis commands are voice actions that control your Mac. Say them as natural phrases — the prefix **"Jarvis"** or **"Hey Jarvis"** is optional when Jarvis Commands are enabled.

Enable or disable from the menu bar → **Jarvis Commands** or Settings → **Jarvis**.

> Jarvis commands are ignored when Safe Mode is on.

---

### Open apps and websites

| Say | Effect |
|---|---|
| `open Safari` | Opens Safari |
| `open Slack` | Opens Slack |
| `open Terminal` | Opens Terminal |
| `open Notes` | Opens Notes |
| `open Calendar` | Opens Calendar |
| `open Messages` | Opens Messages |
| `open Maps` | Opens Maps |
| `open FaceTime` | Opens FaceTime |
| `open [any app name]` | Opens any installed Mac application |
| `open Netflix` | Opens Netflix in the browser |
| `open Spotify` | Opens Spotify |
| `open YouTube` | Opens YouTube in the browser |

---

### Web search

| Say | Effect |
|---|---|
| `search for [query]` | Opens a web search for your query |
| `search [query]` | Same |
| `google [query]` | Same |
| `look up [query]` | Same |
| `find [query]` | Same |

---

### Email

| Say | Effect |
|---|---|
| `email [name]` | Opens Spark Desktop / Spark / Mail / Outlook with recipient pre-filled |
| `compose email to [name]` | Same |
| `write an email to [name]` | Same |
| `send email to [name]` | Same |
| `new email to [name]` | Same |
| `email [name] about [subject]` | Opens email with recipient and subject |

The app tries Spark Desktop first, then Spark, then Mail, then Outlook.

---

### System volume

| Say | Effect |
|---|---|
| `volume up` / `turn volume up` / `louder` | Increases system volume by 25% |
| `volume down` / `turn volume down` / `quieter` | Decreases system volume by 25% |
| `mute` / `mute volume` | Mutes system audio |
| `unmute` | Unmutes system audio |
| `set volume to [0–100]` | Sets system volume to an exact level |

---

### Screenshots (via Shottr)

Requires [Shottr](https://shottr.cc) to be installed.

| Say | Effect |
|---|---|
| `screenshot` / `take a screenshot` / `capture screen` | Full screen capture |
| `capture window` / `window screenshot` | Window capture |
| `area capture` / `capture area` / `area screenshot` | Interactive area selection |
| `scrolling capture` / `capture scrolling` | Scrolling capture |
| `text recognition` / `extract text` / `recognize text` | OCR text extraction |

---

### Reminders

| Say | Effect |
|---|---|
| `remind me to [task]` | Creates a new reminder in the Reminders app |
| `set a reminder to [task]` | Same |
| `add reminder [task]` | Same |

---

### Calendar

| Say | Effect |
|---|---|
| `open calendar` / `check calendar` | Opens the Calendar app |
| `what's on my calendar` | Opens the Calendar app |

---

### Weather

| Say | Effect |
|---|---|
| `check weather` / `what's the weather` / `weather today` | Opens a weather search |
| `weather in [city]` | Opens a weather search for a specific location |

---

### Close and quit apps

| Say | Effect |
|---|---|
| `close [app]` | Closes the named application (Cmd+Q) |
| `kill [app]` | Force-quits the named application |

---

### Spotify & Music

| Say | Effect |
|---|---|
| `play [song or artist] on Spotify` | Searches Spotify for the song or artist |
| `play coding playlist` | Opens the coding playlist |
| `play workout playlist` | Opens the workout playlist |
| `play playlist 4 / 5 / 6` | Opens custom playlists (configured in USER_CONFIG) |

---

## Snippets

Snippets let you store long blocks of text and insert them with a short trigger phrase.

### Creating a snippet

**By voice:**

1. Say `create snippet` (or `new snippet`, `add snippet`, `make snippet`).
2. The HUD prompts you — say your **trigger phrase** (the short phrase you'll speak to expand it).
3. The HUD prompts again — say the **content** (the full text to insert).
4. Done. The snippet is saved.

**Via the Snippets panel:**

- Open from the menu bar → **Snippets**.
- Click **New** to create, type the trigger and content, click **Save**.
- Select any snippet in the sidebar and edit or delete it.

### Using a snippet

Simply dictate the trigger phrase. When Jarvis Dictation detects it in the transcription, it automatically replaces it with the stored content before pasting.

**Email normalisation:** when creating a snippet, you can say "at" and "dot" in email addresses — they are normalised to `@` and `.` automatically.

### Snippets file

Snippets are stored in `~/.dictation_snippets.json`. You can edit this file directly.

---

## Dictation History

Jarvis Dictation keeps a persistent log of your last 100 dictations.

### Viewing history

- Menu bar → **History**
- Or say `show history` / `dictation history`

### What is recorded

Each entry shows:

- **Final text** — the text that was actually pasted
- **Whisper text** — the raw transcription before AI cleanup
- **Ollama text** — what Ollama suggested (if different)
- **Status** — whether Ollama was accepted, rejected, or skipped
- **Profile** — the writing profile that was active
- **App** — which app received the text
- **Timestamp**

### History file

History is stored in `~/.dictation_history.json`. You can back this file up or clear it by deleting it.

---

## Custom Commands

Custom commands let you create your own voice triggers that open URLs, launch apps, or type predefined text.

### Creating a custom command

Settings → **Custom Commands**:

1. Enter a **trigger phrase** (must be at least two words).
2. Choose an **action type**:
   - **Open URL** — opens any URL in the default browser (also works with `spotify:`, `music:`, `mailto:` links)
   - **Open App** — opens a macOS application by name
   - **Type Text** — types a block of text at the cursor
3. Enter the **target** (URL, app name, or text).
4. Click **Add Command**.

### Using custom commands

Say the trigger phrase during dictation. Custom commands are checked before built-in Jarvis commands, so your commands take priority.

**Example:**

| Trigger | Action | Target |
|---|---|---|
| `open dashboard` | Open URL | `https://example.com/dashboard` |
| `launch postman` | Open App | `Postman` |
| `insert signature` | Type Text | `Best regards,\nYour Name` |

### Custom commands file

Custom commands are stored in `~/.dictation_commands.json`.

---

## Custom Vocabulary

Whisper can struggle with proper nouns, brand names, domain-specific terms, and unusual words. The vocabulary list feeds these words to Whisper as a hint before each transcription.

### Adding vocabulary

Settings → **Vocabulary**:

- Type words, names, or phrases separated by commas or new lines.
- Click **Save changes**.

**Examples:** `Kubernetes`, `Anthropic`, `llama3`, `FastAPI`, `Dr. Mehta`, `Zurich`

### Auto-learning

Jarvis Dictation automatically learns from every dictation — words you use frequently are added to the vocabulary hint over time. This improves recognition of your personal vocabulary without any manual work.

---

## Safe Mode

Safe Mode is a one-click way to get raw, unprocessed dictation. When enabled:

- **Ollama cleanup is disabled** — raw Whisper text is pasted
- **Jarvis commands are ignored** — voice commands are treated as dictation
- **Cloud transcription is disabled** — local Whisper only
- **Context-aware formatting is disabled**

### Toggling Safe Mode

- Menu bar → **Safe Mode** (shows a checkmark when active)
- Settings → **AI Cleanup** → Safe Mode toggle
- The HUD shows `Safe Mode On` when active

Use Safe Mode when you want to dictate code, technical terms, or anything where the AI cleanup might interfere.

---

## Hey Jarvis Wake Word

> ⚠️ **Experimental.** The wake word is **OFF by default** on Intel Macs. Enable only if your Mac is stable with it.

The wake word lets you start dictation completely hands-free by saying **"Hey Jarvis"**.

### How it works

1. Enable from the menu bar → **Wake Word** or Settings → **Jarvis**.
2. Say "Hey Jarvis" — the HUD turns red and recording begins automatically.
3. Speak your dictation naturally.
4. Jarvis waits for a natural pause before stopping — it does not cut you off like a push-to-talk hotkey.
5. After the silence threshold is met, recording stops and transcription begins.

### Wake dictation timing

| Setting | Default | Effect |
|---|---|---|
| **Grace seconds** | 3.5 s | Minimum recording time — prevents cutting off the start of speech |
| **Silence seconds** | 4.5 s | How long silence must last before auto-stop |
| **Max seconds** | 45 s | Hard cap — recording always stops after this |

Adjust in Settings → **Jarvis** → Wake Dictation Timing. Increase Silence seconds if Jarvis stops before you finish speaking.

### Wake word model

Powered by [OpenWakeWord](https://github.com/dscripka/openWakeWord) running an ONNX model locally. No audio is sent anywhere.

---

## Cloud Transcription

By default all transcription is local. You can optionally enable OpenAI Whisper API transcription.

### Enabling cloud mode

1. Get an OpenAI API key from [https://platform.openai.com](https://platform.openai.com).
2. Settings → **Cloud** → enable **Cloud mode** and paste your API key.
3. Click **Save changes**.

When cloud mode is on, audio is sent to the OpenAI Whisper API. If the API call fails, the app automatically falls back to local Whisper — you never get a blank result.

**Privacy:** the API key is stored in the macOS Keychain, not in the settings file.

---

## Menu Bar Reference

Click the Jarvis Dictation icon in the menu bar to access all controls.

| Item | Function |
|---|---|
| **Status: Idle / Recording…** | Shows current recording state |
| **Start Dictation** | Starts recording (same as pressing the record key) |
| **Cancel Recording** | Discards the current recording without transcribing |
| ─── | |
| **Hide HUD / Show HUD** | Toggles the floating HUD |
| **Safe Mode** ✓ | Toggles Safe Mode on/off |
| **Wake Word** ✓ | Toggles "Hey Jarvis" wake word on/off |
| **Jarvis Commands** ✓ | Toggles Jarvis voice commands on/off |
| ─── | |
| **Whisper Model** ▶ | Submenu — switch between tiny.en, base.en, small.en, medium.en, large-v2, large-v3, distil variants |
| **Record Key** ▶ | Submenu — switch between Right Option, F13, F14, F15 |
| **Correction Strength** ▶ | Submenu — Off, Light, Standard, Strong |
| **Writing Profile** ▶ | Submenu — General, Professional, Email, Developer, Medical, Legal, Sales, Notes, Creative, Verbatim |
| ─── | |
| **Settings** | Opens the Settings panel |
| **History** | Opens the Dictation History window |
| **Snippets** | Opens the Snippets panel |
| ─── | |
| **Launch at Login** ✓ | Adds/removes Jarvis Dictation from macOS Login Items |
| **About Jarvis Dictation** | Version and info |
| **Quit Jarvis Dictation** | Exits the app cleanly |

---

## Settings Panel — All Pages

Open Settings from the menu bar or with the shortcut **Ctrl+,**.

---

### Setup

First-run guidance. Recommended steps:

1. Confirm your record key (Right Option + toggle mode is the stable default).
2. Confirm your microphone on the Audio page.
3. Keep the simple defaults: small.en, local Whisper, Ollama, Jarvis enabled, Cloud mode off.
4. Try one short dictation to verify the setup.
5. Click **Mark setup complete**.

---

### Dictation

| Setting | Default | Description |
|---|---|---|
| **Record hotkey** | Right Option | The global key that starts/stops recording |
| **Toggle mode** | On | Press once to start, press again to stop |
| **Show HUD** | On | Show the floating status bar during dictation |
| **Start / stop sounds** | On | Play a short sound when recording starts and stops |
| **Helpful HUD tips** | On | Show friendly guidance in the HUD instead of technical status |

**Reset to recommended defaults** — restores all Dictation settings to factory values.

---

### Audio

| Setting | Default | Description |
|---|---|---|
| **Microphone** | System default | Choose which audio input device to use |
| **Whisper model** | small.en | The transcription model to use |
| **Auto-detect language** | On | Let Whisper identify the spoken language automatically |

> Microphone and model changes are most reliable after restarting the app.

---

### AI Cleanup

The AI Cleanup page shows a live status card so you always know whether Local AI Cleanup is ready, and what to do if it isn't.

| Status | Meaning |
|---|---|
| **✓ Local AI Cleanup ready** | Ollama is running and the recommended model is installed |
| **⚠ Ollama not installed** | Download from ollama.com |
| **⚠ Ollama installed but not running** | Start Ollama from Applications |
| **⚠ Recommended model not installed** | Click "Install Recommended Model" |

**Buttons:**

| Button | Action |
|---|---|
| **Check Again** | Re-probe Ollama status |
| **Open Ollama Download Page** | Opens ollama.com/download |
| **Install Recommended Model** | Runs `ollama pull qwen2.5:3b` after you click |
| **Test Cleanup** | Sends a sample phrase through Ollama and shows the result |
| **Disable AI Cleanup** | Turns off Local AI Cleanup immediately |

**Settings:**

| Setting | Default | Description |
|---|---|---|
| **Local AI Cleanup mode** | auto | auto / on / off — controls when cleanup is attempted |
| **Correction strength** | Standard | How aggressively the model rewrites the text |
| **Safe Mode** | Off | Disables all AI cleanup and Jarvis commands |
| **Context-aware formatting** | On | Adjusts tone based on the active app |

---

### Writing Profiles

| Setting | Default | Description |
|---|---|---|
| **Default profile** | General | The profile used when auto-detection does not apply |
| **Auto-detect profile by app** | On | Automatically switch profile based on which app is active |
| **Show active profile** | On | Log the profile in History and display it in the HUD |

---

### Jarvis

| Setting | Default | Description |
|---|---|---|
| **Wake word** | Off | Enable "Hey Jarvis" hands-free recording |
| **Jarvis commands** | On | Enable voice commands for apps, media, and system control |
| **Wake dictation — Grace** | 3.5 s | Minimum recording time before auto-stop is allowed |
| **Wake dictation — Silence** | 4.5 s | Sustained quiet required before auto-stop |
| **Wake dictation — Max** | 45 s | Hard cap on wake dictation length |

---

### Custom Commands

Build your own voice commands:

- **Trigger phrase** — what you say (minimum two words)
- **Action** — Open URL / Open App / Type Text
- **Target** — the URL, app name, or text to type

Custom commands run before all built-in Jarvis commands.

---

### Vocabulary

A text box for custom words and names that Whisper should recognise. Separate with commas or new lines. Click **Save changes** to apply.

The app also learns vocabulary automatically from your dictation history.

---

### Cloud

| Setting | Default | Description |
|---|---|---|
| **Cloud mode** | Off | Send audio to OpenAI Whisper API instead of local Whisper |
| **OpenAI API key** | Empty | Your OpenAI key (stored in macOS Keychain) |

Cloud mode falls back to local Whisper automatically if the API call fails.

---

### Help

- Quick start instructions
- Explanation of HUD states
- Dictation tips
- **Copy setup summary** — copies a full technical summary of your current settings to the clipboard (useful for troubleshooting or bug reports)

---

## Privacy & Security

| Topic | Detail |
|---|---|
| **Local by default** | All transcription runs on your Mac using Whisper. No audio or text is sent anywhere unless you enable Cloud mode. |
| **No telemetry** | The app contains no analytics, crash reporting, or usage tracking of any kind. |
| **OpenAI key** | Stored in the macOS Keychain when possible. Falls back to the settings file only if Keychain access fails. |
| **AppleScript injection prevention** | All strings passed to AppleScript are escaped to prevent injection. |
| **Settings file** | Stored at `~/.dictation_settings.json`. Contains no sensitive data when Cloud mode is off. |
| **History file** | Stored at `~/.dictation_history.json`. Kept locally. Delete it at any time to clear your history. |
| **Snippets file** | Stored at `~/.dictation_snippets.json`. Local only. |

---

## Building the App from Source

To build a standalone `.app` bundle (no Python or conda required to run):

```bash
conda activate dictation
pip install pyinstaller
cd packaging/mac
chmod +x build_mac_app.sh
./build_mac_app.sh
```

The built app is placed at `packaging/mac/dist/Jarvis Dictation.app`.

After building, copy to Applications:

```bash
cp -R "packaging/mac/dist/Jarvis Dictation.app" /Applications/
```

Then grant Microphone, Accessibility, and Input Monitoring permissions to **Jarvis Dictation** in System Settings → Privacy & Security.

---

## Troubleshooting

### Nothing is typed after recording

- Check that **Accessibility** permission is granted to Jarvis Dictation in System Settings.
- If it was just granted, restart the app.

### Microphone is not working

- Check that **Microphone** permission is granted to Jarvis Dictation.
- Go to Settings → **Audio** and select the correct input device.
- Restart the app after changing the microphone device.

### Hotkey does not trigger recording

- Check that **Input Monitoring** permission is granted.
- Make sure no other app is capturing the same key globally.
- Try switching to F13/F14/F15 from Settings → **Dictation**.

### Text is cut off or first word is missing

- Switch from Hold mode to **Toggle mode** — press once to start, then speak.
- Wait a moment after pressing the key before speaking.
- Increase the minimum recording time in Settings if available.

### Old clipboard content is being pasted

- This was a known bug fixed in v6.1.40. Make sure you are running the latest version.
- If `restore_clipboard_after_paste` was manually enabled in the settings file, set it to `false`.

### Ollama is not cleaning up text

- Make sure Ollama is installed and running: `ollama serve`
- Make sure a model is downloaded: `ollama pull llama3`
- Check Settings → **AI Cleanup** → Enable Ollama is on.
- Ollama is skipped for very short phrases — this is expected.

### App crashes when using Hey Jarvis

- The wake word is experimental on Intel Macs. Disable it from the menu bar → **Wake Word**.
- This is a known hardware limitation — see the Intel crash analysis in `docs/intel-crash-analysis.md`.

### Recording seems stuck

- Release the hotkey, wait a second, then try again.
- If the issue persists, click **Quit Jarvis Dictation** in the menu bar and relaunch.

### Getting a support summary

Settings → **Help** → **Copy setup summary** — paste this when reporting a bug.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for full version history.

## License

MIT License — see [LICENSE](LICENSE).
