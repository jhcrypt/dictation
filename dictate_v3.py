#!/usr/bin/env python
"""
Local Whisper Dictation v2 - Intel Mac
Hold Right Option to record, release to transcribe and type.
100% offline. No API keys. No cloud.
"""

import os
# CRITICAL CRASH FIX: Must be set BEFORE importing faster_whisper to prevent "illegal hardware instruction"
os.environ["OMP_NUM_THREADS"] = "1"

import threading
import tempfile
import sys
import time
import wave
import subprocess
import json
import re
import urllib.request as _urllib

try:
    import sounddevice as sd
    import numpy as np
    from pynput import keyboard
    from pynput.keyboard import Controller, Key
    from faster_whisper import WhisperModel
except ImportError as e:
    print(f"\nMissing dependency: {e}")
    sys.exit(1)

import tkinter as tk
from tkinter import ttk

# ── Ollama AI Brain ──────────────────────────────────────────────────────────
OLLAMA_MODEL   = "llama3"
OLLAMA_URL     = "http://localhost:11434/api/generate"
JARVIS_ENABLED = True  # overridden by settings on load

# Added Spark so Context-Aware formatting triggers on emails!
APP_FORMAT_RULES = {
    "mail":     "formal email tone, proper punctuation, capitalize first word",
    "spark":    "formal email tone, proper punctuation, capitalize first word",
    "messages": "casual conversational tone, short sentences",
    "slack":    "casual professional tone, short sentences",
    "notes":    "clear concise notes format",
    "code":     "technical precise language",
    "terminal": "command or technical text only",
    "word":     "formal document style with proper punctuation",
    "pages":    "formal document style with proper punctuation",
    "claude":   "conversational natural tone",
    "chrome":   "natural conversational text",
    "safari":   "natural conversational text",
}

JARVIS_COMMANDS = {
    "open": "open_app", "search": "web_search", "email": "send_email",
    "volume": "set_volume", "screenshot": "take_screenshot", "remind": "set_reminder",
    "calendar": "check_calendar", "close": "close_app", "play": "play_media", "weather": "check_weather",
}

def ollama_query(prompt, system="You are a helpful assistant.", timeout=8):
    try:
        payload = json.dumps({"model": OLLAMA_MODEL, "prompt": prompt, "system": system, "stream": False}).encode()
        req = _urllib.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
        with _urllib.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()).get("response", "").strip()
    except Exception as e:
        print(f"[ollama] error: {e}")
        return None

def detect_jarvis_intent(text):
    system = """You are an intent detector for a voice assistant on macOS.
Analyze the text and respond with JSON only, no explanation.
Format: {"is_command": true/false, "action": "action_name", "params": {}}"""
    response = ollama_query(text, system=system, timeout=5)
    if not response: return None
    try:
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match: return json.loads(match.group())
    except Exception as e:
        print(f"[intent] parse error: {e}")
    return None

def format_for_app(text, app_name):
    app_lower = app_name.lower()
    rule = next((fmt_rule for app_key, fmt_rule in APP_FORMAT_RULES.items() if app_key in app_lower), None)
    if not rule: return text

    prompt = f"Format this dictated text for use in {app_name}.\nRule: {rule}\nText: {text}\nReturn ONLY the formatted text, nothing else."
    formatted = ollama_query(prompt, timeout=5)
    if formatted:
        print(f"[format] {app_name}: {text!r} -> {formatted!r}")
        return formatted
    return text

def execute_jarvis_command(action, params):
    global _last_jarvis_time
    if time.time() - _last_jarvis_time < 3.0: return
    _last_jarvis_time = time.time()

    print(f"[jarvis] executing: {action} {params}")
    app.show_message(f"Jarvis: {action.replace('_', ' ')}...", "#0a84ff")

    try:
        if action == "open_app":
            app_name = params.get("app", "")
            url = params.get("url", "")
            if url: subprocess.Popen(["open", url])
            else:
                result = subprocess.run(["open", "-a", app_name], capture_output=True, text=True)
                if result.returncode != 0: subprocess.Popen(["open", "-a", app_name.lower()])
            app.show_message(f"Opening {app_name}", "#30d158")

        elif action == "web_search":
            query = params.get("query", "")
            subprocess.Popen(["open", f"https://duckduckgo.com/?q={query.replace(' ', '+')}"])
            app.show_message(f"Searching: {query[:30]}", "#30d158")

        elif action == "set_volume":
            direction = params.get("direction", "")
            level = params.get("level", None)
            if direction == "up": subprocess.run(["osascript", "-e", "set volume output volume (output volume of (get volume settings) + 25)"]); app.show_message("Volume up", "#30d158")
            elif direction == "down": subprocess.run(["osascript", "-e", "set volume output volume (output volume of (get volume settings) - 25)"]); app.show_message("Volume down", "#30d158")
            elif direction == "mute": subprocess.run(["osascript", "-e", "set volume with output muted"]); app.show_message("Muted", "#30d158")
            elif level is not None: subprocess.run(["osascript", "-e", f"set volume output volume {level}"]); app.show_message(f"Volume: {level}%", "#30d158")

        elif action == "take_screenshot":
            shot_type = params.get("type", "screen").lower()
            if "area" in shot_type: key, msg = "a", "Area capture"
            elif "scroll" in shot_type: key, msg = "s", "Scrolling capture"
            elif "text" in shot_type: key, msg = "t", "Text recognition"
            else: key, msg = "w", "Full screen capture"
            subprocess.Popen(["osascript", "-e", f'tell application "System Events"\n    keystroke "{key}" using control down\nend tell'])
            app.show_message(f"Shottr: {msg}", "#30d158")

        elif action == "check_weather":
            location = params.get("location", "")
            query = f"weather {location}" if location else "weather today"
            subprocess.Popen(["open", f"https://duckduckgo.com/?q={query.replace(' ', '+')}"])
            app.show_message("Opening weather", "#30d158")

        elif action == "check_calendar":
            subprocess.Popen(["open", "-a", "Calendar"])
            app.show_message("Opening Calendar", "#30d158")

        elif action == "set_reminder":
            text = params.get("text", "")
            subprocess.run(["osascript", "-e", f'tell application "Reminders"\n    tell default list\n        make new reminder with properties {{name:"{text}"}}\n    end tell\nend tell'])
            app.show_message(f"Reminder: {text[:30]}", "#30d158")

        elif action == "send_email":
            to, subject, body = params.get("to", ""), params.get("subject", ""), params.get("body", "")
            script = f'tell application "Spark" to activate\ndelay 0.5\ntell application "System Events"\ntell process "Spark"\nkeystroke "n" using command down\ndelay 0.5\nkeystroke "{to}"\nkeystroke tab\nkeystroke "{subject}"\nkeystroke tab\nkeystroke "{body}"\nend tell\nend tell'
            subprocess.Popen(["osascript", "-e", script])
            app.show_message(f"Composing email to {to[:20]}" if to else "Opening Spark", "#30d158")

        elif action == "close_app":
            app_name = params.get("app", "")
            subprocess.run(["osascript", "-e", f'tell application "{app_name}" to quit'])
            app.show_message(f"Closing {app_name}", "#30d158")

        elif action == "play_media":
            query = params.get("query", "")
            service = params.get("service", "youtube").lower()
            if "spotify" in service:
                # Be sure to replace these with your actual Spotify URIs!
                SPOTIFY_FAVORITES = {
                    "playlist4": "spotify:playlist:37i9dQZF1DX4UtSsGT1Sbe",
                    "playlist5": "spotify:playlist:0Ivl3dhpcSx8mL4df69HI9",
                    "playlist6": "spotify:playlist:7JZxrxQtbmAGcXf9b4BibQ",
                    "coding": "spotify:playlist:37i9dQZF1DXt6tRSzY2qG3",
                    "workout": "spotify:playlist:37i9dQZF1DX70RN3TfR07f",
                }
                condensed_query = query.lower().replace(" ", "")
                matched_uri = next((fav_uri for fav_name, fav_uri in SPOTIFY_FAVORITES.items() if fav_name in condensed_query), None)
                if matched_uri: subprocess.Popen(["osascript", "-e", f'tell application "Spotify" to play track "{matched_uri}"'])
                else: subprocess.Popen(["open", f"spotify:search:{query.replace(' ', '%20')}"])
            elif "apple music" in service:
                subprocess.Popen(["open", f"https://music.apple.com/search?term={query.replace(' ', '+')}"])
            else:
                subprocess.Popen(["open", f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"])
            app.show_message(f"Playing: {query[:30]}", "#30d158")

    except Exception as e:
        print(f"[jarvis] error: {e}")
        app.show_message(f"Jarvis error: {str(e)[:30]}", "#ff3b30")

# ── Symspell ──────────────────────────────────────────────────────────────────
try:
    from symspellpy import SymSpell, Verbosity
    _sym = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
    _DICT = os.path.expanduser("~/miniconda3/lib/python3.11/site-packages/symspellpy/frequency_dictionary_en_82_765.txt")
    USE_SYMSPELL = os.path.exists(_DICT) and _sym.load_dictionary(_DICT, term_index=0, count_index=1)
except ImportError:
    USE_SYMSPELL = False

WORD_TO_NUM = {
    "zero":"0","one":"1","two":"2","three":"3","four":"4","five":"5","six":"6",
    "seven":"7","eight":"8","nine":"9","ten":"10","eleven":"11","twelve":"12",
    "thirteen":"13","fourteen":"14","fifteen":"15","sixteen":"16","seventeen":"17",
    "eighteen":"18","nineteen":"19","twenty":"20","thirty":"30","forty":"40",
    "fifty":"50","sixty":"60","seventy":"70","eighty":"80","ninety":"90",
    "hundred":"100","thousand":"1000"
}

def words_to_digits(text):
    def replace(m): return WORD_TO_NUM.get(m.group(0).lower(), m.group(0))
    pattern = r'\b(' + '|'.join(WORD_TO_NUM.keys()) + r')\b'
    return re.sub(pattern, replace, text, flags=re.IGNORECASE)

def transcribe_cloud(wav_path):
    try:
        api_key = settings.get("openai_key", "")
        if not api_key: return None
        with open(wav_path, "rb") as f: audio_data = f.read()
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        part1 = ("--" + boundary + "\r\n" + 'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n' + "Content-Type: audio/wav\r\n\r\n").encode()
        part2 = ("\r\n--" + boundary + "\r\n" + 'Content-Disposition: form-data; name="model"\r\n\r\n' + "whisper-1\r\n--" + boundary + "--\r\n").encode()
        req = _urllib.Request("https://api.openai.com/v1/audio/transcriptions", data=part1 + audio_data + part2, headers={"Authorization": f"Bearer {api_key}", "Content-Type": f"multipart/form-data; boundary={boundary}"})
        with _urllib.urlopen(req, timeout=15) as r: return json.loads(r.read()).get("text", "").strip()
    except Exception as e:
        print(f"[cloud] error: {e}"); return None

def symspell_correct(text):
    if not USE_SYMSPELL: return text
    words = text.split()
    corrected = []
    for word in words:
        m = re.match(r"([a-zA-Z']+)([.,!?;:]*)$", word)
        if m:
            core, punct = m.group(1), m.group(2)
            suggestions = _sym.lookup(core.lower(), Verbosity.CLOSEST, max_edit_distance=2)
            if suggestions:
                s = suggestions[0].term
                if core[0].isupper(): s = s.capitalize()
                corrected.append(s + punct)
            else: corrected.append(word)
        else: corrected.append(word)
    return " ".join(corrected)

# ── Settings ──────────────────────────────────────────────────────────────────
SETTINGS_FILE = os.path.expanduser("~/.dictation_settings.json")
DEFAULT_SETTINGS = {
    "model": "small.en", 
    "mic_device": 2, 
    "sample_rate": 48000, 
    "hotkey_label": "Right Option", 
    "show_hud": True, 
    "toggle_mode": True, 
    "cloud_mode": False, 
    "openai_key": "", 
    "context_format": True, 
    "auto_detect": True, 
    "jarvis_enabled": True
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE) as f:
                s = json.load(f)
                for k, v in DEFAULT_SETTINGS.items(): s.setdefault(k, v)
                return s
        except Exception: pass
    return dict(DEFAULT_SETTINGS)

def save_settings(s):
    with open(SETTINGS_FILE, "w") as f: json.dump(s, f, indent=2)

settings = load_settings()
HOTKEY_OPTIONS = {"Right Command": Key.cmd_r, "Right Option": Key.alt_r, "Right Control": Key.ctrl_r, "F13": Key.f13, "F14": Key.f14, "F15": Key.f15}

def get_record_key(): return HOTKEY_OPTIONS.get(settings.get("hotkey_label", "Right Option"), Key.alt_r)

LANGUAGES = {"English":"en","Spanish":"es","French":"fr","German":"de","Italian":"it","Portuguese":"pt","Dutch":"nl","Russian":"ru","Japanese":"ja","Chinese":"zh","Korean":"ko","Arabic":"ar","Hindi":"hi","Auto-detect":None}
current_language = None if settings.get("auto_detect", True) else settings.get("language", "en")
MODEL, SAMPLE_RATE, CHANNELS, MIC_DEVICE = settings["model"], 48000, 1, settings.get("mic_device", 2)

import platform as _platform
_is_arm = _platform.machine() == "arm64"
DEVICE, COMPUTE = "cpu", "int8"
WAKE_WORD, WAKE_ENABLED, WAKE_CHUNK_SECS, WAKE_THRESHOLD, WAKE_MODEL_SIZE = "hey cryptic", True, 2.5, 0.003, "tiny.en"

# GLOBALS RESTORED
recording, audio_frames, last_text, typer, whisper, app, current_keys, cancelled = False, [], "", Controller(), None, None, set(), False
snippet_state, snippet_trigger, dictation_history, history_index, last_transcribed_text = None, "", [], -1, ""
_last_jarvis_time, wake_listening, wake_frames, wake_lock, wake_whisper = 0.0, False, [], threading.Lock(), None
_wake_cooldown_until = 0.0
_wake_active = threading.Event()

SNIPPETS_FILE = os.path.expanduser("~/.dictation_snippets.json")

def load_snippets():
    if os.path.exists(SNIPPETS_FILE):
        try:
            with open(SNIPPETS_FILE) as f: return json.load(f)
        except Exception: pass
    return {}

def apply_snippets(text):
    snippets = load_snippets()
    lower = text.strip().lower().rstrip(".,!?")
    for trigger, expansion in snippets.items():
        if lower == trigger.lower(): return expansion
    return text

HISTORY_FILE = os.path.expanduser("~/.dictation_history.json")

def save_history(text, app_name):
    try:
        history = []
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE) as f: history = json.load(f)
        history.append({"text": text, "app": app_name, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "model": settings.get("model", "unknown")})
        with open(HISTORY_FILE, "w") as f: json.dump(history[-500:], f, indent=2)
    except Exception as e: print(f"[history] save error: {e}")

VOCAB_FILE = os.path.expanduser("~/.dictation_vocabulary.json")
STOPWORDS = {"the","a","an","and","or","but","in","on","at","to","for","of","with","is","it","i","you","we","he","she","they","this","that","was","are","be","been","have","has","had","do","did","will","would","could","should","not","no","so","if","as","by","up","out","about","just","like","from","what","when","where","how","why","who","my","your","its","our","their","testing","one","two","three","four","five","okay","yes","no"}

def load_vocab():
    if os.path.exists(VOCAB_FILE):
        try:
            with open(VOCAB_FILE) as f: return json.load(f)
        except Exception: pass
    return {"word_counts": {}, "total_dictations": 0, "phrases": {}}

def save_vocab(vocab):
    try:
        with open(VOCAB_FILE, "w") as f: json.dump(vocab, f, indent=2)
    except Exception: pass

def learn_from_text(text):
    try:
        vocab = load_vocab()
        vocab["total_dictations"] = vocab.get("total_dictations", 0) + 1
        words = re.findall(r"[a-zA-Z']+", text.lower())
        for word in words:
            if len(word) > 3 and word not in STOPWORDS: vocab["word_counts"][word] = vocab["word_counts"].get(word, 0) + 1
        for i in range(len(words) - 1):
            phrase = words[i] + " " + words[i+1]
            if not any(w in STOPWORDS for w in [words[i], words[i+1]]): vocab["phrases"][phrase] = vocab["phrases"].get(phrase, 0) + 1
        save_vocab(vocab)
    except Exception as e: print(f"[vocab] error: {e}")

def get_personal_prompt():
    try:
        vocab = load_vocab()
        if vocab.get("total_dictations", 0) < 5: return None
        word_counts, phrases = vocab.get("word_counts", {}), vocab.get("phrases", {})
        top_words = sorted(word_counts, key=word_counts.get, reverse=True)[:20]
        top_phrases = sorted(phrases, key=phrases.get, reverse=True)[:5]
        prompt = "Transcribe spoken English accurately."
        if top_words: prompt += f" Common words: {', '.join(top_words)}."
        if top_phrases: prompt += f" Common phrases: {', '.join(top_phrases)}."
        return prompt
    except Exception: return None

def get_active_app_name():
    try: return subprocess.check_output(["osascript", "-e", 'tell application "System Events" to get name of first application process whose frontmost is true'], timeout=1).decode().strip()
    except Exception: return ""

def play_sound(name):
    sounds = {"start": "/System/Library/Sounds/Tink.aiff", "stop": "/System/Library/Sounds/Pop.aiff"}
    subprocess.Popen(["afplay", sounds[name]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def _set_system_mute(mute: bool):
    try: subprocess.run(["osascript", "-e", f"set volume {'with' if mute else 'without'} output muted"], timeout=3)
    except Exception: pass

_pre_recording_muted = False
_apps_were_playing = []
_browsers_paused = []

def _is_running(proc_name):
    try: return subprocess.run(["pgrep", "-ix", proc_name], capture_output=True, timeout=1).returncode == 0
    except Exception: return False

def pause_media():
    global _pre_recording_muted, _apps_were_playing, _browsers_paused
    _apps_were_playing = []
    _browsers_paused = []
    try:
        _pre_recording_muted = (subprocess.check_output(["osascript", "-e", "output muted of (get volume settings)"], timeout=2).decode().strip() == "true")
        if not _pre_recording_muted: _set_system_mute(True)
    except Exception: pass
    for proc, state_cmd, pause_cmd in [("Spotify", 'tell application "Spotify" to player state as string', 'tell application "Spotify" to pause'), ("Music", 'tell application "Music" to player state as string', 'tell application "Music" to pause'), ("Podcasts", 'tell application "Podcasts" to player state as string', 'tell application "Podcasts" to pause')]:
        if not _is_running(proc): continue
        try:
            if subprocess.check_output(["osascript", "-e", state_cmd], timeout=2).decode().strip().lower() in ("playing", "1"):
                subprocess.Popen(["osascript", "-e", pause_cmd]); _apps_were_playing.append(proc)
        except Exception: pass

def resume_media():
    global _pre_recording_muted, _apps_were_playing, _browsers_paused
    if not _pre_recording_muted: _set_system_mute(False)
    resume_cmds = {"Spotify": 'tell application "Spotify" to play', "Music": 'tell application "Music" to play', "Podcasts": 'tell application "Podcasts" to resume'}
    for app_name in _apps_were_playing:
        try: subprocess.run(["osascript", "-e", resume_cmds[app_name]], timeout=5)
        except Exception: pass
    _apps_were_playing = []
    _browsers_paused = []

def get_current_rms():
    return float(np.sqrt(np.mean(audio_frames[-1]**2))) if audio_frames else 0.0

def audio_callback(indata, frames, time_info, status):
    if recording: audio_frames.append(indata.copy())
    elif WAKE_ENABLED and not recording and not cancelled:
        with wake_lock: wake_frames.append(indata.copy())

def save_wav(frames, path):
    audio = np.concatenate(frames, axis=0)
    target_len = int(len(audio) * 16000 / SAMPLE_RATE)
    resampled = np.interp(np.linspace(0, len(audio)-1, target_len), np.arange(len(audio)), audio[:, 0]).astype(np.float32)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes((resampled * 32767).astype(np.int16).tobytes())

def paste_text(text):
    try:
        import subprocess as _sp
        prev = _sp.run(["pbpaste"], capture_output=True).stdout
        _sp.run(["pbcopy"], input=(text + " ").encode(), timeout=2)
        import time as _t; _t.sleep(0.05)
        from pynput.keyboard import Controller as _C, Key as _K
        _k = _C()
        with _k.pressed(_K.cmd):
            _k.press("v"); _k.release("v")
        _t.sleep(0.1)
        _sp.run(["pbcopy"], input=prev, timeout=2)
    except Exception: typer.type(text + " ")

def smart_punctuate(text):
    if not text or text.rstrip()[-1] in ".!?": return text
    question_starters = ("what", "when", "where", "who", "why", "how", "which", "whose", "is ", "are ", "was ", "were ", "will ", "would ", "could ", "should ", "do ", "does ", "did ", "have ", "has ", "had ", "can ", "may ", "might ", "shall ", "am ", "isn't", "aren't", "wasn't", "weren't", "don't", "doesn't", "didn't", "won't", "wouldn't", "couldn't")
    if any(text.lower().strip().startswith(q) for q in question_starters): return text.rstrip() + "?"
    return text.rstrip() + "."

def _fast_jarvis_match(lower):
    import re
    open_match = re.match(r"^open (.+)$", lower)
    if open_match:
        target = open_match.group(1).strip()
        websites = {
            "youtube": "https://www.youtube.com", "google": "https://www.google.com", 
            "duckduckgo": "https://duckduckgo.com", "gmail": "https://mail.google.com", 
            "twitter": "https://www.twitter.com", "x": "https://www.x.com", 
            "instagram": "https://www.instagram.com", "facebook": "https://www.facebook.com", 
            "linkedin": "https://www.linkedin.com", "github": "https://www.github.com", 
            "spotify": "", "netflix": "https://www.netflix.com", 
            "amazon": "https://www.amazon.com", "reddit": "https://www.reddit.com", 
            "claude": "https://claude.ai", "chatgpt": "https://chat.openai.com", 
            "maps": "https://maps.google.com", "my website": "https://your-actual-website.com", "my repo": "https://github.com/your-username/repo-name",
        }
        if target in websites: return ("open_app", {"app": target.capitalize(), "url": websites[target]})
        return ("open_app", {"app": target.capitalize(), "url": ""})

    if any(p in lower for p in ("open email", "check email", "open spark", "check spark", "open my email", "check my email", "open inbox")):
        return ("open_app", {"app": "Spark", "url": ""})

    app_keywords = {
        "notes": "Notes", "calendar": "Calendar", "messages": "Messages",
        "slack": "Slack", "finder": "Finder", "terminal": "Terminal",
        "system settings": "System Settings", "music": "Music", "photos": "Photos",
        "facetime": "FaceTime", "maps": "Maps", "weather": "Weather",
        "reminders": "Reminders", "calculator": "Calculator", "safari": "Safari",
        "chrome": "Google Chrome", "firefox": "Firefox", "vs code": "Visual Studio Code",
        "vscode": "Visual Studio Code", "xcode": "Xcode", "textedit": "TextEdit",
        "photoshop": "Adobe Photoshop 2025", "illustrator": "Adobe Illustrator",
        "premiere": "Adobe Premiere Pro", "after effects": "Adobe After Effects",
        "figma": "Figma", "sketch": "Sketch", "zoom": "Zoom", "teams": "Microsoft Teams",
        "word": "Microsoft Word", "excel": "Microsoft Excel", "powerpoint": "Microsoft PowerPoint",
        "outlook": "Microsoft Outlook", "notion": "Notion", "obsidian": "Obsidian",
        "discord": "Discord", "whatsapp": "WhatsApp", "telegram": "Telegram",
        "1password": "1Password 7", "screenflow": "ScreenFlow", "quicktime": "QuickTime Player",
        "vlc": "VLC", "iterm": "iTerm", "app store": "App Store"
    }
    if lower.startswith("open "):
        keyword = lower[5:].strip()
        if keyword in app_keywords: return ("open_app", {"app": app_keywords[keyword], "url": ""})
        for kw, app_name in app_keywords.items():
            if kw in keyword: return ("open_app", {"app": app_name, "url": ""})
        return ("open_app", {"app": keyword.title(), "url": ""})

    email_match = re.match(r"(?:send|compose|write|draft)\s+(?:an\s+)?email\s+(?:to\s+)?(.+?)\s+(?:saying|that|about|with)\s+(.+)", lower)
    if email_match: return ("send_email", {"to": email_match.group(1).strip(), "subject": "", "body": email_match.group(2).strip()})
    simple_email = re.match(r"^(?:send|compose|write)\s+(?:an\s+)?email\s+to\s+(.+)", lower)
    if simple_email: return ("send_email", {"to": simple_email.group(1).strip(), "subject": "", "body": ""})

    for prefix in ("search for ", "search ", "google ", "look up "):
        if lower.startswith(prefix): return ("web_search", {"query": lower[len(prefix):]})

    for prefix in ("play ", "watch "):
        if lower.startswith(prefix):
            query = lower[len(prefix):].strip()
            
            # FIXED: Handle Whisper's typos for "notify", "playlist for", and spaces!
            query = query.replace(" on notify", " on spotify").replace("playlist for", "playlist 4").replace("play list", "playlist")
            
            if query.endswith(" on spotify"): return ("play_media", {"query": query[:-11].strip(), "service": "spotify"})
            elif query.endswith(" on apple music"): return ("play_media", {"query": query[:-15].strip(), "service": "apple music"})
            elif any(fav in query for fav in ["playlist 4", "playlist 5", "playlist 6", "coding", "workout"]): return ("play_media", {"query": query, "service": "spotify"})
            else: return ("play_media", {"query": query, "service": "youtube"})

    if lower in ("volume up", "turn volume up", "increase volume", "raise volume", "louder"): return ("set_volume", {"direction": "up"})
    if lower in ("volume down", "turn volume down", "decrease volume", "reduce volume", "lower volume", "quieter"): return ("set_volume", {"direction": "down"})
    if lower in ("mute", "mute volume", "turn off sound", "unmute"): return ("set_volume", {"direction": "mute"})
    if lower.startswith("set volume to "):
        try: return ("set_volume", {"direction": "", "level": min(100, max(0, int(lower.replace("set volume to ", "").strip())))})
        except Exception: pass

    if any(p in lower for p in ("capture area", "area capture", "area screenshot")): return ("take_screenshot", {"type": "area"})
    if any(p in lower for p in ("scrolling capture", "scrolling screenshot", "capture scrolling", "capture scroll")): return ("take_screenshot", {"type": "scrolling"})
    if any(p in lower for p in ("text recognition", "extract text", "capture text", "recognize text")): return ("take_screenshot", {"type": "text"})
    if any(p in lower for p in ("capture screen", "capture full screen", "full screen capture", "take a screenshot", "screenshot", "take screenshot", "capture window", "window screenshot")): return ("take_screenshot", {"type": "screen"})

    if any(p in lower for p in ("check weather", "whats the weather", "weather today")): return ("check_weather", {"location": ""})
    if any(p in lower for p in ("open calendar", "check calendar", "whats on my calendar")): return ("check_calendar", {})
    remind_match = re.match(r"remind me (?:to )?(.+)", lower)
    if remind_match: return ("set_reminder", {"text": remind_match.group(1)})
    close_match = re.match(r"close (.+)", lower)
    if close_match: return ("close_app", {"app": close_match.group(1).capitalize()})
    return None

def transcribe_and_type(wav_path, raw_frames):
    global last_text, cancelled, snippet_state, snippet_trigger
    if cancelled:
        cancelled = False
        app.set_state("idle")
        return
    audio = np.concatenate(raw_frames, axis=0)
    if np.sqrt(np.mean(audio**2)) < 0.002:
        threading.Thread(target=resume_media, daemon=True).start()
        app.set_state("idle")
        return
    globals()["_recording_had_audio"] = True
    app.set_state("transcribing")
    if float(np.sqrt(np.mean(np.concatenate(raw_frames, axis=0)**2))) < 0.008:
        print("[transcribe] skipping — audio too quiet")
        app.set_state("idle")
        return

    personal_prompt = get_personal_prompt()
    language_to_use = "en" if not settings.get("auto_detect", True) else None

    if settings.get("cloud_mode") and settings.get("openai_key"):
        raw_text = transcribe_cloud(wav_path)
        if not raw_text:
            segments, _ = whisper.transcribe(wav_path, beam_size=5, language=language_to_use, condition_on_previous_text=False, initial_prompt=personal_prompt, vad_filter=True, no_speech_threshold=0.6)
            raw_text = " ".join(seg.text for seg in segments).strip()
    else:
        segments, _ = whisper.transcribe(wav_path, beam_size=5, language=language_to_use, condition_on_previous_text=False, initial_prompt=personal_prompt, vad_filter=True, no_speech_threshold=0.6)
        raw_text = " ".join(seg.text for seg in segments).strip()
    
    if not raw_text:
        app.set_state("idle")
        return

    # FIXED: Number conversion correctly runs before intent parsing!
    raw_text = words_to_digits(raw_text)
    lower = re.sub(r"[^a-z0-9 ]", "", raw_text.lower()).strip()
    print(f"[cmd] {lower!r}")

    if JARVIS_ENABLED:
        cmd_text = lower[7:].strip() if lower.startswith("jarvis ") else (lower[11:].strip() if lower.startswith("hey jarvis ") else lower)
        jarvis_intent = _fast_jarvis_match(cmd_text)
        if jarvis_intent:
            threading.Thread(target=execute_jarvis_command, args=(jarvis_intent[0], jarvis_intent[1]), daemon=True).start()
            app.set_state("idle")
            return

    if snippet_state == "waiting_trigger":
        if any(p in lower for p in ("create snippet","new snippet","add snippet","make snippet")):
            app.show_message("That's a command, not a trigger. Try again.", "#ff9f0a")
            app.set_state("idle")
            return
        snippet_trigger, snippet_state = lower, "waiting_content"
        app.show_snippet_step(2, snippet_trigger)
        return
        
    if snippet_state == "waiting_content":
        snippets = load_snippets()
        snippets[snippet_trigger] = raw_text.strip().replace(' at ', '@').replace(' dot ', '.').replace(' dot', '.')
        with open(SNIPPETS_FILE, "w") as f:
            json.dump(snippets, f, indent=2)
        snippet_state, snippet_trigger = None, ""
        app.show_snippet_step(3)
        app.set_state("idle")
        return
        
    if lower in ("create snippet", "new snippet", "add snippet", "make snippet", "create a snippet"):
        snippet_state = "waiting_trigger"
        app.show_snippet_step(1)
        return

    if lower in ("scratch that", "undo that", "delete that", "scratch", "undo", "scratch last"):
        _scratch_last(1)
        app.set_state("idle")
        return
    if lower in ("scratch again", "undo again", "scratch more"):
        _scratch_last(1)
        app.set_state("idle")
        return
    if any(p in lower for p in ("scratch last 2", "scratch two", "scratch last two", "undo last 2", "undo two", "undo last two", "scratch last tool", "delete last 2", "delete two")):
        _scratch_last(2)
        app.set_state("idle")
        return
    if any(p in lower for p in ("scratch last 3", "scratch three", "scratch last three", "undo last 3", "undo three", "undo last three", "delete last 3", "delete three")):
        _scratch_last(3)
        app.set_state("idle")
        return
    if any(p in lower for p in ("scratch all", "undo all", "delete all", "clear all")):
        _scratch_last(len(dictation_history))
        app.set_state("idle")
        return

    PUNCT_COMMANDS = {"period":".","full stop":".","comma":",","exclamation point":"!","exclamation mark":"!","question mark":"?","colon":":","semicolon":";","ellipsis":"...","open paren":"(","close paren":")","dash":" — ","hyphen":"-"}
    if lower in PUNCT_COMMANDS:
        typer.type(PUNCT_COMMANDS[lower])
        app.show_message(PUNCT_COMMANDS[lower], "#0a84ff")
        app.set_state("idle")
        return

    if lower in ("new line", "newline", "next line"):
        if any(a in get_active_app_name().lower() for a in ("claude", "slack", "discord", "messages", "teams", "whatsapp", "telegram")):
            typer.press(Key.shift); typer.press(Key.enter); typer.release(Key.enter); typer.release(Key.shift)
        else:
            typer.press(Key.enter); typer.release(Key.enter)
        app.show_message("New line", "#0a84ff")
        app.set_state("idle")
        return
        
    if lower == "new paragraph":
        for _ in range(2):
            typer.press(Key.enter); typer.release(Key.enter)
        app.show_message("New paragraph", "#0a84ff")
        app.set_state("idle")
        return
        
    if lower in ("tab", "indent"):
        typer.press(Key.tab); typer.release(Key.tab)
        app.show_message("Tab", "#0a84ff")
        app.set_state("idle")
        return
        
    if lower == "select all":
        with typer.pressed(Key.cmd):
            typer.press("a"); typer.release("a")
        app.show_message("Select all", "#0a84ff")
        app.set_state("idle")
        return

    if lower in ("make bold", "bold that") and last_text:
        for _ in range(len(last_text) + 1): typer.press(Key.backspace); typer.release(Key.backspace)
        last_text = f"**{last_text}**"; paste_text(last_text); app.show_message("Bolded!", "#0a84ff"); app.set_state("idle"); return
    if lower in ("make italic", "italic that") and last_text:
        for _ in range(len(last_text) + 1): typer.press(Key.backspace); typer.release(Key.backspace)
        last_text = f"*{last_text}*"; paste_text(last_text); app.show_message("Italicized!", "#0a84ff"); app.set_state("idle"); return
    if lower in ("format as code", "code that", "make code") and last_text:
        for _ in range(len(last_text) + 1): typer.press(Key.backspace); typer.release(Key.backspace)
        last_text = f"`{last_text}`"; paste_text(last_text); app.show_message("Code formatted!", "#0a84ff"); app.set_state("idle"); return
    if lower in ("make heading", "heading that", "make title") and last_text:
        for _ in range(len(last_text) + 1): typer.press(Key.backspace); typer.release(Key.backspace)
        last_text = f"# {last_text}"; paste_text(last_text); app.show_message("Heading!", "#0a84ff"); app.set_state("idle"); return
    if lower in ("all caps", "make caps", "capitalize that") and last_text:
        for _ in range(len(last_text) + 1): typer.press(Key.backspace); typer.release(Key.backspace)
        last_text = last_text.upper(); paste_text(last_text); app.show_message("ALL CAPS!", "#0a84ff"); app.set_state("idle"); return
    if lower in ("make bullet", "bullet that", "create list", "make list") and last_text:
        for _ in range(len(last_text) + 1): typer.press(Key.backspace); typer.release(Key.backspace)
        last_text = "\n".join(f"• {s.strip()}" for s in last_text.split('.') if s.strip()); paste_text(last_text); app.show_message("Bulleted!", "#0a84ff"); app.set_state("idle"); return
    if lower in ("make quote", "quote that", "block quote") and last_text:
        for _ in range(len(last_text) + 1): typer.press(Key.backspace); typer.release(Key.backspace)
        last_text = f"> {last_text}"; paste_text(last_text); app.show_message("Quoted!", "#0a84ff"); app.set_state("idle"); return
    if lower in ("strikethrough that", "strike that") and last_text:
        for _ in range(len(last_text) + 1): typer.press(Key.backspace); typer.release(Key.backspace)
        last_text = f"~~{last_text}~~"; paste_text(last_text); app.show_message("Strikethrough!", "#0a84ff"); app.set_state("idle"); return

    if lower in ("copy that", "copy last"):
        if last_text:
            subprocess.run(["osascript", "-e", f'set the clipboard to "{last_text}"'], timeout=2)
            app.show_message("Copied!", "#0a84ff")
        else:
            app.show_message("Nothing to copy", "#ff9f0a")
        app.set_state("idle")
        return
        
    if lower == "copy all":
        with typer.pressed(Key.cmd):
            typer.press("a"); typer.release("a")
        time.sleep(0.05)
        with typer.pressed(Key.cmd):
            typer.press("c"); typer.release("c")
        app.show_message("Copied all!", "#0a84ff")
        app.set_state("idle")
        return
        
    if lower in ("paste", "paste that"):
        with typer.pressed(Key.cmd):
            typer.press("v"); typer.release("v")
        app.show_message("Pasted!", "#0a84ff")
        app.set_state("idle")
        return

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

    text = smart_punctuate(apply_snippets(symspell_correct(raw_text)))
    last_text = text
    _add_to_history(text)
    active_app = get_active_app_name()

    if settings.get("context_format") and active_app:
        app.show_message("Formatting...", "#0a84ff")
        formatted = format_for_app(text, active_app)
        if formatted and formatted != text:
            text = formatted

    app.set_transcript(text)
    paste_text(text)
    threading.Thread(target=resume_media, daemon=True).start()

    def _background_tasks(t=text, a=active_app):
        save_history(t, a)
        learn_from_text(t)

    threading.Thread(target=_background_tasks, daemon=True).start()
    time.sleep(1.5)
    app.set_state("idle")

def _scratch_last(count=1):
    global last_text, dictation_history, history_index
    deleted = 0
    for i in range(count):
        if history_index >= 0 and history_index < len(dictation_history):
            text_to_delete = dictation_history[history_index]
        elif i == 0 and last_text:
            text_to_delete = last_text
        else:
            break
        for _ in range(len(text_to_delete) + 1):
            typer.press(Key.backspace)
            typer.release(Key.backspace)
            time.sleep(0.005)
        if history_index >= 0 and history_index < len(dictation_history):
            dictation_history.pop(history_index)
            history_index = len(dictation_history) - 1
        last_text = dictation_history[history_index] if history_index >= 0 and dictation_history else ""
        deleted += 1
    if deleted > 1: app.show_message(f"Scratched {deleted}!", "#ff9f0a")
    elif deleted: app.show_message("Scratched!", "#ff9f0a")
    else: app.show_message("Nothing to scratch", "#ff9f0a")

def _add_to_history(text):
    global dictation_history, history_index
    if history_index < len(dictation_history) - 1:
        dictation_history = dictation_history[:history_index + 1]
    dictation_history.append(text)
    history_index = len(dictation_history) - 1
    if len(dictation_history) > 50:
        dictation_history = dictation_history[-50:]
        history_index = 49

def _undo_last_dictation():
    global last_text, history_index
    if last_text:
        for _ in range(len(last_text) + 1):
            typer.press(Key.backspace); typer.release(Key.backspace)
        history_index = max(-1, history_index - 1)
        app.show_message("Undo!", "#0a84ff")
    else:
        app.show_message("Nothing to undo", "#ff9f0a")

def _redo_dictation():
    global history_index
    if history_index < len(dictation_history) - 1:
        history_index += 1
        paste_text(dictation_history[history_index])
        app.show_message("Redo!", "#0a84ff")
    else:
        app.show_message("Nothing to redo", "#ff9f0a")

def _reinsert_last():
    global last_text
    if last_text:
        paste_text(last_text)
        app.show_message("Re-inserted!", "#30d158")
    else:
        app.show_message("Nothing to re-insert", "#ff9f0a")

def _show_history():
    def _show():
        hwin = tk.Toplevel(app.root)
        hwin.title("Dictation History")
        hwin.geometry("500x400")
        hwin.configure(bg="#1a1a1a")
        hwin.attributes("-topmost", True)
        tk.Label(hwin, text="Recent Dictations", bg="#1a1a1a", fg="#ffffff", font=("Helvetica Neue", 14, "bold")).pack(pady=(12, 4))
        frame = tk.Frame(hwin, bg="#1a1a1a")
        frame.pack(fill="both", expand=True, padx=16, pady=8)
        canvas = tk.Canvas(frame, bg="#1a1a1a", highlightthickness=0)
        scroll = tk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg="#1a1a1a")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
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
                    tk.Label(row, text=item["text"][:60] + ("..." if len(item["text"]) > 60 else ""), bg="#2a2a2a", fg="#aaaaaa", font=("Helvetica Neue", 10), anchor="w", padx=8, pady=4).pack(fill="x")
                    tk.Label(row, text=f"{item['app']} • {item['timestamp']}", bg="#1c1c1c", fg="#666666", font=("Helvetica Neue", 8)).pack(anchor="w", padx=8, pady=2)
            else:
                tk.Label(inner, text="No history yet", bg="#1a1a1a", fg="#666666", font=("Helvetica Neue", 11)).pack(pady=20)
        except Exception:
            tk.Label(inner, text="Error loading history", bg="#1a1a1a", fg="#ff3b30", font=("Helvetica Neue", 11)).pack(pady=20)
        tk.Button(hwin, text="Close", command=hwin.destroy, bg="#2a2a2a", fg="#aaaaaa", font=("Helvetica Neue", 12), relief="flat", padx=20, pady=8, cursor="hand2").pack(pady=8)
    app.root.after(0, _show)

def _trigger_wake():
    global recording, audio_frames, cancelled, _wake_cooldown_until
    if recording or time.time() < _wake_cooldown_until: return
    with wake_lock:
        wake_frames.clear()
    audio_frames = []
    time.sleep(0.3)
    audio_frames = []
    cancelled = False
    recording = True
    _wake_active.set()
    _wake_cooldown_until = time.time() + 5.0
    app.capture_active_app()
    app.set_state("recording")
    app.root.after(0, app.start_wave)
    app.root.after(100, lambda: app.canvas.itemconfig(app.label, text=f"Recording...  press {settings.get('hotkey_label', 'Right Option')} to stop", fill=app.TEXT_WHITE))
    threading.Thread(target=play_sound, args=("start",), daemon=True).start()
    threading.Thread(target=_silence_stop_monitor, daemon=True).start()

def _silence_stop_monitor():
    start_time = time.time()
    silence_since = None
    while recording:
        time.sleep(0.1)
        if time.time() - start_time < 1.5:
            silence_since = None
            continue
        if not audio_frames: continue
        if float(np.sqrt(np.mean(audio_frames[-1]**2))) < 0.08:
            if silence_since is None:
                silence_since = time.time()
            elif time.time() - silence_since >= 2.5:
                _stop_recording()
                return
        else:
            silence_since = None

def _wake_word_loop():
    global recording
    try:
        from openwakeword.model import Model as WakeModel
        oww = WakeModel(wakeword_models=["hey_jarvis"], inference_framework="onnx")
    except Exception:
        return

    while True:
        while True:
            if recording or not WAKE_ENABLED:
                time.sleep(0.5)
                continue
            buf = []
            triggered = False

            def _oww_callback(indata, frames, time_info, status):
                nonlocal triggered
                if recording or triggered or not WAKE_ENABLED or time.time() < _wake_cooldown_until: return
                audio = indata[:, 0]
                target_len = int(len(audio) * 16000 / SAMPLE_RATE)
                resampled = np.interp(np.linspace(0, len(audio)-1, target_len), np.arange(len(audio)), audio)
                buf.extend(resampled.tolist())
                while len(buf) >= 1280:
                    chunk = np.array(buf[:1280], dtype=np.float32)
                    del buf[:1280]
                    if oww.predict((chunk * 32767).astype(np.int16)).get("hey_jarvis", 0) > 0.75:
                        triggered = True
                        buf.clear()

            try:
                with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", device=MIC_DEVICE, callback=_oww_callback):
                    while not recording and not triggered and WAKE_ENABLED:
                        time.sleep(0.05)
            except Exception:
                time.sleep(1)
                continue

            if triggered and not recording:
                threading.Thread(target=_trigger_wake, daemon=True).start()
            while recording:
                time.sleep(0.2)
            try:
                oww.reset()
            except Exception: pass
            while time.time() < _wake_cooldown_until:
                time.sleep(0.1)
            try:
                for key in oww.prediction_buffer:
                    oww.prediction_buffer[key] = [0.0] * len(oww.prediction_buffer[key])
            except Exception: pass

def _stop_recording():
    global recording, _wake_cooldown_until
    if not recording: return
    recording = False
    _wake_cooldown_until = time.time() + 2.0
    app.root.after(0, app.stop_wave)
    app.root.after(0, lambda: app.set_state("transcribing"))
    frames = list(audio_frames)
    def _finish():
        resume_media()
        play_sound("stop")
        if frames:
            _process(frames)
        else:
            app.set_state("idle")
    threading.Thread(target=_finish, daemon=True).start()

def _process(frames):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name
    try:
        save_wav(frames, wav_path)
        transcribe_and_type(wav_path, frames)
    finally:
        os.unlink(wav_path)

def on_press(key):
    global recording, audio_frames, cancelled
    if key in current_keys: return
    current_keys.add(key)
    record_key = get_record_key()
    ctrl = Key.ctrl in current_keys or Key.ctrl_l in current_keys or Key.ctrl_r in current_keys
    is_z = hasattr(key, "char") and key.char == "z"
    is_comma = hasattr(key, "char") and key.char in (",", "d")

    if key == record_key and not recording:
        recording = True
        _wake_active.set()
        globals()["_wake_cooldown_until"] = time.time() + 2.0
        audio_frames = []
        cancelled = False
        with wake_lock:
            wake_frames.clear()
        app.capture_active_app()
        app.set_state("recording")
        app.root.after(0, app.start_wave)
        play_sound("start")
        threading.Thread(target=pause_media, daemon=True).start()
        globals()["_recording_had_audio"] = False
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
        _scratch_last(1)
    elif ctrl and is_comma:
        app.open_settings()

def on_release(key):
    global recording, _wake_cooldown_until
    current_keys.discard(key)
    if key == get_record_key() and recording and not settings.get("toggle_mode", False):
        recording = False
        _wake_active.clear()
        _wake_cooldown_until = time.time() + 2.0
        app.root.after(0, app.stop_wave)
        frames = list(audio_frames)
        def _stop_and_process():
            resume_media()
            play_sound("stop")
            if frames:
                _process(frames)
            else:
                app.set_state("idle")
        threading.Thread(target=_stop_and_process, daemon=True).start()

class MenuBarApp:
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
                    if app: threading.Thread(target=lambda: app.root.after(0, app.root.deiconify if settings["show_hud"] else app.root.withdraw), daemon=True).start()
                def openSettings_(self, sender):
                    if app: threading.Thread(target=lambda: app.root.after(0, app._show_settings), daemon=True).start()
                def showSnippets_(self, sender):
                    if app: threading.Thread(target=lambda: app.root.after(0, app._show_snippets), daemon=True).start()
                def selectModel_(self, sender):
                    new_model = sender.title()
                    if new_model == settings.get("model"): return
                    settings["model"] = new_model
                    save_settings(settings)
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
                    if app: threading.Thread(target=lambda: app.root.after(0, _show_history), daemon=True).start()

            self._delegate = MenuDelegate.alloc().init()
            bar = NSStatusBar.systemStatusBar()
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

            model_menu = NSMenu.alloc().init()
            model_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Model", None, "")
            for m in ["tiny.en","base.en","small.en","medium.en","large-v2","large-v3","distil-medium.en","distil-large-v3"]:
                mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(m, "selectModel:", "")
                mi.setTarget_(self._delegate)
                if m == settings.get("model"): mi.setState_(1)
                model_menu.addItem_(mi)
            model_item.setSubmenu_(model_menu)
            self._menu.addItem_(model_item)
            self._model_menu = model_menu

            hotkey_menu = NSMenu.alloc().init()
            hotkey_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Record Key", None, "")
            for k in ["Right Command", "Right Option", "Right Control", "F13", "F14", "F15"]:
                hi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(k, "selectHotkey:", "")
                hi.setTarget_(self._delegate)
                if k == settings.get("hotkey_label"): hi.setState_(1)
                hotkey_menu.addItem_(hi)
            hotkey_item.setSubmenu_(hotkey_menu)
            self._menu.addItem_(hotkey_item)
            self._menu.addItem_(NSMenuItem.separatorItem())

            for title, action in [("Settings", "openSettings:"), ("Manage Snippets", "showSnippets:"), ("Show History", "showHistory:")]:
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
                item.setTarget_(self._delegate)
                self._menu.addItem_(item)
            self._menu.addItem_(NSMenuItem.separatorItem())
            
            quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit", "quitApp:", "")
            quit_item.setTarget_(self._delegate)
            self._menu.addItem_(quit_item)
            self._item.setMenu_(self._menu)
            self._available = True
        except Exception:
            self._available = False

    def _set_icon(self, state):
        if not self._available: return
        icon_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.argv[0])))
        path = os.path.join(icon_dir, f"icon_{state}.png")
        if os.path.exists(path):
            img = self._NSImage.alloc().initWithContentsOfFile_(path)
            if img:
                img.setSize_((18, 18))
                img.setTemplate_(True)
                self._item.button().setImage_(img)
                self._item.button().setTitle_("")
                return
        self._item.button().setImage_(None)
        self._item.button().setTitle_({"idle": "🎙️", "recording": "🔴", "transcribing": "⏳"}.get(state, "🎙️"))

    # FIXED: Menubar correctly sets title logic without printing dictionaries
    def set_state(self, state):
        if not self._available: return
        def _update():
            self._set_icon(state)
            labels = {"idle": "Idle", "recording": "Recording...", "transcribing": "Transcribing..."}
            self._status_item.setTitle_(f"Status: {labels.get(state, state.capitalize())}")
        if app and app.root:
            app.root.after(0, _update)

    def _update_hud_label(self):
        if self._available:
            self._toggle_item.setTitle_("Hide HUD" if settings.get("show_hud", True) else "Show HUD")

menubar = None

class DictationApp:
    BG, PILL, TEXT_WHITE, TEXT_DIM, RED, BLUE, GREEN, ORANGE, W, H = "#1c1c1c", "#242424", "#ffffff", "#4a4a4a", "#ff3b30", "#0a84ff", "#30d158", "#ff9f0a", 420, 52

    def __init__(self, root):
        self.root, self._ready, self._blink_job, self._blink_on, self._msg_timer = root, False, None, True, None
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
        self.root.attributes("-transparent", True)
        self.root.configure(bg="systemTransparent", highlightthickness=0)
        self.root.resizable(False, False)
        self.root.focus_set()
        try:
            from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
            NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
            self.root.update_idletasks()
            for win in NSApplication.sharedApplication().windows():
                win.setIgnoresMouseEvents_(False)
                win.setAcceptsMouseMovedEvents_(False)
                win.setCanBecomeKey_(False)
                win.setCanBecomeMain_(False)
        except Exception: pass
        sw = self.root.winfo_screenwidth()
        self.root.geometry(f"{self.W}x{self.H}+{settings.get('hud_x', sw//2 - self.W//2)}+{settings.get('hud_y', 24)}")
        self._build()
        self._make_draggable()

    def _build(self):
        self.canvas = tk.Canvas(self.root, width=self.W, height=self.H, bg="systemTransparent", highlightthickness=0, takefocus=0)
        self.canvas.pack()
        points = [18, 0, self.W-18, 0, self.W, 0, self.W, 18, self.W, self.H-18, self.W, self.H, self.W-18, self.H, 18, self.H, 0, self.H, 0, self.H-18, 0, 18, 0, 0]
        self.canvas.create_polygon(points, smooth=True, fill=self.PILL, outline="")
        self.dot = self.canvas.create_oval(20, self.H//2-6, 32, self.H//2+6, fill=self.TEXT_DIM, outline="")
        self.canvas.create_line(46, 14, 46, self.H-14, fill="#303030", width=1)
        self.label = self.canvas.create_text(80, self.H//2, text="Loading model...", font=("Helvetica Neue", 13), fill=self.TEXT_DIM, anchor="w", width=260)
        self.appname = self.canvas.create_text(self.W-38, self.H//2, text="", font=("Helvetica Neue", 11), fill=self.TEXT_DIM, anchor="e")
        self.appicon = self.canvas.create_image(self.W-22, self.H//2, anchor="e")
        self.canvas.create_text(self.W-14, self.H//2, text="✕", font=("Helvetica", 10), fill=self.TEXT_DIM, anchor="center", tags="close")
        self.canvas.tag_bind("close", "<Button-1>", lambda e: os._exit(0))
        self.canvas.tag_bind("close", "<Enter>", lambda e: self.canvas.itemconfig("close", fill=self.TEXT_WHITE))
        self.canvas.tag_bind("close", "<Leave>", lambda e: self.canvas.itemconfig("close", fill=self.TEXT_DIM))

    def _make_draggable(self):
        def start(e):
            if self._ready: self._drag_x, self._drag_y = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()
        def move(e):
            if self._ready:
                x, y = e.x_root - self._drag_x, e.y_root - self._drag_y
                self.root.geometry(f"+{x}+{y}")
                settings["hud_x"], settings["hud_y"] = x, y
                save_settings(settings)
        self.canvas.bind("<ButtonPress-1>", start)
        self.canvas.bind("<B1-Motion>", move)

    def capture_active_app(self):
        def _fetch():
            try:
                from AppKit import NSWorkspace
                from PIL import Image, ImageTk
                import io
                ws = NSWorkspace.sharedWorkspace()
                appo = ws.frontmostApplication()
                path = appo.bundleURL().path() if appo and appo.bundleURL() else None
                if path:
                    icon_ns = ws.iconForFile_(path)
                    icon_ns.setSize_((48, 48))
                    img = Image.open(io.BytesIO(bytes(icon_ns.TIFFRepresentation()))).convert("RGBA")
                    bbox = img.getbbox()
                    if bbox: img = img.crop(bbox)
                    img = img.resize((32, 32), Image.LANCZOS)
                    def _update_icon(i=img):
                        try:
                            photo = ImageTk.PhotoImage(i)
                            self._app_icon = photo
                            self.canvas.itemconfig(self.appicon, image=photo)
                            self.canvas.itemconfig(self.appname, text="")
                        except Exception: pass
                    self.root.after(0, _update_icon)
                    return
            except Exception: pass
            self.root.after(0, lambda: self.canvas.itemconfig(self.appname, text=(get_active_app_name() or "")[:8]))
        threading.Thread(target=_fetch, daemon=True).start()

    def set_state(self, state):
        self.root.after(0, self._apply_state, state)

    def _apply_state(self, state):
        if self._blink_job:
            self.root.after_cancel(self._blink_job)
            self._blink_job = None
        if state != "recording":
            self.stop_wave()
        if state == "idle":
            self.canvas.itemconfig(self.dot, fill=self.TEXT_DIM)
            self.canvas.itemconfig(self.label, text=f"{'Press' if settings.get('toggle_mode') else 'Hold'} {settings.get('hotkey_label', 'Right Option')} to dictate", fill=self.TEXT_DIM)
        elif state == "recording":
            self.canvas.itemconfig(self.dot, fill=self.RED)
            self.canvas.itemconfig(self.label, text=f"Recording... {'press' if settings.get('toggle_mode') else 'release'} to stop", fill=self.TEXT_WHITE)
        elif state == "transcribing":
            self.canvas.itemconfig(self.dot, fill=self.BLUE)
            self.canvas.itemconfig(self.label, text="Transcribing...", fill=self.BLUE)
            
        if menubar:
            menubar.set_state(state)

    def set_transcript(self, text):
        self.root.after(0, lambda: (self.canvas.itemconfig(self.dot, fill=self.GREEN), self.canvas.itemconfig(self.label, text=text if len(text) <= 48 else text[:45] + "...", fill=self.TEXT_WHITE)))

    def show_snippet_step(self, step, trigger=""):
        def _show():
            if self._msg_timer: self.root.after_cancel(self._msg_timer)
            if step == 1:
                self.canvas.itemconfig(self.dot, fill=self.BLUE)
                self.canvas.itemconfig(self.label, text="Step 1: Say ONLY the trigger word/phrase", fill=self.BLUE)
            elif step == 2:
                self.canvas.itemconfig(self.dot, fill=self.BLUE)
                self.canvas.itemconfig(self.label, text=f"Step 2: '{trigger[:17] + '...' if len(trigger) > 20 else trigger}' saved — say the full content", fill=self.BLUE)
            elif step == 3:
                self.canvas.itemconfig(self.dot, fill=self.GREEN)
                self.canvas.itemconfig(self.label, text="Snippet saved!", fill=self.GREEN)
                self._msg_timer = self.root.after(3000, lambda: self._apply_state("idle"))
        self.root.after(0, _show)

    def show_message(self, msg, color=None):
        def _show():
            if self._msg_timer: self.root.after_cancel(self._msg_timer)
            self.canvas.itemconfig(self.dot, fill=color or self.ORANGE)
            self.canvas.itemconfig(self.label, text=msg, fill=color or self.ORANGE)
            self._msg_timer = self.root.after(5000, lambda: self._apply_state("idle"))
        self.root.after(0, _show)

    def start_wave(self):
        self.canvas.itemconfig(self.dot, state="hidden")
        self._bars = []
        for i in range(14):
            self._bars.append(self.canvas.create_rectangle(8 + i * 5, self.H//2-1, 8 + i * 5 + 3, self.H//2+1, fill=self.RED, outline=""))
        self._wave_phase = 0.0
        if recording:
            self._wave_job = self.root.after(30, self._animate_wave)
        else:
            self.root.after(0, self.stop_wave)

    def _animate_wave(self):
        if not hasattr(self, '_bars') or not self._bars: return
        import math
        scale = min(1.0, get_current_rms() * 18 + 0.15)
        self._wave_phase += 0.18
        for i, bar in enumerate(self._bars):
            dist = abs(i - 7) / 7
            height = max(2, int((self.H//2 - 6) * scale * (math.sin(self._wave_phase + i * 0.55) * 0.5 + 0.5) * (1 - dist * 0.5)))
            brightness = int(255 * (1 - dist * 0.65))
            x1, _, x2, _ = self.canvas.coords(bar)
            self.canvas.coords(bar, x1, self.H//2 - height, x2, self.H//2 + height)
            self.canvas.itemconfig(bar, fill=f"#{brightness:02x}{int(brightness*0.18):02x}{int(brightness*0.12):02x}")
        if recording:
            self._wave_job = self.root.after(30, self._animate_wave)
        else:
            self.root.after(0, self.stop_wave)

    def stop_wave(self):
        job = getattr(self, '_wave_job', None)
        self._wave_job = None
        if job: self.root.after_cancel(job)
        if hasattr(self, '_bars'):
            for bar in self._bars:
                try: self.canvas.delete(bar)
                except Exception: pass
            self._bars = []
        try: self.canvas.itemconfig(self.dot, state="normal")
        except Exception: pass

    def _show_snippets(self, parent=None):
        BG, CARD, SEP, ACC, FG, DIM = "#1c1c1e", "#242424", "#2c2c2e", "#0a84ff", "#ffffff", "#8e8e93"
        swin = tk.Toplevel(self.root)
        swin.title("Snippets")
        swin.geometry("660x520")
        swin.configure(bg=BG)
        swin.attributes("-topmost", True)
        swin.attributes("-alpha", 0.97)
        try: swin.tk.call("::tk::unsupported::MacWindowStyle", "style", swin._w, "plain", "none")
        except Exception: pass

        tb = tk.Frame(swin, bg=BG, height=48)
        tb.pack(fill="x")
        tb.pack_propagate(False)
        tk.Label(tb, text="Snippets", bg=BG, fg=FG, font=("Helvetica Neue", 14, "bold")).place(relx=0.5, rely=0.5, anchor="center")
        x_lbl = tk.Label(tb, text="✕", bg=BG, fg=DIM, font=("Helvetica Neue", 14), cursor="hand2")
        x_lbl.place(x=16, y=14)
        x_lbl.bind("<Button-1>", lambda e: swin.destroy())
        tk.Frame(swin, bg=SEP, height=1).pack(fill="x")

        sf = tk.Frame(swin, bg=BG)
        sf.pack(fill="x", padx=16, pady=(12,8))
        tk.Label(sf, text="⌕", bg=BG, fg=DIM, font=("Helvetica Neue", 16)).pack(side="left", padx=(0,8))
        search_var = tk.StringVar()
        tk.Entry(sf, textvariable=search_var, bg=CARD, fg=FG, font=("Helvetica Neue", 13), relief="flat", insertbackground=FG, bd=0).pack(side="left", fill="x", expand=True, ipady=7)

        body = tk.Frame(swin, bg=BG)
        body.pack(fill="both", expand=True)
        left = tk.Frame(body, bg=BG, width=210)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        lc = tk.Canvas(left, bg=BG, highlightthickness=0)
        ls = tk.Scrollbar(left, orient="vertical", command=lc.yview)
        li = tk.Frame(lc, bg=BG)
        lc.create_window((0,0), window=li, anchor="nw")
        lc.configure(yscrollcommand=ls.set)
        lc.pack(side="left", fill="both", expand=True)
        ls.pack(side="right", fill="y")
        tk.Frame(body, bg=SEP, width=1).pack(side="left", fill="y")

        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=20, pady=16)
        tk.Label(right, text="TRIGGER", bg=BG, fg=DIM, font=("Helvetica Neue", 9, "bold")).pack(anchor="w")
        trigger_var = tk.StringVar()
        trigger_entry = tk.Entry(right, textvariable=trigger_var, bg=CARD, fg=FG, font=("Helvetica Neue", 14), relief="flat", insertbackground=FG, bd=0)
        trigger_entry.pack(fill="x", ipady=8, pady=(4,16))
        tk.Label(right, text="EXPANSION", bg=BG, fg=DIM, font=("Helvetica Neue", 9, "bold")).pack(anchor="w")
        content_text = tk.Text(right, bg=CARD, fg=FG, font=("Helvetica Neue", 13), relief="flat", insertbackground=FG, wrap="word", height=8, padx=10, pady=10, bd=0)
        content_text.pack(fill="both", expand=True, pady=(4,0))

        selected, rows = [None], {}

        def select(t, c):
            selected[0] = t
            trigger_var.set(t)
            content_text.delete("1.0", tk.END)
            content_text.insert("1.0", c)
            for k, b in rows.items():
                b.configure(bg=ACC if k == t else BG, fg=FG if k == t else DIM)

        def refresh(q=""):
            for w in li.winfo_children(): w.destroy()
            rows.clear()
            snips = load_snippets()
            shown = {t: c for t, c in snips.items() if not q or q.lower() in t.lower() or q.lower() in c.lower()}
            if not shown:
                tk.Label(li, text="No snippets", bg=BG, fg=DIM, font=("Helvetica Neue", 12)).pack(pady=20, padx=12)
                return
            for t, c in shown.items():
                b = tk.Button(li, text=f"  {t}", anchor="w", bg=ACC if t == selected[0] else BG, fg=FG if t == selected[0] else DIM, font=("Helvetica Neue", 12), relief="flat", padx=8, pady=10, command=lambda tt=t, cc=c: select(tt, cc))
                b.pack(fill="x")
                rows[t] = b
            if selected[0] not in shown:
                try: select(next(iter(shown)), shown[next(iter(shown))])
                except StopIteration: pass

        search_var.trace_add("write", lambda *a: refresh(search_var.get()))
        refresh()

        bot = tk.Frame(swin, bg=BG)
        bot.pack(fill="x", padx=16, pady=12)
        def save_sel():
            t, c = trigger_var.get().strip().lower(), content_text.get("1.0", tk.END).strip()
            if not t or not c: return
            s = load_snippets()
            s.pop(selected[0], None)
            s[t] = c
            with open(SNIPPETS_FILE, "w") as f: json.dump(s, f, indent=2)
            selected[0] = t
            refresh(search_var.get())
            self.show_message(f"Saved '{t}'", self.GREEN)

        tk.Button(bot, text="+ New", command=lambda: (selected.__setitem__(0, None), trigger_var.set(""), content_text.delete("1.0", tk.END), trigger_entry.focus_set()), bg=CARD, fg=FG, relief="flat", padx=16, pady=8).pack(side="left")
        tk.Button(bot, text="Save", command=save_sel, bg=ACC, fg=FG, relief="flat", padx=16, pady=8).pack(side="right")

    def open_settings(self):
        self.root.after(0, self._show_settings)
    
    def _show_settings(self):
        BG, CARD, SEP, ACC, FG, DIM = "#1c1c1e", "#242424", "#2c2c2e", "#0a84ff", "#ffffff", "#8e8e93"
        _win = tk.Toplevel(self.root)
        _win.title("Settings")
        _win.geometry("400x680")
        _win.configure(bg=BG)
        _win.attributes("-topmost", True)
        
        tb = tk.Frame(_win, bg=BG, height=48)
        tb.pack(fill="x")
        tk.Label(tb, text="Settings", bg=BG, fg=FG, font=("Helvetica Neue", 14, "bold")).place(relx=0.5, rely=0.5, anchor="center")
        tk.Button(tb, text="✕", command=_win.destroy, bg=BG, fg=DIM, relief="flat").place(x=16, y=14)
        
        canvas = tk.Canvas(_win, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(_win, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=BG)
        
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        model_var = tk.StringVar(value=settings["model"])
        hotkey_var = tk.StringVar(value=settings.get("hotkey_label", "Right Option"))
        cloud_var = tk.BooleanVar(value=settings.get("cloud_mode", False))
        key_var = tk.StringVar(value=settings.get("openai_key", ""))
        
        hud_var = tk.BooleanVar(value=settings.get("show_hud", True))
        toggle_var = tk.BooleanVar(value=settings.get("toggle_mode", True))
        wake_var = tk.BooleanVar(value=settings.get("wake_enabled", True))
        jarvis_var = tk.BooleanVar(value=settings.get("jarvis_enabled", True))
        format_var = tk.BooleanVar(value=settings.get("context_format", True))
        auto_var = tk.BooleanVar(value=settings.get("auto_detect", True))

        def section(text):
            tk.Label(scrollable_frame, text=text, bg=BG, fg=DIM, font=("Helvetica Neue", 9, "bold")).pack(anchor="w", padx=20, pady=(18,6))
        
        section("TRANSCRIPTION")
        ttk.Combobox(scrollable_frame, textvariable=model_var, values=["tiny.en","base.en","small.en","medium.en","large-v2","large-v3"], state="readonly").pack(pady=5)
        
        section("HOTKEYS")
        ttk.Combobox(scrollable_frame, textvariable=hotkey_var, values=list(HOTKEY_OPTIONS.keys()), state="readonly").pack(pady=5)
        
        section("SETTINGS")
        tk.Checkbutton(scrollable_frame, text="Show HUD", variable=hud_var, bg=BG, fg=FG, selectcolor=CARD).pack(anchor="w", padx=20, pady=2)
        tk.Checkbutton(scrollable_frame, text="Toggle Mode (Press to Start/Stop)", variable=toggle_var, bg=BG, fg=FG, selectcolor=CARD).pack(anchor="w", padx=20, pady=2)
        tk.Checkbutton(scrollable_frame, text="Wake Word", variable=wake_var, bg=BG, fg=FG, selectcolor=CARD).pack(anchor="w", padx=20, pady=2)
        tk.Checkbutton(scrollable_frame, text="Jarvis Commands", variable=jarvis_var, bg=BG, fg=FG, selectcolor=CARD).pack(anchor="w", padx=20, pady=2)
        tk.Checkbutton(scrollable_frame, text="Context-Aware Formatting", variable=format_var, bg=BG, fg=FG, selectcolor=CARD).pack(anchor="w", padx=20, pady=2)
        tk.Checkbutton(scrollable_frame, text="Auto-Detect Language", variable=auto_var, bg=BG, fg=FG, selectcolor=CARD).pack(anchor="w", padx=20, pady=2)
        tk.Checkbutton(scrollable_frame, text="Cloud Mode (OpenAI)", variable=cloud_var, bg=BG, fg=FG, selectcolor=CARD).pack(anchor="w", padx=20, pady=2)
        
        section("OPENAI KEY")
        tk.Entry(scrollable_frame, textvariable=key_var, show="*").pack(pady=5)

        def save_and_close():
            settings.update({
                "model": model_var.get(), 
                "hotkey_label": hotkey_var.get(), 
                "show_hud": hud_var.get(), 
                "toggle_mode": toggle_var.get(), 
                "wake_enabled": wake_var.get(), 
                "cloud_mode": cloud_var.get(), 
                "openai_key": key_var.get(), 
                "jarvis_enabled": jarvis_var.get(), 
                "context_format": format_var.get(),
                "auto_detect": auto_var.get()
            })
            globals().update({"WAKE_ENABLED": wake_var.get(), "JARVIS_ENABLED": jarvis_var.get()})
            save_settings(settings)
            _win.destroy()
            self.show_message("Saved! Restart to apply.", self.GREEN)

        tk.Button(scrollable_frame, text="Save All Settings", command=save_and_close, bg=ACC, fg=FG, width=20).pack(pady=30)

def reload_model():
    global whisper, MODEL
    model_name = settings["model"]
    app.root.after(0, lambda: app.show_message(f"Loading {model_name}...", "#0a84ff"))
    try:
        whisper = WhisperModel(model_name, device=DEVICE, compute_type=COMPUTE)
        MODEL = model_name
        app.root.after(0, lambda: app.show_message(f"{model_name} ready!", "#30d158"))
    except Exception:
        app.root.after(0, lambda: app.show_message(f"Failed to load {model_name}", "#ff3b30"))
        settings["model"] = "small.en"
        save_settings(settings)
    time.sleep(4.0)
    app.set_state("idle")

def start_backend(stream):
    global whisper, JARVIS_ENABLED
    JARVIS_ENABLED = settings.get("jarvis_enabled", True)
    time.sleep(1.5)
    try:
        whisper = WhisperModel(MODEL, device=DEVICE, compute_type=COMPUTE)
    except Exception:
        try:
            whisper = WhisperModel("tiny.en", device=DEVICE, compute_type=COMPUTE)
            settings["model"] = "tiny.en"
            save_settings(settings)
        except Exception:
            app.root.after(0, lambda: app.show_message("No Whisper model found.", "#ff3b30"))
            app.set_state("idle")
            return
    app._ready = True
    app.set_state("idle")
    threading.Thread(target=_wake_word_loop, daemon=True).start()
    with keyboard.Listener(on_press=on_press, on_release=on_release):
        stream.start()
        threading.Event().wait()

def main():
    global app, menubar
    root = tk.Tk()
    root.tk.call('tk', 'windowingsystem')
    app = DictationApp(root)
    if not settings.get("show_hud", True):
        root.withdraw()
    stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", device=MIC_DEVICE, callback=audio_callback)
    threading.Thread(target=start_backend, args=(stream,), daemon=True).start()
    root.after(500, _init_menubar)
    root.mainloop()

def _init_menubar():
    global menubar
    try:
        from Foundation import NSObject
        import objc
        class _Trampoline(NSObject):
            def create_(self, _):
                global menubar
                menubar = MenuBarApp()
        t = _Trampoline.alloc().init()
        t.performSelectorOnMainThread_withObject_waitUntilDone_(objc.selector(t.create_, selector=b"create:"), None, True)
    except Exception:
        menubar = MenuBarApp()

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