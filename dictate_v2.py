#!/usr/bin/env python
"""
Local Whisper Dictation v2 - Intel Mac
Hold Right Command to record, release to transcribe and type.
100% offline. No API keys. No cloud.
"""

import threading
import tempfile
import os
import sys
import time
import wave
import subprocess
import json
import re

try:
    import sounddevice as sd
    import numpy as np
    from pynput import keyboard
    from pynput.keyboard import Controller, Key
    from faster_whisper import WhisperModel
except ImportError as e:
    print(f"\nMissing dependency: {e}")
    sys.exit(1)

import os
os.environ["OMP_NUM_THREADS"] = "1"       # suppress OMP fork warning

import tkinter as tk
from tkinter import ttk

# ── Ollama AI Brain ──────────────────────────────────────────────────────────
import urllib.request as _urllib

OLLAMA_MODEL   = "llama3"
OLLAMA_URL     = "http://localhost:11434/api/generate"
JARVIS_ENABLED = True  # overridden by settings on load

# App context formatting rules
APP_FORMAT_RULES = {
    "mail":        "formal email tone, proper punctuation, capitalize first word",
    "messages":    "casual conversational tone, short sentences",
    "slack":       "casual professional tone, short sentences",
    "notes":       "clear concise notes format",
    "code":        "technical precise language",
    "terminal":    "command or technical text only",
    "word":        "formal document style with proper punctuation",
    "pages":       "formal document style with proper punctuation",
    "claude":      "conversational natural tone",
    "chrome":      "natural conversational text",
    "safari":      "natural conversational text",
}

# Jarvis command patterns mapped to actions
JARVIS_COMMANDS = {
    "open":        "open_app",
    "search":      "web_search",
    "email":       "send_email",
    "volume":      "set_volume",
    "screenshot":  "take_screenshot",
    "remind":      "set_reminder",
    "calendar":    "check_calendar",
    "close":       "close_app",
    "play":        "play_media",
    "weather":     "check_weather",
}

def ollama_query(prompt, system="You are a helpful assistant.", timeout=8):
    """Send a query to local Ollama and return response."""
    try:
        import json
        payload = json.dumps({
            "model":  OLLAMA_MODEL,
            "prompt": prompt,
            "system": system,
            "stream": False,
        }).encode()
        req = _urllib.Request(
            OLLAMA_URL, data=payload,
            headers={"Content-Type": "application/json"}
        )
        with _urllib.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()).get("response", "").strip()
    except Exception as e:
        print(f"[ollama] error: {e}")
        return None

def detect_jarvis_intent(text):
    """Use Ollama to detect if text is a Jarvis command and extract intent."""
    system = """You are an intent detector for a voice assistant on macOS.
Analyze the text and respond with JSON only, no explanation.
Format: {"is_command": true/false, "action": "action_name", "params": {}}

Actions available:
- open_app: open an application {"app": "app_name"}
- web_search: search the web {"query": "search query", "browser": "chrome"}
- send_email: compose email {"to": "name/email", "subject": "", "body": ""}
- set_volume: change volume {"level": 0-100, "direction": "up/down/mute"}
- take_screenshot: take screenshot {"type": "screen/window/selection"}
- set_reminder: create reminder {"text": "", "time": ""}
- check_calendar: check calendar {"when": "today/tomorrow/this week"}
- close_app: close application {"app": "app_name"}
- play_media: play media {"query": "", "service": "youtube/spotify/apple music"}
- check_weather: check weather {"location": ""}
- none: not a command

Examples:
"open YouTube" -> {"is_command": true, "action": "open_app", "params": {"app": "YouTube", "url": "youtube.com"}}
"search for Python tutorials" -> {"is_command": true, "action": "web_search", "params": {"query": "Python tutorials"}}
"turn volume up" -> {"is_command": true, "action": "set_volume", "params": {"direction": "up"}}
"what is the weather today" -> {"is_command": true, "action": "check_weather", "params": {"location": ""}}
"testing one two three" -> {"is_command": false, "action": "none", "params": {}}
"""
    response = ollama_query(text, system=system, timeout=5)
    if not response:
        return None
    try:
        import json, re
        # Extract JSON from response
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f"[intent] parse error: {e}")
    return None

def format_for_app(text, app_name):
    """Apply context-aware formatting based on active app."""
    app_lower = app_name.lower()
    rule = None
    for app_key, fmt_rule in APP_FORMAT_RULES.items():
        if app_key in app_lower:
            rule = fmt_rule
            break
    if not rule:
        return text

    prompt = f"""Format this dictated text for use in {app_name}.
Rule: {rule}
Text: {text}
Return ONLY the formatted text, nothing else."""

    formatted = ollama_query(prompt, timeout=5)
    if formatted:
        print(f"[format] {app_name}: {text!r} -> {formatted!r}")
        return formatted
    return text

def execute_jarvis_command(action, params):
    """Execute a detected Jarvis command via AppleScript/shell."""
    global _last_jarvis_time
    # Debounce — prevent multiple executions within 3 seconds
    if time.time() - _last_jarvis_time < 3.0:
        print(f"[jarvis] debounced")
        return
    _last_jarvis_time = time.time()

    print(f"[jarvis] executing: {action} {params}")
    app.show_message(f"Jarvis: {action.replace('_', ' ')}...", "#0a84ff")

    try:
        if action == "open_app":
            app_name = params.get("app", "")
            url      = params.get("url", "")
            if url:
                subprocess.Popen(["open", url])
            else:
                result = subprocess.run(["open", "-a", app_name],
                                       capture_output=True, text=True)
                if result.returncode != 0:
                    # Try without -a flag
                    subprocess.Popen(["open", "-a", app_name.lower()])
            app.show_message(f"Opening {app_name}", "#30d158")

        elif action == "web_search":
            query   = params.get("query", "")
            browser = params.get("browser", "")
            url     = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            subprocess.Popen(["open", url])
            app.show_message(f"Searching: {query[:30]}", "#30d158")

        elif action == "set_volume":
            direction = params.get("direction", "")
            level     = params.get("level", None)
            if direction == "up":
                subprocess.run(["osascript", "-e", "set volume output volume (output volume of (get volume settings) + 25)"])
                app.show_message("Volume up", "#30d158")
            elif direction == "down":
                subprocess.run(["osascript", "-e", "set volume output volume (output volume of (get volume settings) - 25)"])
                app.show_message("Volume down", "#30d158")
            elif direction == "mute":
                subprocess.run(["osascript", "-e", "set volume with output muted"])
                app.show_message("Muted", "#30d158")
            elif level is not None:
                subprocess.run(["osascript", "-e", f"set volume output volume {level}"])
                app.show_message(f"Volume: {level}%", "#30d158")

        elif action == "take_screenshot":
            subprocess.Popen(["screencapture", "-i", os.path.expanduser("~/Desktop/screenshot.png")])
            app.show_message("Screenshot saved to Desktop", "#30d158")

        elif action == "check_weather":
            location = params.get("location", "")
            query    = f"weather {location}" if location else "weather today"
            url      = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            subprocess.Popen(["open", url])
            app.show_message("Opening weather", "#30d158")

        elif action == "check_calendar":
            subprocess.Popen(["open", "-a", "Calendar"])
            app.show_message("Opening Calendar", "#30d158")

        elif action == "set_reminder":
            text     = params.get("text", "")
            reminder = f'tell application "Reminders" to make new reminder with properties {{name:"{text}"}}'
            subprocess.run(["osascript", "-e", reminder])
            app.show_message(f"Reminder: {text[:30]}", "#30d158")

        elif action == "send_email":
            to      = params.get("to", "")
            subject = params.get("subject", "")
            body    = params.get("body", "")
            # Open Spark directly with compose window via AppleScript
            script = f"""
tell application "Spark" to activate
delay 0.5
tell application "System Events"
    tell process "Spark"
        keystroke "n" using command down
        delay 0.5
        keystroke "{to}"
        keystroke tab
        keystroke "{subject}"
        keystroke tab
        keystroke "{body}"
    end tell
end tell
"""
            subprocess.Popen(["osascript", "-e", script])
            msg = f"Composing email to {to[:20]}" if to else "Opening Spark"
            app.show_message(msg, "#30d158")

        elif action == "close_app":
            app_name = params.get("app", "")
            subprocess.run(["osascript", "-e", f'tell application "{app_name}" to quit'])
            app.show_message(f"Closing {app_name}", "#30d158")

        elif action == "play_media":
            query   = params.get("query", "")
            service = params.get("service", "youtube")
            if "youtube" in service:
                url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
            elif "spotify" in service:
                url = f"https://open.spotify.com/search/{query.replace(' ', '%20')}"
            else:
                url = f"https://music.apple.com/search?term={query.replace(' ', '+')}"
            subprocess.Popen(["open", url])
            app.show_message(f"Playing: {query[:30]}", "#30d158")

    except Exception as e:
        print(f"[jarvis] error: {e}")
        app.show_message(f"Jarvis error: {str(e)[:30]}", "#ff3b30")

# ── Symspell ──────────────────────────────────────────────────────────────────
try:
    from symspellpy import SymSpell, Verbosity
    _sym = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
    _DICT = os.path.expanduser(
        "~/miniconda3/lib/python3.11/site-packages/symspellpy/frequency_dictionary_en_82_765.txt"
    )
    USE_SYMSPELL = os.path.exists(_DICT) and _sym.load_dictionary(_DICT, term_index=0, count_index=1)
    print(f"[symspell] {'loaded OK' if USE_SYMSPELL else 'dictionary not found'}")
except ImportError:
    USE_SYMSPELL = False

WORD_TO_NUM = {
    "zero":"0","one":"1","two":"2","three":"3","four":"4",
    "five":"5","six":"6","seven":"7","eight":"8","nine":"9",
    "ten":"10","eleven":"11","twelve":"12","thirteen":"13",
    "fourteen":"14","fifteen":"15","sixteen":"16","seventeen":"17",
    "eighteen":"18","nineteen":"19","twenty":"20","thirty":"30",
    "forty":"40","fifty":"50","sixty":"60","seventy":"70",
    "eighty":"80","ninety":"90","hundred":"100","thousand":"1000",
}

def words_to_digits(text):
    def replace(m):
        return WORD_TO_NUM.get(m.group(0).lower(), m.group(0))
    pattern = r'\b(' + '|'.join(WORD_TO_NUM.keys()) + r')\b'
    return re.sub(pattern, replace, text, flags=re.IGNORECASE)

def transcribe_cloud(wav_path):
    """Transcribe using OpenAI Whisper API — fast, accurate, requires internet."""
    try:
        import urllib.request
        api_key = settings.get("openai_key", "")
        if not api_key:
            print("[cloud] no API key set")
            return None

        with open(wav_path, "rb") as f:
            audio_data = f.read()

        import urllib.request, json
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        part1 = ("--" + boundary + "\r\n" +
            'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n' +
            "Content-Type: audio/wav\r\n\r\n").encode()
        part2 = ("\r\n--" + boundary + "\r\n" +
            'Content-Disposition: form-data; name="model"\r\n\r\n' +
            "whisper-1\r\n--" + boundary + "--\r\n").encode()
        body = part1 + audio_data + part2

        req = urllib.request.Request(
            "https://api.openai.com/v1/audio/transcriptions",
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            }
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
            return result.get("text", "").strip()
    except Exception as e:
        print(f"[cloud] error: {e}")
        return None


def symspell_correct(text):
    if not USE_SYMSPELL:
        return text
    words = text.split()
    corrected = []
    for word in words:
        m = re.match(r"([a-zA-Z']+)([.,!?;:]*)$", word)
        if m:
            core, punct = m.group(1), m.group(2)
            suggestions = _sym.lookup(core.lower(), Verbosity.CLOSEST, max_edit_distance=2)
            if suggestions:
                s = suggestions[0].term
                if core[0].isupper():
                    s = s.capitalize()
                corrected.append(s + punct)
            else:
                corrected.append(word)
        else:
            corrected.append(word)
    return " ".join(corrected)

# ── Settings ──────────────────────────────────────────────────────────────────
SETTINGS_FILE = os.path.expanduser("~/.dictation_settings.json")
DEFAULT_SETTINGS = {
    "model":        "small.en",
    "mic_device":   2,
    "sample_rate":  48000,
    "hotkey_label": "Right Command",
    "show_hud":     True,
    "toggle_mode":  False,
    "cloud_mode":   False,
    "openai_key":   "",
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE) as f:
                s = json.load(f)
                for k, v in DEFAULT_SETTINGS.items():
                    s.setdefault(k, v)
                return s
        except Exception:
            pass
    return dict(DEFAULT_SETTINGS)

def save_settings(s):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(s, f, indent=2)

settings = load_settings()

HOTKEY_OPTIONS = {
    "Right Command": Key.cmd_r,
    "Right Option":  Key.alt_r,
    "Right Control": Key.ctrl_r,
    "F13":           Key.f13,
    "F14":           Key.f14,
    "F15":           Key.f15,
}

def get_record_key():
    return HOTKEY_OPTIONS.get(settings.get("hotkey_label", "Right Command"), Key.cmd_r)

# ── Languages ────────────────────────────────────────────────────────────────
LANGUAGES = {
    "English":     "en",
    "Spanish":     "es",
    "French":      "fr",
    "German":      "de",
    "Italian":     "it",
    "Portuguese":  "pt",
    "Dutch":       "nl",
    "Russian":     "ru",
    "Japanese":    "ja",
    "Chinese":     "zh",
    "Korean":      "ko",
    "Arabic":      "ar",
    "Hindi":       "hi",
    "Auto-detect": None,
}
current_language = "en"

# ── Config ────────────────────────────────────────────────────────────────────
MODEL       = settings["model"]
DEVICE      = "cpu"
COMPUTE     = "int8"
SAMPLE_RATE = 48000
CHANNELS    = 1
MIC_DEVICE  = 2

# ── Wake word config ─────────────────────────────────────────────────────────
WAKE_WORD         = "hey cryptic"
WAKE_ENABLED      = True
WAKE_CHUNK_SECS   = 2.5    # seconds of audio to check for wake word
WAKE_THRESHOLD    = 0.003  # min RMS to bother transcribing wake chunk
WAKE_MODEL_SIZE   = "tiny.en"  # fast model just for wake detection

# ── Globals ───────────────────────────────────────────────────────────────────
recording       = False
audio_frames    = []
last_text       = ""
typer           = Controller()
whisper         = None
app             = None
current_keys    = set()
cancelled       = False
snippet_state   = None  # None | 'waiting_trigger' | 'waiting_content'
snippet_trigger = ""
# History for undo/redo and re-insert
dictation_history    = []
history_index        = -1
last_transcribed_text = ""

# Jarvis debounce
_last_jarvis_time = 0.0

# Wake word state
wake_listening    = False   # True when idle and listening for wake word
wake_frames       = []      # rolling buffer for wake detection
wake_lock         = threading.Lock()
wake_whisper      = None    # separate tiny model for fast wake detection



# ── Snippets ─────────────────────────────────────────────────────────────────
SNIPPETS_FILE = os.path.expanduser("~/.dictation_snippets.json")

def load_snippets():
    if os.path.exists(SNIPPETS_FILE):
        try:
            with open(SNIPPETS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def apply_snippets(text):
    snippets = load_snippets()
    lower = text.strip().lower().rstrip(".,!?")
    for trigger, expansion in snippets.items():
        if lower == trigger.lower():
            return expansion
    return text

# ── History ───────────────────────────────────────────────────────────────────
HISTORY_FILE = os.path.expanduser("~/.dictation_history.json")

def save_history(text, app_name):
    try:
        history = []
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE) as f:
                history = json.load(f)
        history.append({
            "text":      text,
            "app":       app_name,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "model":     settings.get("model", "unknown"),
        })
        history = history[-500:]
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"[history] save error: {e}")

# ── Personal Vocabulary Learning ─────────────────────────────────────────────
VOCAB_FILE = os.path.expanduser("~/.dictation_vocabulary.json")
STOPWORDS  = {
    "the","a","an","and","or","but","in","on","at","to","for","of","with",
    "is","it","i","you","we","he","she","they","this","that","was","are",
    "be","been","have","has","had","do","did","will","would","could","should",
    "not","no","so","if","as","by","up","out","about","just","like","from",
    "what","when","where","how","why","who","my","your","its","our","their",
    "testing","one","two","three","four","five","okay","yes","no",
}

def load_vocab():
    if os.path.exists(VOCAB_FILE):
        try:
            with open(VOCAB_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"word_counts": {}, "total_dictations": 0, "phrases": {}}

def save_vocab(vocab):
    try:
        with open(VOCAB_FILE, "w") as f:
            json.dump(vocab, f, indent=2)
    except Exception:
        pass

def learn_from_text(text):
    """Extract and save vocabulary from a dictation."""
    try:
        vocab = load_vocab()
        vocab["total_dictations"] = vocab.get("total_dictations", 0) + 1
        words = re.findall(r"[a-zA-Z']+", text.lower())
        for word in words:
            if len(word) > 3 and word not in STOPWORDS:
                vocab["word_counts"][word] = vocab["word_counts"].get(word, 0) + 1
        # Track 2-word phrases
        for i in range(len(words) - 1):
            phrase = words[i] + " " + words[i+1]
            if not any(w in STOPWORDS for w in [words[i], words[i+1]]):
                vocab["phrases"][phrase] = vocab["phrases"].get(phrase, 0) + 1
        save_vocab(vocab)
    except Exception as e:
        print(f"[vocab] error: {e}")

def get_personal_prompt():
    """Build a personal initial_prompt from learned vocabulary."""
    try:
        vocab = load_vocab()
        total = vocab.get("total_dictations", 0)
        if total < 5:
            return None  # not enough data yet

        # Top 20 most used personal words
        word_counts = vocab.get("word_counts", {})
        top_words   = sorted(word_counts, key=word_counts.get, reverse=True)[:20]

        # Top 5 phrases
        phrases     = vocab.get("phrases", {})
        top_phrases = sorted(phrases, key=phrases.get, reverse=True)[:5]

        prompt = "Transcribe spoken English accurately."
        if top_words:
            prompt += f" Common words: {', '.join(top_words)}."
        if top_phrases:
            prompt += f" Common phrases: {', '.join(top_phrases)}."
        print(f"[vocab] prompt from {total} dictations: {prompt[:80]}...")
        return prompt
    except Exception:
        return None

# ── Active app ────────────────────────────────────────────────────────────────
def get_active_app_name():
    try:
        script = 'tell application "System Events" to get name of first application process whose frontmost is true'
        return subprocess.check_output(["osascript", "-e", script], timeout=1).decode().strip()
    except Exception:
        return ""

def get_active_app_icon():
    try:
        from AppKit import NSWorkspace
        from PIL import Image, ImageTk
        import io
        ws  = NSWorkspace.sharedWorkspace()
        app = ws.frontmostApplication()
        if not app:
            return None
        bundle_url = app.bundleURL()
        if not bundle_url:
            return None
        path = bundle_url.path()
        if not path:
            return None
        icon = ws.iconForFile_(path)
        if not icon:
            return None
        icon.setSize_((48, 48))
        tiff = icon.TIFFRepresentation()
        if not tiff:
            return None
        data = bytes(tiff)
        img  = Image.open(io.BytesIO(data)).convert("RGBA")
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
        img = img.resize((32, 32), Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception as e:
        print(f"[icon] error: {e}")
        return None

# ── Audio ─────────────────────────────────────────────────────────────────────
def play_sound(name):
    sounds = {
        "start": "/System/Library/Sounds/Tink.aiff",
        "stop":  "/System/Library/Sounds/Pop.aiff",
    }
    subprocess.Popen(["afplay", sounds[name]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def _set_system_mute(mute: bool):
    try:
        flag = "with" if mute else "without"
        subprocess.run(["osascript", "-e", f"set volume {flag} output muted"], timeout=3)
    except Exception:
        pass

_pre_recording_muted = False
_apps_were_playing   = []

def pause_media():
    """Mute system audio and pause only media apps that were actually playing."""
    global _pre_recording_muted, _apps_were_playing
    _apps_were_playing = []
    try:
        result = subprocess.check_output(
            ["osascript", "-e", "output muted of (get volume settings)"], timeout=3
        ).decode().strip()
        _pre_recording_muted = (result == "true")
        if not _pre_recording_muted:
            _set_system_mute(True)
            print("[media] system muted")
    except Exception as e:
        print(f"[media] mute error: {e}")
    for app_name, state_cmd, pause_cmd in [
        ("Spotify",  'tell application "Spotify" to player state as string',  'tell application "Spotify" to pause'),
        ("Music",    'tell application "Music" to player state as string',    'tell application "Music" to pause'),
        ("Podcasts", 'tell application "Podcasts" to player state as string', 'tell application "Podcasts" to pause'),
    ]:
        try:
            check = f'tell application "System Events" to exists process "{app_name}"'
            exists = subprocess.check_output(["osascript", "-e", check], timeout=1).decode().strip()
            if exists == "true":
                state = subprocess.check_output(["osascript", "-e", state_cmd], timeout=1).decode().strip()
                if state.lower() in ("playing", "1"):
                    subprocess.Popen(["osascript", "-e", pause_cmd])
                    _apps_were_playing.append(app_name)
                    print(f"[media] paused {app_name}")
        except Exception:
            pass


def resume_media():
    """Unmute system and resume only apps that were playing before recording."""
    global _pre_recording_muted, _apps_were_playing
    if not _pre_recording_muted:
        _set_system_mute(False)
        print("[media] system unmuted")
    resume_cmds = {
        "Spotify":  'tell application "Spotify" to play',
        "Music":    'tell application "Music" to play',
        "Podcasts": 'tell application "Podcasts" to resume',
    }
    for app_name in _apps_were_playing:
        try:
            subprocess.Popen(["osascript", "-e", resume_cmds[app_name]])
            print(f"[media] resumed {app_name}")
        except Exception:
            pass
    _apps_were_playing = []


def get_current_rms():
    if not audio_frames:
        return 0.0
    return float(np.sqrt(np.mean(audio_frames[-1]**2)))

def audio_callback(indata, frames, time_info, status):
    if recording:
        audio_frames.append(indata.copy())
    elif WAKE_ENABLED and not recording and not cancelled:
        with wake_lock:
            wake_frames.append(indata.copy())

def save_wav(frames, path):
    audio = np.concatenate(frames, axis=0)
    target_rate = 16000
    target_len  = int(len(audio) * target_rate / SAMPLE_RATE)
    resampled   = np.interp(
        np.linspace(0, len(audio)-1, target_len),
        np.arange(len(audio)),
        audio[:, 0]
    ).astype(np.float32)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(target_rate)
        wf.writeframes((resampled * 32767).astype(np.int16).tobytes())

def paste_text(text):
    """Paste using a single AppleScript call - fast and reliable."""
    try:
        clean    = (text + " ").replace("\\", "\\\\").replace('"', '\\"')
        # Single AppleScript: save clipboard, paste, restore — all in one call
        script = f"""
set prevClip to the clipboard
set the clipboard to "{clean}"
tell application "System Events" to keystroke "v" using command down
delay 0.05
set the clipboard to prevClip
"""
        subprocess.Popen(["osascript", "-e", script])
    except Exception as e:
        print(f"[paste] error: {e}")
        typer.type(text + " ")

def smart_punctuate(text):
    """Detect questions and ensure proper end punctuation."""
    if not text:
        return text
    # Already has end punctuation
    if text.rstrip()[-1] in ".!?":
        return text
    # Question words at start
    question_starters = (
        "what", "when", "where", "who", "why", "how", "which", "whose",
        "is ", "are ", "was ", "were ", "will ", "would ", "could ", "should ",
        "do ", "does ", "did ", "have ", "has ", "had ", "can ", "may ",
        "might ", "shall ", "am ", "isn't", "aren't", "wasn't", "weren't",
        "don't", "doesn't", "didn't", "won't", "wouldn't", "couldn't",
    )
    lower = text.lower().strip()
    if any(lower.startswith(q) for q in question_starters):
        return text.rstrip() + "?"
    # Add period if no punctuation
    return text.rstrip() + "."


def _fast_jarvis_match(lower):
    """Fast keyword-based command matching — no AI needed."""
    import re

    # Open app/website
    open_match = re.match(r"^open (.+)$", lower)
    if open_match:
        target = open_match.group(1).strip()
        websites = {
            "youtube": "https://www.youtube.com",
            "google": "https://www.google.com",
            "gmail": "https://mail.google.com",
            "twitter": "https://www.twitter.com",
            "x": "https://www.x.com",
            "instagram": "https://www.instagram.com",
            "facebook": "https://www.facebook.com",
            "linkedin": "https://www.linkedin.com",
            "github": "https://www.github.com",
            "spotify": "",  # handled by app_keywords above
            "netflix": "https://www.netflix.com",
            "amazon": "https://www.amazon.com",
            "reddit": "https://www.reddit.com",
            "claude": "https://claude.ai",
            "chatgpt": "https://chat.openai.com",
            "maps": "https://maps.google.com",
        }
        if target in websites:
            return ("open_app", {"app": target.capitalize(), "url": websites[target]})
        else:
            return ("open_app", {"app": target.capitalize(), "url": ""})

    # Email — require open/check prefix
    if any(p in lower for p in ("open email", "check email", "open spark",
                                 "check spark", "open my email", "check my email",
                                 "open inbox")):
        return ("open_app", {"app": "Spark", "url": ""})

    # Common Mac apps — check by keyword not exact phrase
    app_keywords = {
        "notes":            "Notes",
        "calendar":         "Calendar",
        "messages":         "Messages",
        "slack":            "Slack",
        "finder":           "Finder",
        "terminal":         "Terminal",
        "system settings":  "System Settings",
        "system preferences": "System Preferences",
        "music":            "Music",
        "photos":           "Photos",
        "facetime":         "FaceTime",
        "maps":             "Maps",
        "weather":          "Weather",
        "reminders":        "Reminders",
        "calculator":       "Calculator",
        "safari":           "Safari",
        "chrome":           "Google Chrome",
        "firefox":          "Firefox",
        "vs code":          "Visual Studio Code",
        "vscode":           "Visual Studio Code",
        "visual studio":    "Visual Studio Code",
        "xcode":            "Xcode",
        "textedit":         "TextEdit",
        "text edit":        "TextEdit",
        "photoshop":        "Adobe Photoshop 2025",
        "illustrator":      "Adobe Illustrator",
        "premiere":         "Adobe Premiere Pro",
        "after effects":    "Adobe After Effects",
        "lightroom":        "Adobe Lightroom",
        "figma":            "Figma",
        "sketch":           "Sketch",
        "zoom":             "Zoom",
        "teams":            "Microsoft Teams",
        "word":             "Microsoft Word",
        "excel":            "Microsoft Excel",
        "powerpoint":       "Microsoft PowerPoint",
        "outlook":          "Microsoft Outlook",
        "notion":           "Notion",
        "obsidian":         "Obsidian",
        "discord":          "Discord",
        "whatsapp":         "WhatsApp",
        "telegram":         "Telegram",
        "1password":        "1Password 7",
        "screenflow":       "ScreenFlow",
        "screencast":       "ScreenFlow",
        "quicktime":        "QuickTime Player",
        "vlc":              "VLC",
        "iterm":            "iTerm",
        "activity monitor": "Activity Monitor",
        "app store":        "App Store",
        "contacts":         "Contacts",
        "clock":            "Clock",
        "stocks":           "Stocks",
        "news":             "News",
        "podcasts":         "Podcasts",
        "books":            "Books",
        "preview":          "Preview",
        "script editor":    "Script Editor",
        "automator":        "Automator",
        "shortcuts":        "Shortcuts",
    }
    if lower.startswith("open "):
        keyword = lower[5:].strip()
        # Direct keyword match
        if keyword in app_keywords:
            return ("open_app", {"app": app_keywords[keyword], "url": ""})
        # Partial match
        for kw, app_name in app_keywords.items():
            if kw in keyword:
                return ("open_app", {"app": app_name, "url": ""})
        # Try launching whatever they said as an app name
        return ("open_app", {"app": keyword.title(), "url": ""})

    # Email compose — "send email to John saying I'll be late"
    import re as _re
    email_match = _re.match(
        r"(?:send|compose|write|draft)\s+(?:an\s+)?email\s+(?:to\s+)?(.+?)\s+(?:saying|that|about|with)\s+(.+)",
        lower
    )
    if email_match:
        to      = email_match.group(1).strip()
        body    = email_match.group(2).strip()
        return ("send_email", {"to": to, "subject": "", "body": body})

    # Simple "send email to John"
    simple_email = _re.match(r"^(?:send|compose|write)\s+(?:an\s+)?email\s+to\s+(.+)", lower)
    if simple_email:
        to = simple_email.group(1).strip()
        return ("send_email", {"to": to, "subject": "", "body": ""})

    # Web search
    for prefix in ("search for ", "search ", "google ", "look up "):
        if lower.startswith(prefix):
            query = lower[len(prefix):]
            return ("web_search", {"query": query})

    # YouTube
    for prefix in ("play ", "watch "):
        if lower.startswith(prefix):
            query = lower[len(prefix):]
            return ("play_media", {"query": query, "service": "youtube"})

    # Volume — require explicit control phrases only
    if lower in ("volume up", "turn volume up", "increase volume", "raise volume", "louder"):
        return ("set_volume", {"direction": "up"})
    if lower in ("volume down", "turn volume down", "decrease volume", "reduce volume",
                 "lower volume", "quieter"):
        return ("set_volume", {"direction": "down"})
    if lower in ("mute", "mute volume", "turn off sound", "unmute"):
        return ("set_volume", {"direction": "mute"})
    # Set exact volume "set volume to 50"
    if lower.startswith("set volume to "):
        try:
            level = min(100, max(0, int(lower.replace("set volume to ", "").strip())))
            return ("set_volume", {"direction": "", "level": level})
        except Exception:
            pass

    # Screenshot
    if any(p in lower for p in ("take a screenshot", "screenshot", "take screenshot")):
        return ("take_screenshot", {})

    # Weather
    if any(p in lower for p in ("check weather", "whats the weather", "weather today")):
        return ("check_weather", {"location": ""})

    # Calendar
    if any(p in lower for p in ("open calendar", "check calendar", "whats on my calendar")):
        return ("check_calendar", {})

    # Reminder
    remind_match = re.match(r"remind me (?:to )?(.+)", lower)
    if remind_match:
        return ("set_reminder", {"text": remind_match.group(1)})

    # Close app
    close_match = re.match(r"close (.+)", lower)
    if close_match:
        return ("close_app", {"app": close_match.group(1).capitalize()})

    return None


def transcribe_and_type(wav_path, raw_frames):
    global last_text, cancelled, snippet_state, snippet_trigger

    if cancelled:
        cancelled = False
        app.set_state("idle")
        return

    audio = np.concatenate(raw_frames, axis=0)
    rms = np.sqrt(np.mean(audio**2))
    if rms < 0.002:  # lower threshold to allow pauses
        app.set_state("idle")
        return

    app.set_state("transcribing")
    # Check RMS — skip if audio is too quiet (prevents hallucination)
    audio_check = np.concatenate(raw_frames, axis=0)
    rms_check = float(np.sqrt(np.mean(audio_check**2)))
    if rms_check < 0.008:
        print(f"[transcribe] skipping — audio too quiet (rms={rms_check:.4f})")
        app.set_state("idle")
        return

    # Cloud mode — use OpenAI Whisper API
    if settings.get("cloud_mode") and settings.get("openai_key"):
        print("[cloud] transcribing...")
        raw_text = transcribe_cloud(wav_path)
        if not raw_text:
            print("[cloud] failed, falling back to local")
            segments, _ = whisper.transcribe(wav_path, beam_size=5, language="en",
                                             condition_on_previous_text=False)
            raw_text = " ".join(seg.text for seg in segments).strip()
    else:
        segments, _ = whisper.transcribe(
            wav_path,
            beam_size=5,
            language="en",
            condition_on_previous_text=False,
        )
        raw_text = " ".join(seg.text for seg in segments).strip()
    if not raw_text:
        app.set_state("idle")
        return

    # Voice command check — strip all punctuation before matching
    lower = re.sub(r"[^a-z0-9 ]", "", raw_text.lower()).strip()
    print(f"[cmd] {lower!r}")

    # Jarvis fast command detection
    if JARVIS_ENABLED:
        # Strip "jarvis" prefix if present
        cmd_text = lower
        if lower.startswith("jarvis "):
            cmd_text = lower[7:].strip()
            print(f"[jarvis] prefix detected, command: {cmd_text!r}")
        elif lower.startswith("hey jarvis "):
            cmd_text = lower[11:].strip()
            print(f"[jarvis] prefix detected, command: {cmd_text!r}")

        jarvis_intent = _fast_jarvis_match(cmd_text)
        if jarvis_intent:
            action, params = jarvis_intent
            print(f"[jarvis] fast match: {action} {params}")
            threading.Thread(
                target=execute_jarvis_command,
                args=(action, params),
                daemon=True
            ).start()
            app.set_state("idle")
            return

    # Snippet recording flow
    if snippet_state == "waiting_trigger":
        RESERVED_CMDS = {
            "create snippet","new snippet","add snippet","make snippet",
            "scratch that","undo that","delete that","new line","new paragraph",
            "tab","indent","select all","copy that","copy last","copy all",
            "paste","paste that","period","comma","question mark"
        }
        candidate = re.sub(r"[^a-z0-9 ]", "", raw_text.lower()).strip()
        if any(p in candidate for p in ("create snippet","new snippet","add snippet","make snippet")):
            app.show_message("That's a command, not a trigger. Try again.", "#ff9f0a")
            app.set_state("idle")
            return
        snippet_trigger = candidate
        snippet_state   = "waiting_content"
        print(f"[snippet] trigger='{snippet_trigger}' — waiting for content")
        app.show_snippet_step(2, snippet_trigger)
        return
    if snippet_state == "waiting_content":
        snippets = load_snippets()
        # Fix common spoken email/URL patterns
        fixed = raw_text.strip()
        fixed = fixed.replace(' at ', '@').replace(' dot ', '.').replace(' dot', '.')
        snippets[snippet_trigger] = fixed
        with open(SNIPPETS_FILE, "w") as f:
            json.dump(snippets, f, indent=2)
        snippet_state   = None
        snippet_trigger = ""
        print(f"[snippet] saved — snippets now: {snippets}")
        app.show_snippet_step(3)
        app.set_state("idle")
        return
    if lower in ("create snippet", "new snippet", "add snippet", "make snippet", "create a snippet"):
        snippet_state = "waiting_trigger"
        print(f"[snippet] triggered — waiting for trigger word")
        app.show_snippet_step(1)
        return

    # Scratch
    if lower in ("scratch that", "undo that", "delete that", "scratch", "undo", "scratch last"):
        print(f"[scratch] triggered, last_text={last_text!r}")
        _scratch_last(1)
        app.set_state("idle")
        return
    if lower in ("scratch again", "undo again", "scratch more"):
        print(f"[scratch again] history={len(dictation_history)} index={history_index}")
        _scratch_last(1)
        app.set_state("idle")
        return
    if any(p in lower for p in ("scratch last 2", "scratch two", "scratch last two",
                                 "undo last 2", "undo two", "undo last two",
                                 "scratch last tool", "delete last 2", "delete two")):
        print(f"[scratch 2] history={len(dictation_history)} index={history_index}")
        _scratch_last(2)
        app.set_state("idle")
        return
    if any(p in lower for p in ("scratch last 3", "scratch three", "scratch last three",
                                 "undo last 3", "undo three", "undo last three",
                                 "delete last 3", "delete three")):
        print(f"[scratch 3] history={len(dictation_history)} index={history_index}")
        _scratch_last(3)
        app.set_state("idle")
        return
    if any(p in lower for p in ("scratch all", "undo all", "delete all", "clear all")):
        _scratch_last(len(dictation_history))
        app.set_state("idle")
        return

    # Punctuation commands
    PUNCT_COMMANDS = {
        "period":            ".",
        "full stop":         ".",
        "comma":             ",",
        "exclamation point": "!",
        "exclamation mark":  "!",
        "question mark":     "?",
        "colon":             ":",
        "semicolon":         ";",
        "ellipsis":          "...",
        "open paren":        "(",
        "close paren":       ")",
        "dash":              " — ",
        "hyphen":            "-",
    }
    if lower in PUNCT_COMMANDS:
        typer.type(PUNCT_COMMANDS[lower])
        app.show_message(PUNCT_COMMANDS[lower], "#0a84ff")
        app.set_state("idle")
        return

    # New line — Shift+Enter for chat apps, plain Enter elsewhere
    if lower in ("new line", "newline", "next line"):
        chat_apps = ("claude", "slack", "discord", "messages", "teams", "whatsapp", "telegram")
        active = get_active_app_name().lower()
        if any(a in active for a in chat_apps):
            typer.press(Key.shift)
            typer.press(Key.enter)
            typer.release(Key.enter)
            typer.release(Key.shift)
        else:
            typer.press(Key.enter)
            typer.release(Key.enter)
        app.show_message("New line", "#0a84ff")
        app.set_state("idle")
        return
    # New paragraph
    if lower == "new paragraph":
        for _ in range(2):
            typer.press(Key.enter); typer.release(Key.enter)
        app.show_message("New paragraph", "#0a84ff")
        app.set_state("idle")
        return
    # Tab
    if lower in ("tab", "indent"):
        typer.press(Key.tab); typer.release(Key.tab)
        app.show_message("Tab", "#0a84ff")
        app.set_state("idle")
        return
    # Select all
    if lower == "select all":
        with typer.pressed(Key.cmd):
            typer.press("a"); typer.release("a")
        app.show_message("Select all", "#0a84ff")
        app.set_state("idle")
        return
    # ── Smart Formatting ─────────────────────────────────────────────────────
    if lower in ("make bold", "bold that"):
        if last_text:
            # Delete last text and retype with bold markdown
            for _ in range(len(last_text) + 1):
                typer.press(Key.backspace); typer.release(Key.backspace)
            bold = f"**{last_text}**"
            paste_text(bold)
            last_text = bold
            app.show_message("Bolded!", "#0a84ff")
        app.set_state("idle")
        return

    if lower in ("make italic", "italic that"):
        if last_text:
            for _ in range(len(last_text) + 1):
                typer.press(Key.backspace); typer.release(Key.backspace)
            italic = f"*{last_text}*"
            paste_text(italic)
            last_text = italic
            app.show_message("Italicized!", "#0a84ff")
        app.set_state("idle")
        return

    if lower in ("format as code", "code that", "make code"):
        if last_text:
            for _ in range(len(last_text) + 1):
                typer.press(Key.backspace); typer.release(Key.backspace)
            coded = f"`{last_text}`"
            paste_text(coded)
            last_text = coded
            app.show_message("Code formatted!", "#0a84ff")
        app.set_state("idle")
        return

    if lower in ("make heading", "heading that", "make title"):
        if last_text:
            for _ in range(len(last_text) + 1):
                typer.press(Key.backspace); typer.release(Key.backspace)
            headed = f"# {last_text}"
            paste_text(headed)
            last_text = headed
            app.show_message("Heading!", "#0a84ff")
        app.set_state("idle")
        return

    if lower in ("all caps", "make caps", "capitalize that"):
        if last_text:
            for _ in range(len(last_text) + 1):
                typer.press(Key.backspace); typer.release(Key.backspace)
            capped = last_text.upper()
            paste_text(capped)
            last_text = capped
            app.show_message("ALL CAPS!", "#0a84ff")
        app.set_state("idle")
        return

    if lower in ("make bullet", "bullet that", "create list", "make list"):
        if last_text:
            for _ in range(len(last_text) + 1):
                typer.press(Key.backspace); typer.release(Key.backspace)
            # Split into sentences and bullet each
            sentences = [s.strip() for s in last_text.split('.') if s.strip()]
            bulleted  = "\n".join(f"• {s}" for s in sentences)
            paste_text(bulleted)
            last_text = bulleted
            app.show_message("Bulleted!", "#0a84ff")
        app.set_state("idle")
        return

    if lower in ("make quote", "quote that", "block quote"):
        if last_text:
            for _ in range(len(last_text) + 1):
                typer.press(Key.backspace); typer.release(Key.backspace)
            quoted = f"> {last_text}"
            paste_text(quoted)
            last_text = quoted
            app.show_message("Quoted!", "#0a84ff")
        app.set_state("idle")
        return

    if lower in ("strikethrough that", "strike that"):
        if last_text:
            for _ in range(len(last_text) + 1):
                typer.press(Key.backspace); typer.release(Key.backspace)
            struck = f"~~{last_text}~~"
            paste_text(struck)
            last_text = struck
            app.show_message("Strikethrough!", "#0a84ff")
        app.set_state("idle")
        return

    # Copy that
    if lower in ("copy that", "copy last"):
        if last_text:
            subprocess.run(["osascript", "-e", f'set the clipboard to "{last_text}"'], timeout=2)
            app.show_message("Copied!", "#0a84ff")
        else:
            app.show_message("Nothing to copy", "#ff9f0a")
        app.set_state("idle")
        return
    # Copy all
    if lower == "copy all":
        with typer.pressed(Key.cmd):
            typer.press("a"); typer.release("a")
        time.sleep(0.05)
        with typer.pressed(Key.cmd):
            typer.press("c"); typer.release("c")
        app.show_message("Copied all!", "#0a84ff")
        app.set_state("idle")
        return
    # Paste
    if lower in ("paste", "paste that"):
        with typer.pressed(Key.cmd):
            typer.press("v"); typer.release("v")
        app.show_message("Pasted!", "#0a84ff")
        app.set_state("idle")
        return

    # History commands
    if lower in ("undo dictation", "undo last"):
        _undo_last_dictation()
        app.set_state("idle")
        return
    if lower in ("redo dictation", "redo last"):
        _redo_dictation()
        app.set_state("idle")
        return
    if lower in ("re-insert last", "insert last", "paste last"):
        _reinsert_last()
        app.set_state("idle")
        return
    if lower in ("show history", "dictation history", "view history"):
        _show_history()
        app.set_state("idle")
        return

    text = symspell_correct(raw_text)
    text = words_to_digits(text)
    text = apply_snippets(text)

    last_text = text
    _add_to_history(text)
    active_app = get_active_app_name()
    current_model = settings.get("model", "unknown")
    # Save directly (not in thread) to ensure it completes
    try:
        history = []
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE) as f:
                history = json.load(f)
        history.append({
            "text":      text,
            "app":       active_app,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "model":     current_model,
        })
        history = history[-500:]
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
        print(f"[history] saved {len(history)} entries")
    except Exception as e:
        print(f"[history] error: {e}")
    learn_from_text(text)  # call directly to ensure it runs
    # Context-aware formatting
    if settings.get("context_format") and active_app:
        app.show_message("Formatting...", "#0a84ff")
        formatted = format_for_app(text, active_app)
        if formatted and formatted != text:
            text = formatted

    app.set_transcript(text)
    time.sleep(0.3)
    paste_text(text)
    threading.Thread(target=resume_media, daemon=True).start()
    time.sleep(3.0)
    app.set_state("idle")

def _scratch_last(count=1):
    """Delete the last N dictations."""
    global last_text, dictation_history, history_index
    deleted = 0
    for i in range(count):
        if history_index >= 0 and history_index < len(dictation_history):
            text_to_delete = dictation_history[history_index]
        elif i == 0 and last_text:
            text_to_delete = last_text
        else:
            break
        chars = len(text_to_delete) + 1
        print(f"[scratch] deleting {chars} chars: {text_to_delete!r}")
        for _ in range(chars):
            typer.press(Key.backspace)
            typer.release(Key.backspace)
            time.sleep(0.005)
        if history_index >= 0 and history_index < len(dictation_history):
            dictation_history.pop(history_index)
            history_index = len(dictation_history) - 1
        last_text = dictation_history[history_index] if history_index >= 0 and dictation_history else ""
        deleted += 1
    if deleted:
        msg = f"Scratched {deleted}!" if deleted > 1 else "Scratched!"
        app.show_message(msg, "#ff9f0a")
    else:
        app.show_message("Nothing to scratch", "#ff9f0a")

def _add_to_history(text):
    """Add text to in-memory dictation history for undo/redo"""
    global dictation_history, history_index
    # Truncate future if we're not at the end
    if history_index < len(dictation_history) - 1:
        dictation_history = dictation_history[:history_index + 1]
    dictation_history.append(text)
    history_index = len(dictation_history) - 1
    # Keep history manageable
    if len(dictation_history) > 50:
        dictation_history = dictation_history[-50:]
        history_index = 49

def _undo_last_dictation():
    """Undo the last dictation by deleting the text"""
    global last_text, history_index
    if last_text:
        count = len(last_text) + 1
        for _ in range(count):
            typer.press(Key.backspace)
            typer.release(Key.backspace)
        history_index = max(-1, history_index - 1)
        app.show_message("Undo!", "#0a84ff")
    else:
        app.show_message("Nothing to undo", "#ff9f0a")

def _redo_dictation():
    """Redo a previously undone dictation"""
    global history_index
    if history_index < len(dictation_history) - 1:
        history_index += 1
        text = dictation_history[history_index]
        paste_text(text)
        app.show_message("Redo!", "#0a84ff")
    else:
        app.show_message("Nothing to redo", "#ff9f0a")

def _reinsert_last():
    """Re-insert the last dictation at cursor position"""
    global last_text
    if last_text:
        paste_text(last_text)
        app.show_message("Re-inserted!", "#30d158")
    else:
        app.show_message("Nothing to re-insert", "#ff9f0a")

def _show_history():
    """Show dictation history in a popup window"""
    def _show():
        hwin = tk.Toplevel(app.root)
        hwin.title("Dictation History")
        hwin.geometry("500x400")
        hwin.configure(bg="#1a1a1a")
        hwin.attributes("-topmost", True)

        tk.Label(hwin, text="Recent Dictations", bg="#1a1a1a", fg="#ffffff",
                 font=("Helvetica Neue", 14, "bold")).pack(pady=(12, 4))

        # Scrollable list
        frame = tk.Frame(hwin, bg="#1a1a1a")
        frame.pack(fill="both", expand=True, padx=16, pady=8)

        canvas = tk.Canvas(frame, bg="#1a1a1a", highlightthickness=0)
        scroll = tk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg="#1a1a1a")

        inner.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE) as f:
                    history = json.load(f)
                for item in reversed(history[-100:]):
                    row = tk.Frame(inner, bg="#1c1c1c")
                    row.pack(fill="x", pady=2)
                    tk.Label(row, text=item["text"][:60] + ("..." if len(item["text"]) > 60 else ""),
                             bg="#2a2a2a", fg="#aaaaaa",
                             font=("Helvetica Neue", 10),
                             anchor="w", padx=8, pady=4).pack(fill="x")
                    tk.Label(row, text=f"{item['app']} • {item['timestamp']}",
                             bg="#1c1c1c", fg="#666666",
                             font=("Helvetica Neue", 8)).pack(anchor="w", padx=8, pady=2)
            else:
                tk.Label(inner, text="No history yet", bg="#1a1a1a", fg="#666666",
                         font=("Helvetica Neue", 11)).pack(pady=20)
        except Exception:
            tk.Label(inner, text="Error loading history", bg="#1a1a1a", fg="#ff3b30",
                     font=("Helvetica Neue", 11)).pack(pady=20)

        tk.Button(hwin, text="Close", command=hwin.destroy,
                  bg="#2a2a2a", fg="#aaaaaa", font=("Helvetica Neue", 12),
                  relief="flat", padx=20, pady=8, cursor="hand2").pack(pady=8)

    app.root.after(0, _show)

_wake_cooldown_until = 0.0  # module-level shared cooldown
_wake_active = threading.Event()  # set when recording, cleared when idle

def _trigger_wake():
    """Activate recording after wake word detected."""
    global recording, audio_frames, cancelled, _wake_cooldown_until
    if recording:
        return
    if time.time() < _wake_cooldown_until:
        return
    with wake_lock:
        wake_frames.clear()
    audio_frames = []
    time.sleep(0.3)
    audio_frames = []
    cancelled    = False
    recording    = True
    _wake_active.set()
    _wake_cooldown_until = time.time() + 5.0
    app.capture_active_app()
    app.set_state("recording")
    app.root.after(0, app.start_wave)
    app.root.after(100, lambda: app.canvas.itemconfig(
        app.label, text="Recording...  press ⌘ to stop", fill=app.TEXT_WHITE))
    threading.Thread(target=play_sound, args=("start",), daemon=True).start()
    threading.Thread(target=_silence_stop_monitor, daemon=True).start()


def _silence_stop_monitor():
    """Auto-stop recording after sustained silence."""
    SILENCE_THRESHOLD = 0.08   # raised above room noise floor (~0.054 avg)
    SILENCE_SECS      = 2.5
    MIN_RECORD_SECS   = 1.5
    start_time    = time.time()
    silence_since = None
    while recording:
        time.sleep(0.1)
        if time.time() - start_time < MIN_RECORD_SECS:
            silence_since = None
            continue
        if not audio_frames:
            continue
        rms = float(np.sqrt(np.mean(audio_frames[-1]**2)))
        if rms < SILENCE_THRESHOLD:
            if silence_since is None:
                silence_since = time.time()
            elif time.time() - silence_since >= SILENCE_SECS:
                print(f"[silence] auto-stop (rms={rms:.4f})")
                _stop_recording()
                return
        else:
            silence_since = None


def _wake_word_loop():
    """Wake word detection using openwakeword."""
    global recording

    try:
        from openwakeword.model import Model as WakeModel
        oww = WakeModel(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        print("[wake] ready — say 'Hey Jarvis' to start dictating")
    except Exception as e:
        print(f"[wake] openwakeword failed ({e}), wake word disabled")
        return

    CHUNK    = 1280
    OWW_RATE = 16000

    while True:  # outer restart loop for SEGV prevention
      session_start = time.time()
      while True:
        # Only run stream when NOT recording
        if recording or not WAKE_ENABLED:
            time.sleep(0.5)
            continue

        buf = []
        triggered = False

        def _oww_callback(indata, frames, time_info, status):
            nonlocal triggered
            if recording or triggered or not WAKE_ENABLED:
                return
            if time.time() < _wake_cooldown_until:
                return

            audio      = indata[:, 0]
            target_len = int(len(audio) * OWW_RATE / SAMPLE_RATE)
            resampled  = np.interp(
                np.linspace(0, len(audio)-1, target_len),
                np.arange(len(audio)), audio
            )
            buf.extend(resampled.tolist())
            while len(buf) >= CHUNK:
                chunk = np.array(buf[:CHUNK], dtype=np.float32)
                del buf[:CHUNK]
                pcm   = (chunk * 32767).astype(np.int16)
                preds = oww.predict(pcm)
                score = preds.get("hey_jarvis", 0)
                if score > 0.75:
                    print(f"[wake] Hey Jarvis! score={score:.2f}")
                    triggered = True
                    buf.clear()

        # Open stream, run until recording starts or trigger fires
        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                device=MIC_DEVICE,
                callback=_oww_callback,
            ):
                while not recording and not triggered and WAKE_ENABLED:
                    time.sleep(0.05)
        except Exception as e:
            print(f"[wake] stream error: {e}")
            time.sleep(1)
            continue

        if triggered and not recording:
            threading.Thread(target=_trigger_wake, daemon=True).start()

        # Wait until recording finishes before restarting wake listener
        while recording:
            time.sleep(0.2)

        # Reset oww model state so residual scores don't retrigger
        try:
            oww.reset()
        except Exception:
            pass

        # Cooldown — wait until _wake_cooldown_until has passed
        while time.time() < _wake_cooldown_until:
            time.sleep(0.1)

        # Reset oww prediction state
        try:
            for key in oww.prediction_buffer:
                oww.prediction_buffer[key] = [0.0] * len(oww.prediction_buffer[key])
        except Exception:
            pass

        print("[wake] listening for 'Hey Jarvis'...")



def _auto_stop_monitor():
    """Disabled — use Right Command key to stop recording."""
    pass

def _stop_recording():
    global recording, _wake_cooldown_until
    if not recording:
        return
    recording = False
    _wake_cooldown_until = time.time() + 5.0  # 12s cooldown after auto-stop
    app.root.after(0, app.stop_wave)
    app.root.after(0, lambda: app.set_state("transcribing"))
    frames = list(audio_frames)
    threading.Thread(target=play_sound, args=("stop",), daemon=True).start()
    if frames:
        threading.Thread(target=_process, args=(frames,), daemon=True).start()
    else:
        app.set_state("idle")

def _process(frames):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name
    try:
        save_wav(frames, wav_path)
        transcribe_and_type(wav_path, frames)
    finally:
        os.unlink(wav_path)

# ── Hotkey listener ───────────────────────────────────────────────────────────
def on_press(key):
    global recording, audio_frames, cancelled

    if key in current_keys:
        return
    current_keys.add(key)

    record_key = get_record_key()
    ctrl = Key.ctrl in current_keys or Key.ctrl_l in current_keys or Key.ctrl_r in current_keys
    is_z     = hasattr(key, "char") and key.char == "z"
    is_comma = hasattr(key, "char") and key.char in (",", "d")

    if key == record_key and not recording:
        recording    = True
        _wake_active.set()
        _wake_cooldown_until = time.time() + 5.0
        audio_frames = []
        cancelled    = False
        with wake_lock:
            wake_frames.clear()
        app.capture_active_app()
        app.set_state("recording")
        app.root.after(0, app.start_wave)
        threading.Thread(target=play_sound, args=("start",), daemon=True).start()
        threading.Thread(target=pause_media, daemon=True).start()
    elif key == record_key and recording and settings.get("toggle_mode", False):
        recording = False
        app.root.after(0, app.stop_wave)
        threading.Thread(target=play_sound, args=("stop",), daemon=True).start()
        frames = list(audio_frames)
        if frames:
            threading.Thread(target=_process, args=(frames,), daemon=True).start()
        else:
            app.set_state("idle")
    elif key == Key.esc:
        recording = False
        cancelled = True
        audio_frames.clear()
        app.root.after(0, app.stop_wave)
        app.show_message("Cancelled", "#ff9f0a")
        threading.Thread(target=resume_media, daemon=True).start()
        threading.Timer(1.5, lambda: app.set_state("idle")).start()
    elif ctrl and is_z:
        threading.Thread(target=_scratch_last, daemon=True).start()
    elif ctrl and is_comma:
        app.open_settings()

def on_release(key):
    global recording, _wake_cooldown_until
    current_keys.discard(key)
    if key == get_record_key() and recording and not settings.get("toggle_mode", False):
        recording = False
        _wake_active.clear()
        _wake_cooldown_until = time.time() + 5.0
        app.root.after(0, app.stop_wave)
        threading.Thread(target=play_sound, args=("stop",), daemon=True).start()
        frames = list(audio_frames)
        if frames:
            threading.Thread(target=_process, args=(frames,), daemon=True).start()
        else:
            app.set_state("idle")

# ── Menu Bar ─────────────────────────────────────────────────────────────────
class MenuBarApp:
    ICONS = {
        "idle":         "idle",
        "recording":    "recording",
        "transcribing": "transcribing",
    }
    ICON_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.argv[0])))

    def __init__(self):
        self._available = False
        try:
            from AppKit import NSStatusBar, NSVariableStatusItemLength, NSMenu, NSMenuItem, NSImage
            from Foundation import NSObject
            import objc

            class MenuDelegate(NSObject):
                def toggleHUD_(self, sender):
                    settings["show_hud"] = not settings.get("show_hud", True)
                    save_settings(settings)
                    menubar._update_hud_label()
                    if app:
                        show = settings["show_hud"]
                        threading.Thread(target=lambda: app.root.after(0, app.root.deiconify if show else app.root.withdraw), daemon=True).start()

                def openSettings_(self, sender):
                    if app:
                        threading.Thread(target=lambda: app.root.after(0, app._show_settings), daemon=True).start()

                def showSnippets_(self, sender):
                    if app:
                        threading.Thread(target=lambda: app.root.after(0, app._show_snippets), daemon=True).start()

                def selectModel_(self, sender):
                    new_model = sender.title()
                    if new_model == settings.get("model"):
                        return
                    settings["model"] = new_model
                    save_settings(settings)
                    # Update checkmarks in menu
                    for i in range(menubar._model_menu.numberOfItems()):
                        item = menubar._model_menu.itemAtIndex_(i)
                        item.setState_(1 if item.title() == new_model else 0)
                    threading.Thread(target=reload_model, daemon=True).start()

                def selectHotkey_(self, sender):
                    settings["hotkey_label"] = sender.title()
                    save_settings(settings)

                def quitApp_(self, sender):
                    os._exit(0)

                def showHistory_(self, sender):
                    if app:
                        threading.Thread(target=lambda: app.root.after(0, _show_history), daemon=True).start()

            self._delegate = MenuDelegate.alloc().init()

            bar        = NSStatusBar.systemStatusBar()
            self._item = bar.statusItemWithLength_(NSVariableStatusItemLength)
            self._NSImage = NSImage
            self._set_icon("idle")

            self._menu = NSMenu.alloc().init()

            self._status_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Status: Idle", None, "")
            self._menu.addItem_(self._status_item)
            self._menu.addItem_(NSMenuItem.separatorItem())

            self._toggle_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Hide HUD", "toggleHUD:", "")
            self._toggle_item.setTarget_(self._delegate)
            self._menu.addItem_(self._toggle_item)

            # Model submenu
            model_menu = NSMenu.alloc().init()
            model_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Model", None, "")
            for m in ["tiny.en","base.en","small.en","medium.en",
                      "large-v2","large-v3","distil-medium.en","distil-large-v3"]:
                mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(m, "selectModel:", "")
                mi.setTarget_(self._delegate)
                if m == settings.get("model"):
                    mi.setState_(1)
                model_menu.addItem_(mi)
            model_item.setSubmenu_(model_menu)
            self._menu.addItem_(model_item)
            self._model_menu = model_menu  # store reference for updates

            # Hotkey submenu
            hotkey_menu = NSMenu.alloc().init()
            hotkey_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Record Key", None, "")
            for k in ["Right Command", "Right Option", "Right Control", "F13", "F14", "F15"]:
                hi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(k, "selectHotkey:", "")
                hi.setTarget_(self._delegate)
                if k == settings.get("hotkey_label"):
                    hi.setState_(1)
                hotkey_menu.addItem_(hi)
            hotkey_item.setSubmenu_(hotkey_menu)
            self._menu.addItem_(hotkey_item)

            self._menu.addItem_(NSMenuItem.separatorItem())

            # Settings
            settings_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Settings", "openSettings:", "")
            settings_item.setTarget_(self._delegate)
            self._menu.addItem_(settings_item)

            # Snippets
            snippets_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Manage Snippets", "showSnippets:", "")
            snippets_item.setTarget_(self._delegate)
            self._menu.addItem_(snippets_item)

            # History
            hist_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Show History", "showHistory:", "")
            hist_item.setTarget_(self._delegate)
            self._menu.addItem_(hist_item)

            self._menu.addItem_(NSMenuItem.separatorItem())

            quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit", "quitApp:", "")
            quit_item.setTarget_(self._delegate)
            self._menu.addItem_(quit_item)

            self._item.setMenu_(self._menu)
            self._available = True
        except Exception as e:
            print(f"[menubar] unavailable: {e}")
            self._available = False

    def _set_icon(self, state):
        if not self._available:
            return
        # Try PNG icon first — works both from source and inside .app bundle.
        # In a bundle _MEIPASS points to Frameworks where PyInstaller copies our PNGs.
        icon_dir = getattr(sys, '_MEIPASS', self.ICON_DIR)
        path = os.path.join(icon_dir, f"icon_{state}.png")
        if os.path.exists(path):
            img = self._NSImage.alloc().initWithContentsOfFile_(path)
            if img:
                img.setSize_((18, 18))
                img.setTemplate_(True)
                self._item.button().setImage_(img)
                self._item.button().setTitle_("")
                return
        # Fallback to emoji if PNG missing
        fallback = {"idle": "🎙️", "recording": "🔴", "transcribing": "⏳"}
        self._item.button().setImage_(None)
        self._item.button().setTitle_(fallback.get(state, "🎙️"))

    def set_state(self, state):
        if not self._available:
            return
        self._set_icon(state)
        labels = {"idle": "Idle", "recording": "Recording...", "transcribing": "Transcribing..."}
        self._status_item.setTitle_(f"Status: {labels.get(state, state.capitalize())}")

    def _update_hud_label(self):
        if not self._available:
            return
        self._toggle_item.setTitle_("Hide HUD" if settings.get("show_hud", True) else "Show HUD")

menubar = None

# ── GUI ───────────────────────────────────────────────────────────────────────
class DictationApp:
    BG         = "#1c1c1c"
    PILL       = "#242424"
    TEXT_WHITE = "#ffffff"
    TEXT_DIM   = "#4a4a4a"
    RED        = "#ff3b30"
    BLUE       = "#0a84ff"
    GREEN      = "#30d158"
    ORANGE     = "#ff9f0a"
    W          = 420
    H          = 52

    def __init__(self, root):
        self.root       = root
        self._ready     = False
        self._blink_job = None
        self._blink_on  = True
        self._drag_x    = 0
        self._drag_y    = 0
        self._msg_timer = None

        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
        self.root.attributes("-transparent", True)
        self.root.configure(bg="systemTransparent", highlightthickness=0)
        self.root.resizable(False, False)
        self.root.focus_set()  # keep focus on root not canvas

        # Never take keyboard focus — fixes spacebar stick issue
        try:
            from AppKit import NSApplication, NSApplicationActivationPolicyAccessory, NSWindow
            NSApplication.sharedApplication().setActivationPolicy_(
                NSApplicationActivationPolicyAccessory
            )
            self.root.update_idletasks()
            for win in NSApplication.sharedApplication().windows():
                win.setIgnoresMouseEvents_(False)
                win.setAcceptsMouseMovedEvents_(False)
                win.setCanBecomeKey_(False)
                win.setCanBecomeMain_(False)
        except Exception:
            pass

        sw = self.root.winfo_screenwidth()
        x  = settings.get("hud_x", sw//2 - self.W//2)
        y  = settings.get("hud_y", 24)
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")

        self._build()
        self._make_draggable()

        try:
            from AppKit import NSApplication
            self.root.update_idletasks()
            for win in NSApplication.sharedApplication().windows():
                win.setCornerRadius_(12)
                win.setOpaque_(False)
        except Exception:
            pass

    def _pill(self, x1, y1, x2, y2, r, **kw):
        c = self.canvas
        # Single smooth rounded rectangle using create_polygon with smooth
        points = [
            x1+r, y1,   x2-r, y1,
            x2,   y1,   x2,   y1+r,
            x2,   y2-r, x2,   y2,
            x2-r, y2,   x1+r, y2,
            x1,   y2,   x1,   y2-r,
            x1,   y1+r, x1,   y1,
        ]
        c.create_polygon(points, smooth=True, **kw)

    def _build(self):
        W, H = self.W, self.H
        self.canvas = tk.Canvas(self.root, width=W, height=H,
                                bg="systemTransparent", highlightthickness=0,
                                takefocus=0)
        self.canvas.pack()
        self._pill(0, 0, W, H, 18, fill=self.PILL, outline="")
        self.dot = self.canvas.create_oval(20, H//2-6, 32, H//2+6,
                                           fill=self.TEXT_DIM, outline="")
        self.canvas.create_line(46, 14, 46, H-14, fill="#303030", width=1)
        self.label = self.canvas.create_text(
            80, H//2, text="Loading model...",
            font=("Helvetica Neue", 13),
            fill=self.TEXT_DIM, anchor="w", width=260
        )
        self.appname = self.canvas.create_text(
            W-38, H//2, text="",
            font=("Helvetica Neue", 11),
            fill=self.TEXT_DIM, anchor="e"
        )
        self.appicon = self.canvas.create_image(
            W-22, H//2, anchor="e"
        )
        self.canvas.create_text(W-14, H//2, text="✕",
                                font=("Helvetica", 10),
                                fill=self.TEXT_DIM, anchor="center", tags="close")
        self.canvas.tag_bind("close", "<Button-1>", lambda e: os._exit(0))
        self.canvas.tag_bind("close", "<Enter>",
                             lambda e: self.canvas.itemconfig("close", fill=self.TEXT_WHITE))
        self.canvas.tag_bind("close", "<Leave>",
                             lambda e: self.canvas.itemconfig("close", fill=self.TEXT_DIM))

    def _make_draggable(self):
        def start(e):
            if not self._ready:
                return
            self._drag_x = e.x_root - self.root.winfo_x()
            self._drag_y = e.y_root - self.root.winfo_y()
        def move(e):
            if not self._ready:
                return
            x = e.x_root - self._drag_x
            y = e.y_root - self._drag_y
            self.root.geometry(f"+{x}+{y}")
            settings["hud_x"] = x
            settings["hud_y"] = y
            save_settings(settings)
        self.canvas.bind("<ButtonPress-1>", start)
        self.canvas.bind("<B1-Motion>",     move)

    def capture_active_app(self):
        def _fetch():
            # Do the heavy AppKit + PIL work in the thread
            try:
                from AppKit import NSWorkspace
                from PIL import Image
                import io
                ws   = NSWorkspace.sharedWorkspace()
                appo = ws.frontmostApplication()
                path = appo.bundleURL().path() if appo and appo.bundleURL() else None
                if path:
                    icon_ns = ws.iconForFile_(path)
                    icon_ns.setSize_((48, 48))
                    tiff = icon_ns.TIFFRepresentation()
                    img  = Image.open(io.BytesIO(bytes(tiff))).convert("RGBA")
                    bbox = img.getbbox()
                    if bbox:
                        img = img.crop(bbox)
                    img = img.resize((32, 32), Image.LANCZOS)
                    # ImageTk.PhotoImage MUST be created on the main thread
                    def _update_icon(i=img):
                        try:
                            from PIL import ImageTk
                            photo = ImageTk.PhotoImage(i)
                            self._app_icon = photo  # keep reference alive
                            self.canvas.itemconfig(self.appicon, image=photo)
                            self.canvas.itemconfig(self.appname, text="")
                        except Exception as e:
                            print(f"[icon] update error: {e}")
                    self.root.after(0, _update_icon)
                    return
            except Exception as e:
                print(f"[icon] fetch error: {e}")
            # Fallback: show app name as text
            def _update_name():
                try:
                    name = get_active_app_name()
                    self.canvas.itemconfig(self.appicon, image="")
                    self.canvas.itemconfig(self.appname, text=name[:8] if name else "")
                except Exception:
                    pass
            self.root.after(0, _update_name)
        threading.Thread(target=_fetch, daemon=True).start()

    def set_state(self, state):
        self.root.after(0, self._apply_state, state)
        if menubar:
            menubar.set_state(state)

    def _apply_state(self, state):
        if self._blink_job:
            self.root.after_cancel(self._blink_job)
            self._blink_job = None
        # Always stop wave animation on any state change
        if state != "recording":
            self.stop_wave()
        label = settings.get("hotkey_label", "Right Command")
        if state == "idle":
            self.stop_wave()
            self.canvas.itemconfig(self.dot,   fill=self.TEXT_DIM)
            self.canvas.itemconfig(self.label, text=f"Hold {label} to dictate",
                                   fill=self.TEXT_DIM)
        elif state == "recording":
            self.canvas.itemconfig(self.dot,   fill=self.RED)
            self.canvas.itemconfig(self.label, text="Recording...  release to stop",
                                   fill=self.TEXT_WHITE)
        elif state == "transcribing":
            self.stop_wave()
            self.canvas.itemconfig(self.dot,   fill=self.BLUE)
            self.canvas.itemconfig(self.label, text="Transcribing...", fill=self.BLUE)

    def set_transcript(self, text):
        self.root.after(0, self._show_transcript, text)

    def _show_transcript(self, text):
        short = text if len(text) <= 48 else text[:45] + "..."
        self.canvas.itemconfig(self.dot,   fill=self.GREEN)
        self.canvas.itemconfig(self.label, text=short, fill=self.TEXT_WHITE)

    def show_snippet_step(self, step, trigger=""):
        self.root.after(0, self._show_snippet_step, step, trigger)

    def _show_snippet_step(self, step, trigger=""):
        if self._msg_timer:
            self.root.after_cancel(self._msg_timer)
        if step == 1:
            self.canvas.itemconfig(self.dot,   fill=self.BLUE)
            self.canvas.itemconfig(self.label, text="Step 1: Say ONLY the trigger word/phrase",
                                   fill=self.BLUE)
        elif step == 2:
            self.canvas.itemconfig(self.dot,   fill=self.BLUE)
            short = trigger if len(trigger) <= 20 else trigger[:17] + "..."
            self.canvas.itemconfig(self.label,
                                   text=f"Step 2: '{short}' saved — say the full content",
                                   fill=self.BLUE)
        elif step == 3:
            self.canvas.itemconfig(self.dot,   fill=self.GREEN)
            self.canvas.itemconfig(self.label, text="Snippet saved!", fill=self.GREEN)
            self._msg_timer = self.root.after(3000, lambda: self._apply_state("idle"))

    def show_message(self, msg, color=None):
        self.root.after(0, self._show_msg, msg, color or self.ORANGE)

    def _show_msg(self, msg, color):
        if self._msg_timer:
            self.root.after_cancel(self._msg_timer)
        self.canvas.itemconfig(self.dot,   fill=color)
        self.canvas.itemconfig(self.label, text=msg, fill=color)
        self._msg_timer = self.root.after(5000, lambda: self._apply_state("idle"))

    def _blink(self):
        self._blink_on = not self._blink_on
        self.canvas.itemconfig(self.dot, fill=self.RED if self._blink_on else "#4a1510")
        self._blink_job = self.root.after(500, self._blink)

    # ── Wave bars ─────────────────────────────────────────────────────────────
    def start_wave(self):
        self.canvas.itemconfig(self.dot, state="hidden")
        H = self.H
        self._bars = []
        n_bars = 14
        bar_w  = 3
        gap    = 2
        total  = n_bars * (bar_w + gap) - gap
        start_x = 8  # left side where the dot was
        for i in range(n_bars):
            x = start_x + i * (bar_w + gap)
            bar = self.canvas.create_rectangle(x, H//2-1, x+bar_w, H//2+1,
                                               fill=self.RED, outline="")
            self._bars.append(bar)
        self._wave_phase = 0.0
        if recording:
            self._wave_job = self.root.after(30, self._animate_wave)
        else:
            self.root.after(0, self.stop_wave)

    def _animate_wave(self):
        if not hasattr(self, '_bars') or not self._bars:
            return
        import math
        H = self.H
        n = len(self._bars)
        rms   = get_current_rms()
        scale = min(1.0, rms * 18 + 0.15)
        self._wave_phase += 0.18

        # Gradient colors: bright red center, dim toward edges
        center = n / 2
        for i, bar in enumerate(self._bars):
            dist   = abs(i - center) / center          # 0 at center, 1 at edges
            height = int((H//2 - 6) * scale * (math.sin(self._wave_phase + i * 0.55) * 0.5 + 0.5) * (1 - dist * 0.5))
            height = max(2, height)
            # Fade color: bright red center -> dark red edges
            brightness = int(255 * (1 - dist * 0.65))
            color = f"#{brightness:02x}{int(brightness*0.18):02x}{int(brightness*0.12):02x}"
            x1, _, x2, _ = self.canvas.coords(bar)
            self.canvas.coords(bar, x1, H//2 - height, x2, H//2 + height)
            self.canvas.itemconfig(bar, fill=color)
        if recording:
            self._wave_job = self.root.after(30, self._animate_wave)
        else:
            self.root.after(0, self.stop_wave)

    def stop_wave(self):
        job = getattr(self, '_wave_job', None)
        self._wave_job = None  # set None FIRST to stop animation loop
        if job:
            self.root.after_cancel(job)
        if hasattr(self, '_bars'):
            for bar in self._bars:
                try:
                    self.canvas.delete(bar)
                except Exception:
                    pass
            self._bars = []
        try:
            self.canvas.itemconfig(self.dot, state="normal")
        except Exception:
            pass

    def _show_snippets(self, parent=None):
        BG   = "#1c1c1e"   # HUD background
        CARD = "#242424"   # pill color
        SEP  = "#2c2c2e"   # subtle separator
        ACC  = "#0a84ff"   # blue accent
        FG   = "#ffffff"
        DIM  = "#8e8e93"

        swin = tk.Toplevel(self.root)
        swin.title("Snippets")
        swin.geometry("660x520")
        swin.configure(bg=BG)
        swin.attributes("-topmost", True)
        swin.attributes("-alpha", 0.97)
        swin.resizable(True, True)
        try:
            swin.tk.call("::tk::unsupported::MacWindowStyle", "style", swin._w, "plain", "none")
        except Exception:
            pass

        # Title bar
        tb = tk.Frame(swin, bg=BG, height=48)
        tb.pack(fill="x"); tb.pack_propagate(False)
        tk.Label(tb, text="Snippets", bg=BG, fg=FG,
                 font=("Helvetica Neue", 14, "bold")).place(relx=0.5, rely=0.5, anchor="center")
        x_lbl = tk.Label(tb, text="✕", bg=BG, fg=DIM,
                         font=("Helvetica Neue", 14), cursor="hand2")
        x_lbl.place(x=16, y=14)
        x_lbl.bind("<Button-1>", lambda e: swin.destroy())
        x_lbl.bind("<Enter>",    lambda e: x_lbl.configure(fg=FG))
        x_lbl.bind("<Leave>",    lambda e: x_lbl.configure(fg=DIM))
        tk.Frame(swin, bg=SEP, height=1).pack(fill="x")

        # Search
        sf = tk.Frame(swin, bg=BG)
        sf.pack(fill="x", padx=16, pady=(12,8))
        tk.Label(sf, text="⌕", bg=BG, fg=DIM,
                 font=("Helvetica Neue", 16)).pack(side="left", padx=(0,8))
        search_var = tk.StringVar()
        tk.Entry(sf, textvariable=search_var, bg=CARD, fg=FG,
                 font=("Helvetica Neue", 13), relief="flat",
                 insertbackground=FG, bd=0).pack(side="left", fill="x", expand=True, ipady=7)
        tk.Frame(swin, bg=SEP, height=1).pack(fill="x", padx=16)

        # Body: left list + right editor
        body = tk.Frame(swin, bg=BG)
        body.pack(fill="both", expand=True, padx=0, pady=0)

        # Left panel
        left = tk.Frame(body, bg=BG, width=210)
        left.pack(side="left", fill="y"); left.pack_propagate(False)
        lc = tk.Canvas(left, bg=BG, highlightthickness=0)
        ls = tk.Scrollbar(left, orient="vertical", command=lc.yview)
        li = tk.Frame(lc, bg=BG)
        li.bind("<Configure>", lambda e: lc.configure(scrollregion=lc.bbox("all")))
        lc.create_window((0,0), window=li, anchor="nw")
        lc.configure(yscrollcommand=ls.set)
        lc.pack(side="left", fill="both", expand=True)
        ls.pack(side="right", fill="y")

        # Divider
        tk.Frame(body, bg=SEP, width=1).pack(side="left", fill="y")

        # Right panel
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=20, pady=16)

        tk.Label(right, text="TRIGGER", bg=BG, fg=DIM,
                 font=("Helvetica Neue", 9, "bold")).pack(anchor="w")
        trigger_var   = tk.StringVar()
        trigger_entry = tk.Entry(right, textvariable=trigger_var,
                                 bg=CARD, fg=FG, font=("Helvetica Neue", 14),
                                 relief="flat", insertbackground=FG, bd=0)
        trigger_entry.pack(fill="x", ipady=8, pady=(4,16))

        tk.Label(right, text="EXPANSION", bg=BG, fg=DIM,
                 font=("Helvetica Neue", 9, "bold")).pack(anchor="w")
        content_text = tk.Text(right, bg=CARD, fg=FG,
                               font=("Helvetica Neue", 13), relief="flat",
                               insertbackground=FG, wrap="word",
                               height=8, padx=10, pady=10, bd=0)
        content_text.pack(fill="both", expand=True, pady=(4,0))

        selected = [None]
        rows = {}

        def select(t, c):
            selected[0] = t
            trigger_var.set(t)
            content_text.delete("1.0", tk.END)
            content_text.insert("1.0", c)
            for k, b in rows.items():
                b.configure(bg=ACC if k == t else BG,
                            fg=FG if k == t else DIM)

        def refresh(q=""):
            for w in li.winfo_children():
                w.destroy()
            rows.clear()
            snips = load_snippets()
            shown = {t: c for t, c in snips.items()
                     if not q or q.lower() in t.lower() or q.lower() in c.lower()}
            if not shown:
                tk.Label(li, text="No snippets", bg=BG, fg=DIM,
                         font=("Helvetica Neue", 12)).pack(pady=20, padx=12)
                return
            for t, c in shown.items():
                b = tk.Button(li, text=f"  {t}", anchor="w",
                              bg=ACC if t == selected[0] else BG,
                              fg=FG if t == selected[0] else DIM,
                              activebackground="#1a6bcc",
                              font=("Helvetica Neue", 12),
                              relief="flat", padx=8, pady=10,
                              cursor="hand2",
                              command=lambda tt=t, cc=c: select(tt, cc))
                b.pack(fill="x")
                rows[t] = b
            if selected[0] not in shown and shown:
                first = next(iter(shown))
                select(first, shown[first])

        def delete_sel():
            t = selected[0]
            if not t: return
            s = load_snippets()
            if t in s: del s[t]
            with open(SNIPPETS_FILE, "w") as f: json.dump(s, f, indent=2)
            selected[0] = None
            trigger_var.set(""); content_text.delete("1.0", tk.END)
            refresh(search_var.get())
            self.show_message(f"Deleted '{t}'", self.ORANGE)

        def save_sel():
            t = trigger_var.get().strip().lower()
            c = content_text.get("1.0", tk.END).strip()
            if not t or not c: return
            s = load_snippets()
            old = selected[0]
            if old and old != t and old in s: del s[old]
            s[t] = c
            with open(SNIPPETS_FILE, "w") as f: json.dump(s, f, indent=2)
            selected[0] = t
            refresh(search_var.get())
            self.show_message(f"Saved '{t}'", self.GREEN)

        def new_snip():
            selected[0] = None
            trigger_var.set(""); content_text.delete("1.0", tk.END)
            for b in rows.values(): b.configure(bg=BG, fg=DIM)
            trigger_entry.focus_set()

        search_var.trace_add("write", lambda *a: refresh(search_var.get()))
        refresh()

        # Bottom bar
        tk.Frame(swin, bg=SEP, height=1).pack(fill="x")
        bot = tk.Frame(swin, bg=BG)
        bot.pack(fill="x", padx=16, pady=12)

        def _b(parent, text, cmd, primary=False):
            return tk.Button(parent, text=text, command=cmd,
                             bg=ACC if primary else CARD,
                             fg=FG, activebackground="#1a6bcc" if primary else "#3a3a3a",
                             font=("Helvetica Neue", 12, "bold" if primary else "normal"),
                             relief="flat", padx=16, pady=8, cursor="hand2", bd=0)

        _b(bot, "+ New",  new_snip).pack(side="left")
        _b(bot, "Delete", delete_sel).pack(side="left", padx=8)
        _b(bot, "Close",  swin.destroy).pack(side="right")
        _b(bot, "Save",   save_sel, primary=True).pack(side="right", padx=(0,8))
        swin.bind("<Command-s>", lambda e: save_sel())
        swin.bind("<Command-n>", lambda e: new_snip())

    def open_settings(self):
        self.root.after(0, self._show_settings)

    def _show_settings(self):
        BG   = "#1c1c1e"
        CARD = "#242424"
        SEP  = "#2c2c2e"
        ACC  = "#0a84ff"
        FG   = "#ffffff"
        DIM  = "#8e8e93"

        _win = tk.Toplevel(self.root)
        _win.title("Settings")
        _win.geometry("400x680")
        _win.configure(bg=BG)
        _win.resizable(False, True)
        _win.attributes("-topmost", True)
        _win.attributes("-alpha", 0.97)
        try:
            _win.tk.call("::tk::unsupported::MacWindowStyle", "style", _win._w, "plain", "none")
        except Exception:
            pass

        # Title bar
        tb = tk.Frame(_win, bg=BG, height=48)
        tb.pack(fill="x"); tb.pack_propagate(False)
        tk.Label(tb, text="Settings", bg=BG, fg=FG,
                 font=("Helvetica Neue", 14, "bold")).place(relx=0.5, rely=0.5, anchor="center")
        x_lbl = tk.Label(tb, text="✕", bg=BG, fg=DIM,
                         font=("Helvetica Neue", 14), cursor="hand2")
        x_lbl.place(x=16, y=14)
        x_lbl.bind("<Button-1>", lambda e: _win.destroy())
        x_lbl.bind("<Enter>",    lambda e: x_lbl.configure(fg=FG))
        x_lbl.bind("<Leave>",    lambda e: x_lbl.configure(fg=DIM))
        tk.Frame(_win, bg=SEP, height=1).pack(fill="x")

        # Scrollable body
        bc = tk.Canvas(_win, bg=BG, highlightthickness=0)
        bs = tk.Scrollbar(_win, orient="vertical", command=bc.yview)
        win = tk.Frame(bc, bg=BG)
        win.bind("<Configure>", lambda e: bc.configure(scrollregion=bc.bbox("all")))
        bc.create_window((0,0), window=win, anchor="nw")
        bc.configure(yscrollcommand=bs.set)
        bc.pack(side="left", fill="both", expand=True)
        bs.pack(side="right", fill="y")

        style = ttk.Style(_win)
        style.theme_use("clam")
        style.configure("D.TCombobox",
            fieldbackground=CARD, background=CARD,
            foreground=FG, arrowcolor=FG,
            selectbackground=ACC, selectforeground=FG,
            bordercolor=SEP, lightcolor=CARD, darkcolor=CARD)
        style.map("D.TCombobox",
            fieldbackground=[("readonly", CARD)],
            foreground=[("readonly", FG)],
            background=[("readonly", CARD)])

        def section(text):
            tk.Label(win, text=text, bg=BG, fg=DIM,
                     font=("Helvetica Neue", 9, "bold")).pack(
                     anchor="w", padx=20, pady=(18,6))

        def row(label, widget_fn):
            f = tk.Frame(win, bg=CARD)
            f.pack(fill="x", padx=16, pady=2, ipady=2)
            tk.Label(f, text=label, bg=CARD, fg=FG,
                     font=("Helvetica Neue", 13), anchor="w",
                     padx=12, pady=10).pack(side="left")
            widget_fn(f).pack(side="right", padx=12, pady=8)

        def toggle_row(label, var):
            f = tk.Frame(win, bg=CARD)
            f.pack(fill="x", padx=16, pady=2)
            tk.Label(f, text=label, bg=CARD, fg=FG,
                     font=("Helvetica Neue", 13), anchor="w",
                     padx=12, pady=10).pack(side="left")

            # Custom iOS-style toggle pill
            tog = tk.Canvas(f, width=44, height=24, bg=CARD,
                            highlightthickness=0, cursor="hand2")
            tog.pack(side="right", padx=12, pady=10)

            def draw_toggle():
                tog.delete("all")
                on = var.get()
                pill_color = ACC if on else "#3a3a3a"
                tog.create_oval(0, 0, 44, 24, fill=pill_color, outline="")
                knob_x = 22 if on else 2
                tog.create_oval(knob_x, 2, knob_x+20, 22, fill=FG, outline="")

            def toggle_click(e):
                var.set(not var.get())
                draw_toggle()

            tog.bind("<Button-1>", toggle_click)
            draw_toggle()

        def hotkey_label_row(label, key_text):
            f = tk.Frame(win, bg=CARD)
            f.pack(fill="x", padx=16, pady=2)
            tk.Label(f, text=label, bg=CARD, fg=FG,
                     font=("Helvetica Neue", 13), anchor="w",
                     padx=12, pady=10).pack(side="left")
            tk.Label(f, text=key_text, bg="#3a3a3a", fg=FG,
                     font=("Helvetica Neue", 11),
                     padx=10, pady=4).pack(side="right", padx=12, pady=8)

        section("TRANSCRIPTION")
        model_var = tk.StringVar(value=settings["model"])
        def model_w(f):
            return ttk.Combobox(f, textvariable=model_var, style="D.TCombobox",
                values=["tiny.en","base.en","small.en","medium.en",
                        "large-v2","large-v3","distil-medium.en","distil-large-v3"],
                state="readonly", width=16, font=("Helvetica Neue", 12))
        row("Model", model_w)

        section("HOTKEYS")
        hotkey_var = tk.StringVar(value=settings.get("hotkey_label", "Right Command"))
        if hotkey_var.get() not in HOTKEY_OPTIONS:
            hotkey_var.set("Right Command")
        def hotkey_w(f):
            return ttk.Combobox(f, textvariable=hotkey_var, style="D.TCombobox",
                values=list(HOTKEY_OPTIONS.keys()),
                state="readonly", width=16, font=("Helvetica Neue", 12))
        row("Record Key", hotkey_w)
        hotkey_label_row("Cancel",   "Escape")
        hotkey_label_row("Scratch",  "Ctrl+Z")
        hotkey_label_row("Settings", "Ctrl+D")

        section("DISPLAY")
        hud_var    = tk.BooleanVar(value=settings.get("show_hud", True))
        toggle_var = tk.BooleanVar(value=settings.get("toggle_mode", False))
        wake_var   = tk.BooleanVar(value=settings.get("wake_enabled", True))
        toggle_row("Show HUD",            hud_var)
        toggle_row("Toggle Mode",         toggle_var)
        toggle_row('Wake Word "Hey Jarvis"', wake_var)

        section("LANGUAGE")
        current_lang_name = next(
            (k for k, v in LANGUAGES.items() if v == settings.get("language", "en")), "English")
        lang_var = tk.StringVar(value=current_lang_name)
        def lang_w(f):
            return ttk.Combobox(f, textvariable=lang_var, style="D.TCombobox",
                values=list(LANGUAGES.keys()), state="readonly",
                width=16, font=("Helvetica Neue", 12))
        row("Language", lang_w)
        auto_var = tk.BooleanVar(value=settings.get("auto_detect", False))
        toggle_row("Auto-detect", auto_var)

        section("AI FEATURES")
        jarvis_var = tk.BooleanVar(value=settings.get("jarvis_enabled", True))
        format_var = tk.BooleanVar(value=settings.get("context_format", False))
        toggle_row("Jarvis Commands (Ollama)", jarvis_var)
        toggle_row("Context-Aware Formatting", format_var)

        section("VOICE LEARNING")
        vocab      = load_vocab()
        total      = vocab.get("total_dictations", 0)
        word_count = len(vocab.get("word_counts", {}))
        f_vl = tk.Frame(win, bg=CARD)
        f_vl.pack(fill="x", padx=16, pady=2)
        tk.Label(f_vl,
                 text=f"Learned from {total} dictations  •  {word_count} personal words",
                 bg=CARD, fg=DIM, font=("Helvetica Neue", 11),
                 padx=12, pady=10).pack(side="left")

        def reset_vocab():
            if os.path.exists(VOCAB_FILE): os.remove(VOCAB_FILE)
            app.show_message("Voice learning reset!", "#ff9f0a")
            _win.destroy()

        tk.Button(win, text="Reset Learning Data", command=reset_vocab,
                  bg=CARD, fg=DIM, font=("Helvetica Neue", 11),
                  relief="flat", padx=16, pady=8,
                  cursor="hand2", bd=0).pack(anchor="w", padx=16, pady=(0,4))

        section("CLOUD (OpenAI)")
        cloud_var = tk.BooleanVar(value=settings.get("cloud_mode", False))
        toggle_row("Cloud Mode", cloud_var)
        f_key = tk.Frame(win, bg=CARD)
        f_key.pack(fill="x", padx=16, pady=2)
        tk.Label(f_key, text="OpenAI Key", bg=CARD, fg=FG,
                 font=("Helvetica Neue", 13), padx=12, pady=10).pack(side="left")
        key_var = tk.StringVar(value=settings.get("openai_key", ""))
        tk.Entry(f_key, textvariable=key_var, bg=CARD, fg=FG,
                 font=("Helvetica Neue", 12), relief="flat",
                 insertbackground=FG, show="*", bd=0,
                 width=18).pack(side="right", padx=12, pady=8)

        tk.Frame(win, bg=BG, height=20).pack()

        # Bottom bar
        tk.Frame(_win, bg=SEP, height=1).pack(fill="x")
        bot = tk.Frame(_win, bg=BG)
        bot.pack(fill="x", padx=16, pady=12)

        def save_and_close():
            settings["model"]           = model_var.get()
            settings["hotkey_label"]    = hotkey_var.get()
            settings["show_hud"]        = hud_var.get()
            settings["toggle_mode"]     = toggle_var.get()
            settings["wake_enabled"]    = wake_var.get()
            globals()["WAKE_ENABLED"]   = wake_var.get()
            settings["cloud_mode"]      = cloud_var.get()
            settings["openai_key"]      = key_var.get()
            settings["jarvis_enabled"]  = jarvis_var.get()
            settings["context_format"]  = format_var.get()
            globals()["JARVIS_ENABLED"] = jarvis_var.get()
            save_settings(settings)
            if menubar: menubar._update_hud_label()
            _win.destroy()
            self.show_message("Saved! Restart to apply.", self.GREEN)

        def _b(parent, text, cmd, primary=False):
            return tk.Button(parent, text=text, command=cmd,
                             bg=ACC if primary else CARD,
                             fg=FG, activebackground="#1a6bcc" if primary else "#3a3a3a",
                             font=("Helvetica Neue", 12, "bold" if primary else "normal"),
                             relief="flat", padx=16, pady=8, cursor="hand2", bd=0)

        _b(bot, "Manage Snippets", lambda: self._show_snippets(_win)).pack(side="left")
        _b(bot, "Save", save_and_close, primary=True).pack(side="right")

# Model sizes that need downloading (not pre-cached)
LARGE_MODELS = {"large-v2", "large-v3", "distil-large-v3", "distil-medium.en"}

def reload_model():
    global whisper, MODEL
    model_name = settings["model"]

    # Warn about large models
    if model_name in LARGE_MODELS:
        app.root.after(0, lambda: app.show_message(
            f"Downloading {model_name}... (may take a few minutes)", "#ff9f0a"))
    else:
        app.root.after(0, lambda: app.show_message(
            f"Loading {model_name}...", "#0a84ff"))

    try:
        whisper = WhisperModel(model_name, device=DEVICE, compute_type=COMPUTE)
        MODEL = model_name
        app.root.after(0, lambda: app.show_message(f"{model_name} ready!", "#30d158"))
        print(f"[model] switched to {model_name}")
    except Exception as e:
        print(f"[model] error loading {model_name}: {e}")
        app.root.after(0, lambda: app.show_message(f"Failed to load {model_name}", "#ff3b30"))
        # Revert to small.en on failure
        settings["model"] = "small.en"
        save_settings(settings)
    # Delay idle so message stays visible for 4 seconds
    time.sleep(4.0)
    app.set_state("idle")

# ── Backend ───────────────────────────────────────────────────────────────────
def start_backend(stream):
    global whisper, JARVIS_ENABLED
    JARVIS_ENABLED = settings.get("jarvis_enabled", True)
    time.sleep(1.5)
    try:
        whisper = WhisperModel(MODEL, device=DEVICE, compute_type=COMPUTE)
    except Exception as e:
        print(f"[whisper] failed to load model '{MODEL}': {e}")
        app.root.after(0, lambda: app.show_message(
            f"Model '{MODEL}' not found — check ~/Library/Caches/whisper", "#ff3b30"))
        # Try falling back to tiny.en which is most likely to be cached
        fallback = "tiny.en"
        try:
            print(f"[whisper] falling back to {fallback}")
            whisper = WhisperModel(fallback, device=DEVICE, compute_type=COMPUTE)
            settings["model"] = fallback
            save_settings(settings)
            app.root.after(0, lambda: app.show_message(
                f"Loaded fallback model: {fallback}", "#ff9f0a"))
        except Exception as e2:
            print(f"[whisper] fallback also failed: {e2}")
            app.root.after(0, lambda: app.show_message(
                "No Whisper model found. Run: pip install faster-whisper", "#ff3b30"))
            app.set_state("idle")
            return
    print(f"[jarvis] enabled={JARVIS_ENABLED} model={MODEL}")
    app._ready = True
    app.set_state("idle")
    # Start wake word detection thread
    threading.Thread(target=_wake_word_loop, daemon=True).start()
    with keyboard.Listener(on_press=on_press, on_release=on_release):
        stream.start()
        threading.Event().wait()

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    global app, menubar
    root = tk.Tk()
    root.tk.call('tk', 'windowingsystem')  # force tk init
    try:
        root.tk.call('::tk::unsupported::MacWindowStyle', 'style', root._w, 'plain', 'none')
    except Exception:
        pass
    app  = DictationApp(root)

    if not settings.get("show_hud", True):
        root.withdraw()

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        device=MIC_DEVICE,
        callback=audio_callback,
    )
    threading.Thread(target=start_backend, args=(stream,), daemon=True).start()

    # Initialize MenuBarApp on main thread after tkinter is ready
    root.after(500, _init_menubar)
    root.mainloop()

def _init_menubar():
    """Initialize MenuBarApp, ensuring NSStatusBar calls land on the Cocoa main thread.

    tkinter's root.after() callbacks run on the main thread's run loop, which IS
    the Cocoa main thread in a normal Python process.  However in a PyInstaller
    .app bundle the thread identity can differ.  We use performSelectorOnMainThread
    as the safest cross-version dispatch — it's a no-op overhead when already on
    the right thread, and correctly re-dispatches when not.
    """
    global menubar

    def _create():
        global menubar
        menubar = MenuBarApp()

    try:
        from Foundation import NSObject
        import objc

        class _Trampoline(NSObject):
            def create_(self, _):
                _create()

        t = _Trampoline.alloc().init()
        t.performSelectorOnMainThread_withObject_waitUntilDone_(
            objc.selector(t.create_, selector=b"create:"), None, True
        )
    except Exception as e:
        print(f"[menubar] performSelectorOnMainThread unavailable ({e}), creating directly")
        _create()

if __name__ == "__main__":
    import multiprocessing, signal
    multiprocessing.freeze_support()

    def handle_signal(sig, frame):
        print("\n[exit] shutting down cleanly...")
        os._exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    import traceback
    try:
        main()
    except Exception as e:
        with open(os.path.expanduser("~/dictation_crash.log"), "w") as f:
            f.write(traceback.format_exc())
        raise
