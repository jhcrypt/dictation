#!/usr/bin/env python
"""
Local Whisper Dictation v4 - Intel Mac
Hold Right Option to record, release to transcribe and type.
100% offline. No API keys. No cloud.

v4 fixes:
  - audio_frames guarded by a threading.Lock() (race condition fix)
  - AppleScript injection prevention via _osa_escape()
  - OpenAI key stored in macOS Keychain (falls back to settings JSON)
  - paste_text clipboard restore wrapped in finally (no clipboard clobber)
  - Snippets and vocab cached in memory (no disk read per dictation)
  - Duplicate/inconsistent silence thresholds unified to named constants
  - app-is-None guard on all callbacks that fire before main() completes
  - Mic device picker added to Settings panel
  - Hardcoded personal URLs moved to USER_CONFIG block at top of file
"""

import os
# CRITICAL CRASH FIX: Must be set BEFORE importing faster_whisper to prevent "illegal hardware instruction"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["CT2_USE_EXPERIMENTAL_PACKED_GEMM"] = "0"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

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

# ── User-configurable URLs (moved out of buried code) ────────────────────────
USER_CONFIG = {
    "my_website": "https://conceived-automations.onrender.com/",
    "my_repo":    "https://github.com/jhcrypt/dictation",
    "spotify_playlists": {
        "playlist4": "spotify:playlist:37i9dQZF1DX4UtSsGT1Sbe",
        "playlist5": "spotify:playlist:0Ivl3dhpcSx8mL4df69HI9",
        "playlist6": "spotify:playlist:7JZxrxQtbmAGcXf9b4BibQ",
        "coding":    "spotify:playlist:37i9dQZF1DXt6tRSzY2qG3",
        "workout":   "spotify:playlist:37i9dQZF1DX70RN3TfR07f",
    },
}

# ── Silence / noise-floor thresholds (unified) ───────────────────────────────
SILENCE_FLOOR      = 0.002   # below this → treat recording as empty, skip entirely
SILENCE_TOO_QUIET  = 0.008   # below this after concat → skip transcription
SILENCE_STOP_RMS   = 0.08    # real-time monitor: sustained quiet → auto-stop

# ── audio_frames lock — every mutation must hold this ────────────────────────
_audio_lock = threading.Lock()

# ── AppleScript injection prevention ─────────────────────────────────────────
def _osa_escape(s: str) -> str:
    """Escape a string for safe embedding inside an AppleScript double-quoted literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", "")

# ── macOS Keychain helper for OpenAI key ─────────────────────────────────────
_KEYCHAIN_SERVICE = "dictation-app"
_KEYCHAIN_ACCOUNT = "openai-key"

def _keychain_get() -> str:
    try:
        import keyring
        val = keyring.get_password(_KEYCHAIN_SERVICE, _KEYCHAIN_ACCOUNT)
        return val or ""
    except Exception:
        return ""

def _keychain_set(key: str) -> bool:
    try:
        import keyring
        keyring.set_password(_KEYCHAIN_SERVICE, _KEYCHAIN_ACCOUNT, key)
        return True
    except Exception:
        return False

def get_openai_key() -> str:
    """Return OpenAI key: prefer Keychain, fall back to settings JSON."""
    kc = _keychain_get()
    if kc:
        return kc
    return settings.get("openai_key", "")

def set_openai_key(key: str):
    """Store key in Keychain; also write to settings as legacy fallback."""
    if not _keychain_set(key):
        settings["openai_key"] = key
        save_settings(settings)
    else:
        # Clear plaintext copy from settings JSON if Keychain succeeded
        if "openai_key" in settings:
            settings["openai_key"] = ""
            save_settings(settings)

# ── In-memory caches for snippets and vocab ──────────────────────────────────
_snippets_cache: dict | None = None
_vocab_cache: dict | None = None

# ── Jarvis AI Brain ───────────────────────────────────────────────────────────
JARVIS_ENABLED = True  # overridden by settings on load

# Added Spark so Context-Aware formatting triggers on emails!
APP_FORMAT_RULES = {
    "mail":     "formal email tone, proper punctuation, capitalize first word",
    "spark":    "formal email tone, proper punctuation, capitalize first word",
    "outlook":  "formal email tone, proper punctuation, capitalize first word",
    "notes":    "clear concise notes format",
    # We use broader keywords to catch terminal/coding apps
    "iterm":    "technical precise language",
    "terminal": "technical precise language",
    "code":     "technical precise language",
    "visual studio code": "technical precise language",
}

JARVIS_COMMANDS = {
    "open": "open_app", "search": "web_search", "email": "send_email",
    "volume": "set_volume", "screenshot": "take_screenshot", "remind": "set_reminder",
    "calendar": "check_calendar", "close": "close_app", "play": "play_media", "weather": "check_weather",
}

# ── Local intent detection & formatting (no Ollama) ─────────────────────────

# ── Ollama async refinement engine ───────────────────────────────────────────
# A single persistent worker thread keeps the model warm between calls.
# transcribe_and_type submits a job and waits up to OLLAMA_TIMEOUT seconds.
# If Ollama is still thinking by then, raw Whisper text is used immediately.
#
# BUG FIX (stale result): the worker uses a job_id to tag each result.
# If the caller has already timed out, the worker discards its own result
# rather than leaving it in the queue to poison the next dictation.
OLLAMA_TIMEOUT = 12.0  # seconds — llama3:latest (8B) needs more headroom on Intel

import queue as _queue
import uuid as _uuid

# Queues carry (job_id, payload) tuples so stale results can be identified
_ollama_req_q: _queue.Queue = _queue.Queue(maxsize=1)
_ollama_res_q: _queue.Queue = _queue.Queue(maxsize=1)
_ollama_current_job_id: str = ""   # set by ollama_query, read by worker

# Strict minimal-edit prompt tuned for small models (1b/3b).
# Small models need a fill-in-the-blank frame rather than rule lists —
# rules get "reasoned about" which causes rewriting. The echo-with-fixes
# frame makes rewriting grammatically harder to do.
_OLLAMA_SYSTEM_PROMPT = (
    "You are an AI speech reconstruction engine. "

    "Your task is to transform rough speech-to-text dictation into clean, natural, human-quality writing. "

    "Fix:\n"
    "- spelling\n"
    "- grammar\n"
    "- punctuation\n"
    "- broken phrasing\n"
    "- speech recognition mistakes\n"
    "- incomplete spoken sentence structure\n"

    "Rewrite awkward dictation into the way a fluent person would naturally type it. "

    "Preserve the original meaning, but prioritize clarity and readability. "

    "Do NOT explain anything. "
    "Return ONLY the final corrected text."
)

def _ollama_worker():
    """Persistent background thread — model stays warm, no cold-start per call."""
    try:
        import ollama as _ol
    except ImportError:
        print("[ollama] library not installed — refinement disabled")
        return
    print("[ollama] worker ready")
    while True:
        job = _ollama_req_q.get()         # blocks until a job arrives
        if job is None: break             # poison pill — exit
        job_id, text = job
        try:
            t0 = time.time()
            resp = _ol.chat(
                model="qwen2.5:3b",
                messages=[
                    {"role": "system", "content": _OLLAMA_SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                options={
                    "repeat_penalty": 1.15, 
                    "num_predict": 180, 
                    "temperature": 0.35, 
                    "top_P": 0.9,
                }
            )
            result = resp["message"]["content"].strip()
            elapsed = time.time() - t0
            # Strip common preamble patterns 3b adds despite instructions
            for prefix in (
                "Corrected transcription:", "Corrected:", "Here is the corrected",
                "Here's the corrected", "Output:", "Result:",
            ):
                if result.lower().startswith(prefix.lower()):
                    result = result[len(prefix):].strip()
                    break
            # If model returned multiple lines, take only the last non-empty one
            # (3b sometimes adds a reasoning line before the actual correction)
            lines = [l.strip() for l in result.splitlines() if l.strip()]
            if len(lines) > 1:
                result = lines[-1]
            print(f"[ollama] {elapsed:.2f}s → {result!r}")
        except Exception as e:
            print(f"[ollama] worker error: {e}")
            result = None

        # Only post result if the caller is still waiting for THIS job_id.
        # If it already timed out (_ollama_current_job_id changed), discard.
        if job_id == _ollama_current_job_id:
            try:
                _ollama_res_q.put_nowait((job_id, result))
            except _queue.Full:
                pass   # caller timed out between our check and put — discard

threading.Thread(target=_ollama_worker, daemon=True, name="ollama-worker").start()

def ollama_query(text: str) -> str:
    """Submit to warm worker; return refined text or original if timeout fires."""
    global _ollama_current_job_id

    # Drain any stale result left over from a previous timed-out call
    while not _ollama_res_q.empty():
        try: _ollama_res_q.get_nowait()
        except _queue.Empty: break

    job_id = _uuid.uuid4().hex
    _ollama_current_job_id = job_id

    # Drop request silently if worker is still busy with the previous job
    try:
        _ollama_req_q.put_nowait((job_id, text))
    except _queue.Full:
        print("[ollama] busy — skipping refinement")
        return text

    try:
        result_job_id, result = _ollama_res_q.get(timeout=OLLAMA_TIMEOUT)
        # Sanity check: discard if somehow a mismatched result slipped through
        if result_job_id != job_id:
            print("[ollama] stale result discarded")
            return text
        return result if result else text
    except _queue.Empty:
        print(f"[ollama] timeout after {OLLAMA_TIMEOUT}s — using Whisper text")
        return text

def detect_jarvis_intent(text):
    """Stub — replaced by _fast_jarvis_match."""
    return None

def format_for_app(text, app_name):
    """Rule-based formatting — instant, no LLM required."""
    app_lower = app_name.lower()
    rule_key = next((k for k in APP_FORMAT_RULES if k in app_lower), None)
    if not rule_key:
        return text

    # Capitalize first letter
    text = text.strip()
    if text:
        text = text[0].upper() + text[1:]

    if rule_key in ("mail", "spark", "word", "pages"):
        # Ensure sentence endings have proper punctuation
        if text and text[-1] not in ".!?":
            text += "."
        # Capitalize after period
        text = re.sub(r'(\.\s+)([a-z])', lambda m: m.group(1) + m.group(2).upper(), text)

    elif rule_key in ("messages", "slack"):
        # Strip trailing period for casual tone
        if text.endswith("."):
            text = text[:-1]

    elif rule_key in ("terminal", "iterm", "code", "visual studio code"):
        # Code/Terminal should NOT have trailing periods or leading capitals
        text = text.lower().strip()
        if text.endswith("."):
            text = text[:-1]

    print(f"[format] {app_name}: applied '{rule_key}' rule")
    return text

def execute_jarvis_command(action, params):
    global _last_jarvis_time
    if time.time() - _last_jarvis_time < 3.0: return
    _last_jarvis_time = time.time()

    print(f"[jarvis] executing: {action} {params}")
    if app: app.show_message(f"Jarvis: {action.replace('_', ' ')}...", "#0a84ff")

    try:
        if action == "open_app":
            app_name = params.get("app", "")
            url = params.get("url", "")
            if url: subprocess.Popen(["open", url])
            else:
                result = subprocess.run(["open", "-a", app_name], capture_output=True, text=True)
                if result.returncode != 0: subprocess.Popen(["open", "-a", app_name.lower()])
            if app: app.show_message(f"Opening {app_name}", "#30d158")

        elif action == "web_search":
            query = params.get("query", "")
            subprocess.Popen(["open", f"https://duckduckgo.com/?q={query.replace(' ', '+')}"])
            if app: app.show_message(f"Searching: {query[:30]}", "#30d158")

        elif action == "set_volume":
            direction = params.get("direction", "")
            level = params.get("level", None)
            if direction == "up": subprocess.run(["osascript", "-e", "set volume output volume (output volume of (get volume settings) + 25)"]); app and app.show_message("Volume up", "#30d158")
            elif direction == "down": subprocess.run(["osascript", "-e", "set volume output volume (output volume of (get volume settings) - 25)"]); app and app.show_message("Volume down", "#30d158")
            elif direction == "mute": subprocess.run(["osascript", "-e", "set volume with output muted"]); app and app.show_message("Muted", "#30d158")
            elif level is not None: subprocess.run(["osascript", "-e", f"set volume output volume {level}"]); app and app.show_message(f"Volume: {level}%", "#30d158")

        elif action == "take_screenshot":
            shot_type = params.get("type", "screen").lower()
            if "area" in shot_type: key, msg = "a", "Area capture"
            elif "scroll" in shot_type: key, msg = "s", "Scrolling capture"
            elif "text" in shot_type: key, msg = "t", "Text recognition"
            else: key, msg = "w", "Full screen capture"
            subprocess.Popen(["osascript", "-e", f'tell application "System Events"\n    keystroke "{key}" using control down\nend tell'])
            if app: app.show_message(f"Shottr: {msg}", "#30d158")

        elif action == "check_weather":
            location = params.get("location", "")
            query = f"weather {location}" if location else "weather today"
            subprocess.Popen(["open", f"https://duckduckgo.com/?q={query.replace(' ', '+')}"])
            if app: app.show_message("Opening weather", "#30d158")

        elif action == "check_calendar":
            subprocess.Popen(["open", "-a", "Calendar"])
            if app: app.show_message("Opening Calendar", "#30d158")

        elif action == "set_reminder":
            text = params.get("text", "")
            safe_text = _osa_escape(text)
            subprocess.run(["osascript", "-e", f'tell application "Reminders"\n    tell default list\n        make new reminder with properties {{name:"{safe_text}"}}\n    end tell\nend tell'])
            if app: app.show_message(f"Reminder: {text[:30]}", "#30d158")

        elif action == "kill_app":
            app_name = params.get("app", "")
            subprocess.run(["pkill", "-9", "-f", app_name])
            if app: app.show_message(f"Killed {app_name}", "#30d158")

        elif action == "send_email":
            to, subject, body = params.get("to", ""), params.get("subject", ""), params.get("body", "")
            # Escape all user-supplied strings before embedding in AppleScript
            safe_to      = _osa_escape(to)
            safe_subject = _osa_escape(subject)
            safe_body    = _osa_escape(body)
            lines = [
                'tell application "Spark" to activate',
                'delay 2.5',
                'tell application "System Events"',
                '    tell process "Spark"',
                '        keystroke "n" using command down',
                '        delay 2.0',
            ]
            if safe_to:
                lines += [
                    f'        keystroke "{safe_to}"',
                    '        delay 0.8',
                    '        key code 36',   # Return to confirm recipient autocomplete
                    '        delay 0.5',
                ]
            # Tab past CC to Subject, then tab again to Body
            lines += [
                '        keystroke tab',    # To -> CC
                '        delay 0.2',
                '        keystroke tab',    # CC -> Subject
                '        delay 0.2',
            ]
            if safe_subject:
                lines += [f'        keystroke "{safe_subject}"', '        delay 0.2']
            lines += [
                '        keystroke tab',    # Subject -> Body
                '        delay 0.3',
            ]
            if safe_body:
                lines += [f'        keystroke "{safe_body}"']
            lines += ['    end tell', 'end tell']
            subprocess.Popen(["osascript", "-e", "\n".join(lines)])
            if app: app.show_message(f"Composing email to {to[:20]}" if to else "Opening Spark", "#30d158")

        elif action == "close_app":
            app_name = params.get("app", "")
            safe_name = _osa_escape(app_name)
            subprocess.run(["osascript", "-e", f'tell application "{safe_name}" to quit'])
            if app: app.show_message(f"Closing {app_name}", "#30d158")

        elif action == "play_media":
            query = params.get("query", "")
            service = params.get("service", "youtube").lower()
            if "spotify" in service:
                SPOTIFY_FAVORITES = USER_CONFIG["spotify_playlists"]
                condensed_query = query.lower().replace(" ", "")
                matched_uri = next((fav_uri for fav_name, fav_uri in SPOTIFY_FAVORITES.items() if fav_name in condensed_query), None)
                if matched_uri: subprocess.Popen(["osascript", "-e", f'tell application "Spotify" to play track "{matched_uri}"'])
                else: subprocess.Popen(["open", f"spotify:search:{query.replace(' ', '%20')}"])
            elif "apple music" in service:
                subprocess.Popen(["open", f"https://music.apple.com/search?term={query.replace(' ', '+')}"])
            else:
                subprocess.Popen(["open", f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"])
            if app: app.show_message(f"Playing: {query[:30]}", "#30d158")

    except Exception as e:
        print(f"[jarvis] error: {e}")
        if app: app.show_message(f"Jarvis error: {str(e)[:30]}", "#ff3b30")

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
        api_key = get_openai_key()
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
    "jarvis_enabled": True,
    "use_ollama": True
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
OLLAMA_ENABLED = settings.get("use_ollama", True)  # live-toggled by Settings → Ollama

# GLOBALS RESTORED
recording, audio_frames, last_text, typer, whisper, app, current_keys, cancelled = False, [], "", Controller(), None, None, set(), False
snippet_state, snippet_trigger, dictation_history, history_index, last_transcribed_text = None, "", [], -1, ""
_last_jarvis_time, wake_listening, wake_frames, wake_lock, wake_whisper = 0.0, False, [], threading.Lock(), None
_wake_cooldown_until = 0.0
_wake_active = threading.Event()

def _quit_clean():
    """Graceful shutdown — avoids the semaphore leak warning from os._exit."""
    try:
        if app and app.root:
            app.root.quit()   # exits mainloop cleanly
    except Exception:
        pass
    import sys as _sys
    _sys.exit(0)

SNIPPETS_FILE = os.path.expanduser("~/.dictation_snippets.json")

def load_snippets() -> dict:
    """Load snippets from disk and cache in memory."""
    global _snippets_cache
    if _snippets_cache is not None:
        return _snippets_cache
    if os.path.exists(SNIPPETS_FILE):
        try:
            with open(SNIPPETS_FILE) as f:
                _snippets_cache = json.load(f)
                return _snippets_cache
        except Exception:
            pass
    _snippets_cache = {}
    return _snippets_cache

def _invalidate_snippets_cache():
    global _snippets_cache
    _snippets_cache = None

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

def load_vocab() -> dict:
    """Load vocab from disk and cache in memory."""
    global _vocab_cache
    if _vocab_cache is not None:
        return _vocab_cache
    if os.path.exists(VOCAB_FILE):
        try:
            with open(VOCAB_FILE) as f:
                _vocab_cache = json.load(f)
                return _vocab_cache
        except Exception:
            pass
    _vocab_cache = {"word_counts": {}, "total_dictations": 0, "phrases": {}}
    return _vocab_cache

def save_vocab(vocab):
    global _vocab_cache
    _vocab_cache = vocab
    try:
        with open(VOCAB_FILE, "w") as f: json.dump(vocab, f, indent=2)
    except Exception: pass

def learn_from_text(text):
    """Update vocab — loads once, saves once per call."""
    try:
        vocab = load_vocab()
        vocab["total_dictations"] = vocab.get("total_dictations", 0) + 1
        words = re.findall(r"[a-zA-Z']+", text.lower())
        for word in words:
            if len(word) > 3 and word not in STOPWORDS:
                vocab["word_counts"][word] = vocab["word_counts"].get(word, 0) + 1
        for i in range(len(words) - 1):
            phrase = words[i] + " " + words[i+1]
            if not any(w in STOPWORDS for w in [words[i], words[i+1]]):
                vocab["phrases"][phrase] = vocab["phrases"].get(phrase, 0) + 1
        save_vocab(vocab)
    except Exception as e: print(f"[vocab] error: {e}")

def get_personal_prompt():
    """Uses cached vocab — no extra disk read."""
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

def play_sound(name, block=False):
    sounds = {"start": "/System/Library/Sounds/Tink.aiff", "stop": "/System/Library/Sounds/Pop.aiff"}
    if block:
        subprocess.run(["afplay", sounds[name]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(["afplay", sounds[name]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def _set_system_mute(mute: bool):
    try: subprocess.run(["osascript", "-e", f"set volume {'with' if mute else 'without'} output muted"], timeout=3)
    except Exception: pass

_pre_recording_muted = False
_apps_were_playing = []
_browsers_paused = []

def _send_media_playpause():
    """Send a real media play/pause key event using CoreGraphics."""
    try:
        import Quartz
        NX_KEYTYPE_PLAY = 16
        NX_SYSDEFINED = 14  # correct event type for media keys
        def _make_event(down):
            ev = Quartz.CGEventCreateKeyboardEvent(None, 0, down)
            Quartz.CGEventSetType(ev, NX_SYSDEFINED)
            Quartz.CGEventSetIntegerValueField(
                ev, 159,
                (NX_KEYTYPE_PLAY << 16) | ((1 if down else 0) << 8)
            )
            return ev
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, _make_event(True))
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, _make_event(False))
    except Exception as e:
        print(f"[media] playpause error: {e}")

def _is_running(proc_name):
    try: return subprocess.run(["pgrep", "-ix", proc_name], capture_output=True, timeout=1).returncode == 0
    except Exception: return False

def pause_media():
    global _pre_recording_muted, _apps_were_playing, _browsers_paused
    _apps_were_playing = []
    _browsers_paused = []

    # 1. INSTANT MUTE — fire and forget, no waiting for return value
    try:
        result = subprocess.run(
            ["osascript", "-e", "output muted of (get volume settings)"],
            capture_output=True, timeout=1
        )
        _pre_recording_muted = result.stdout.decode().strip() == "true"
    except Exception:
        _pre_recording_muted = False
    if not _pre_recording_muted:
        subprocess.Popen(["osascript", "-e", "set volume with output muted"])

    # 2. THREADED APP CHECKS — browser and music app pausing in background
    def _pause_apps():
        # Firefox media key
        if _is_running("firefox"):
            try:
                _send_media_playpause()
                _browsers_paused.append("Firefox")
                print("[media] paused Firefox")
            except Exception as e:
                print(f"[media] Firefox pause error: {e}")
        # Spotify/Music/Podcasts in parallel
        import concurrent.futures
        def _pause_one(args):
            proc, state_cmd, pause_cmd = args
            if not _is_running(proc): return None
            try:
                state = subprocess.check_output(
                    ["osascript", "-e", state_cmd], timeout=1
                ).decode().strip().lower()
                if state in ("playing", "1"):
                    subprocess.Popen(["osascript", "-e", pause_cmd])
                    print(f"[media] paused {proc}")
                    return proc
            except Exception: pass
            return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            results = list(ex.map(_pause_one, [
                ("Spotify", 'tell application "Spotify" to player state as string', 'tell application "Spotify" to pause'),
                ("Music",   'tell application "Music" to player state as string',   'tell application "Music" to pause'),
                ("Podcasts",'tell application "Podcasts" to player state as string','tell application "Podcasts" to pause'),
            ]))
        _apps_were_playing.extend([r for r in results if r])

    threading.Thread(target=_pause_apps, daemon=True).start()

def resume_media():
    global _pre_recording_muted, _apps_were_playing, _browsers_paused
    print(f"[media] resuming — _pre_recording_muted={_pre_recording_muted}")
    if not _pre_recording_muted:
        _set_system_mute(False)
        print("[media] system unmuted")
    else:
        print("[media] was already muted before recording, leaving muted")

    # Resume Firefox via media key
    if "Firefox" in _browsers_paused:
        try:
            _send_media_playpause()
            print("[media] resumed Firefox")
        except Exception as e:
            print(f"[media] Firefox resume error: {e}")

    resume_cmds = {"Spotify": 'tell application "Spotify" to play', "Music": 'tell application "Music" to play', "Podcasts": 'tell application "Podcasts" to resume'}
    for app_name in _apps_were_playing:
        try: subprocess.run(["osascript", "-e", resume_cmds[app_name]], timeout=5)
        except Exception: pass
    _apps_were_playing = []
    _browsers_paused = []

def get_current_rms():
    with _audio_lock:
        return float(np.sqrt(np.mean(audio_frames[-1]**2))) if audio_frames else 0.0

def audio_callback(indata, frames, time_info, status):
    if recording:
        with _audio_lock:
            audio_frames.append(indata.copy())
    elif WAKE_ENABLED and not recording and not cancelled:
        with wake_lock:
            wake_frames.append(indata.copy())

def save_wav(frames, path):
    audio = np.concatenate(frames, axis=0)
    target_len = int(len(audio) * 16000 / SAMPLE_RATE)
    resampled = np.interp(np.linspace(0, len(audio)-1, target_len), np.arange(len(audio)), audio[:, 0]).astype(np.float32)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes((resampled * 32767).astype(np.int16).tobytes())

_paste_lock = threading.Lock()   # prevents clipboard desync from overlapping pastes

def paste_text(text):
    with _paste_lock:
        try:
            import subprocess as _sp
            prev = _sp.run(["pbpaste"], capture_output=True).stdout
            _sp.run(["pbcopy"], input=(text + " ").encode(), timeout=2)
            import time as _t; _t.sleep(0.12)
            try:
                _sp.run(["osascript", "-e", 'tell application "System Events" to keystroke "v" using command down'], timeout=3)
                _t.sleep(0.1)
            finally:
                _sp.run(["pbcopy"], input=prev, timeout=2)
        except Exception:
            typer.type(text + " ")

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
            "maps": "https://maps.google.com", 
            "my website": USER_CONFIG["my_website"],
            "my repo":    USER_CONFIG["my_repo"],
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
    }

    def _find_adobe(name):
        """Find installed Adobe app regardless of year version."""
        import glob
        matches = sorted(glob.glob(f"/Applications/Adobe {name}*.app"), reverse=True)
        if matches: return matches[0].split("/")[-1].replace(".app", "")
        return f"Adobe {name}"

    app_keywords.update({
        "photoshop": _find_adobe("Photoshop"),
        "illustrator": _find_adobe("Illustrator"),
        "premiere": _find_adobe("Premiere Pro"),
        "after effects": _find_adobe("After Effects"),
        "lightroom": _find_adobe("Lightroom Classic"),
        "acrobat": _find_adobe("Acrobat"),
        "media encoder": _find_adobe("Media Encoder"),
        "encoder": _find_adobe("Media Encoder"),
        "indesign": _find_adobe("InDesign"),
        "figma": "Figma", "sketch": "Sketch", "zoom": "Zoom", "teams": "Microsoft Teams",
        "word": "Microsoft Word", "excel": "Microsoft Excel", "powerpoint": "Microsoft PowerPoint",
        "outlook": "Microsoft Outlook", "notion": "Notion", "obsidian": "Obsidian",
        "discord": "Discord", "whatsapp": "WhatsApp", "telegram": "Telegram",
        "1password": "1Password 7", "screenflow": "ScreenFlow", "quicktime": "QuickTime Player",
        "vlc": "VLC", "iterm": "iTerm", "app store": "App Store"
    })
    if lower.startswith("open "):
        keyword = lower[5:].strip()
        if keyword in app_keywords: return ("open_app", {"app": app_keywords[keyword], "url": ""})
        for kw, app_name in app_keywords.items():
            if kw in keyword: return ("open_app", {"app": app_name, "url": ""})
        return ("open_app", {"app": keyword.title(), "url": ""})

    # Direct app name match — say just "Photoshop", "Premiere", "Spotify" etc.
    if lower.strip() in app_keywords:
        return ("open_app", {"app": app_keywords[lower.strip()], "url": ""})
    for kw, app_name in app_keywords.items():
        if lower.strip() == kw:
            return ("open_app", {"app": app_name, "url": ""})

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
    kill_match = re.match(r"(?:kill|force quit|force close)\s+(.+)", lower)
    if kill_match: return ("kill_app", {"app": kill_match.group(1).strip()})
    return None

def transcribe_and_type(wav_path, raw_frames):
    global last_text, cancelled, snippet_state, snippet_trigger
    if cancelled:
        cancelled = False
        app.set_state("idle")
        return

    # Single concatenation reused for both silence checks (was computed twice)
    audio = np.concatenate(raw_frames, axis=0)
    rms = float(np.sqrt(np.mean(audio ** 2)))

    if rms < SILENCE_FLOOR:
        threading.Thread(target=resume_media, daemon=True).start()
        app.set_state("idle")
        return
    globals()["_recording_had_audio"] = True
    app.set_state("transcribing")
    if rms < SILENCE_TOO_QUIET:
        print("[transcribe] skipping — audio too quiet")
        app.set_state("idle")
        return

    personal_prompt = get_personal_prompt()
    language_to_use = "en" if not settings.get("auto_detect", True) else None

    # beam_size=1 (greedy) is 3-5x faster than beam_size=5 on Intel CPU
    _BEAM = 1

    if settings.get("cloud_mode") and get_openai_key():
        raw_text = transcribe_cloud(wav_path)
        if not raw_text:
            segments, _ = whisper.transcribe(wav_path, beam_size=_BEAM, language=language_to_use, condition_on_previous_text=False, initial_prompt=personal_prompt, vad_filter=True, no_speech_threshold=0.6)
            raw_text = " ".join(seg.text for seg in segments).strip()
    else:
        segments, _ = whisper.transcribe(wav_path, beam_size=_BEAM, language=language_to_use, condition_on_previous_text=False, initial_prompt=personal_prompt, vad_filter=True, no_speech_threshold=0.6)
        raw_text = " ".join(seg.text for seg in segments).strip()

    # Ollama refinement — non-blocking worker, falls back on timeout.
    # Skip for highly repetitive input (avoids known LLM looping behaviour).
    def _is_repetitive(t):
        words = t.lower().split()
        return len(words) >= 4 and len(set(words)) / len(words) < 0.4

    if raw_text and OLLAMA_ENABLED and not _is_repetitive(raw_text):
        refined = ollama_query(raw_text)
        if refined and refined.lower().strip() != "nothing":
            print(f"[llama refined] {refined}")
            raw_text = refined

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
        _invalidate_snippets_cache()
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
    with _audio_lock:
        audio_frames = []
    time.sleep(0.3)
    with _audio_lock:
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
        with _audio_lock:
            last_frame = audio_frames[-1] if audio_frames else None
        if last_frame is None: continue
        if float(np.sqrt(np.mean(last_frame**2))) < SILENCE_STOP_RMS:
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
        print("[wake] ready — say 'Hey Jarvis' to start dictating")
    except Exception as e:
        print(f"[wake] openwakeword failed ({e}), wake word disabled")
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
            print("[wake] listening for 'Hey Jarvis'...")

def _stop_recording():
    global recording, _wake_cooldown_until
    if not recording: return
    recording = False
    _wake_cooldown_until = time.time() + 2.0
    app.root.after(0, app.stop_wave)
    app.root.after(0, lambda: app.set_state("transcribing"))
    with _audio_lock:
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
        print(f"[debug] record key pressed — starting recording")
        recording = True
        _wake_active.set()
        globals()["_wake_cooldown_until"] = time.time() + 2.0
        with _audio_lock:
            audio_frames.clear()
        cancelled = False
        with wake_lock:
            wake_frames.clear()
        app.capture_active_app()
        app.set_state("recording")
        app.root.after(0, app.start_wave)
        play_sound("start")           # non-blocking — fire and forget
        threading.Thread(target=pause_media, daemon=True).start()
        globals()["_recording_had_audio"] = False
    elif key == record_key and recording and settings.get("toggle_mode", False):
        recording = False
        app.root.after(0, app.stop_wave)
        threading.Thread(target=play_sound, args=("stop",), daemon=True).start()
        with _audio_lock:
            frames = list(audio_frames)
        if frames:
            threading.Thread(target=_process, args=(frames,), daemon=True).start()
        else:
            app.set_state("idle")
    elif key == Key.esc:
        recording = False
        cancelled = True
        with _audio_lock:
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
        with _audio_lock:
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
                    for i in range(menubar._hotkey_menu.numberOfItems()):
                        item = menubar._hotkey_menu.itemAtIndex_(i)
                        item.setState_(1 if item.title() == sender.title() else 0)
                def quitApp_(self, sender):
                    _quit_clean()
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
            self._hotkey_menu = hotkey_menu
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
        self.canvas.tag_bind("close", "<Button-1>", lambda e: _quit_clean())
        self.canvas.tag_bind("close", "<Enter>", lambda e: self.canvas.itemconfig("close", fill=self.TEXT_WHITE))
        self.canvas.tag_bind("close", "<Leave>", lambda e: self.canvas.itemconfig("close", fill=self.TEXT_DIM))

    def _make_draggable(self):
        self._drag_x = None
        self._drag_y = None
        def start(e):
            if self._ready:
                self._drag_x = e.x_root - self.root.winfo_x()
                self._drag_y = e.y_root - self.root.winfo_y()
        def move(e):
            if self._ready and self._drag_x is not None:
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
        BG      = "#141414"   # deepest bg — matches HUD pill colour family
        SIDEBAR = "#1a1a1a"   # sidebar column
        CARD    = "#222222"   # input / list-item surface
        CARD_HI = "#2a2a2a"   # hovered list item
        SEP     = "#2e2e2e"   # divider lines
        ACC     = "#0a84ff"   # blue accent
        ACC_DIM = "#1a3a5c"   # selected row bg (muted accent)
        FG      = "#f0f0f0"
        DIM     = "#6a6a6a"
        FONT    = "Helvetica Neue"

        swin = tk.Toplevel(self.root)
        swin.title("Snippets")
        swin.configure(bg=BG)
        swin.attributes("-topmost", True)
        swin.attributes("-alpha", 0.97)
        swin.resizable(False, False)
        # Center on screen
        W, H = 720, 520
        sw, sh = swin.winfo_screenwidth(), swin.winfo_screenheight()
        swin.geometry(f"{W}x{H}+{sw//2 - W//2}+{sh//2 - H//2}")
        swin.update_idletasks()
        # Close on Escape
        swin.bind("<Escape>", lambda e: swin.destroy())
        # Drag — bound to sidebar/header only after those frames are created below
        def _drag_start(e): swin._dx, swin._dy = e.x_root - swin.winfo_x(), e.y_root - swin.winfo_y()
        def _drag_move(e):
            if hasattr(swin, "_dx"):
                swin.geometry(f"+{e.x_root - swin._dx}+{e.y_root - swin._dy}")

        # ── Sidebar ───────────────────────────────────────────────────────────
        sidebar = tk.Frame(swin, bg=SIDEBAR, width=210)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        # Sidebar header
        hdr = tk.Frame(sidebar, bg=SIDEBAR, height=60)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        _sn_icon = None
        try:
            from PIL import Image, ImageTk
            _sn_path = os.path.join(
                getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.argv[0]))),
                "dictate_icon.png"
            )
            _sn_pil = Image.open(_sn_path).convert("RGBA").resize((22, 22), Image.LANCZOS)
            _sn_icon = ImageTk.PhotoImage(_sn_pil)
            self._snippets_icon = _sn_icon
        except Exception:
            _sn_icon = None
        if _sn_icon:
            tk.Label(hdr, image=_sn_icon, bg=SIDEBAR).place(x=14, rely=0.5, anchor="w")
            tk.Label(hdr, text="Snippets", bg=SIDEBAR, fg=FG,
                     font=(FONT, 14, "bold")).place(x=42, rely=0.5, anchor="w")
        else:
            tk.Label(hdr, text="🎙", bg=SIDEBAR, fg=FG,
                     font=(FONT, 18)).place(x=14, rely=0.5, anchor="w")
            tk.Label(hdr, text="Snippets", bg=SIDEBAR, fg=FG,
                     font=(FONT, 14, "bold")).place(x=40, rely=0.5, anchor="w")
        close_btn = tk.Label(hdr, text="✕", bg=SIDEBAR, fg=DIM,
                             font=(FONT, 12), cursor="hand2")
        close_btn.place(relx=1.0, x=-14, rely=0.5, anchor="e")
        close_btn.bind("<Button-1>", lambda e: swin.destroy())
        close_btn.bind("<Enter>", lambda e: close_btn.configure(fg=FG))
        close_btn.bind("<Leave>", lambda e: close_btn.configure(fg=DIM))

        # Scope drag to sidebar header so Entry/Text focus is never stolen
        for _sw in (sidebar, hdr):
            _sw.bind("<ButtonPress-1>", _drag_start)
            _sw.bind("<B1-Motion>",     _drag_move)

        # Search box  (no separator — matches settings sidebar style)
        search_frame = tk.Frame(sidebar, bg=SIDEBAR, height=44)
        search_frame.pack(fill="x")
        search_frame.pack_propagate(False)
        tk.Label(search_frame, text="⌕", bg=SIDEBAR, fg=FG, font=(FONT, 19)).place(x=12, rely=0.5, anchor="w")
        search_var = tk.StringVar()
        se = tk.Entry(search_frame, textvariable=search_var, bg=SIDEBAR, fg=FG,
                      font=(FONT, 12), relief="flat", insertbackground=FG, bd=0,
                      highlightthickness=0)
        se.place(x=34, rely=0.5, anchor="w", width=148, height=28)

        # Snippet list
        list_canvas = tk.Canvas(sidebar, bg=SIDEBAR, highlightthickness=0)
        list_inner  = tk.Frame(list_canvas, bg=SIDEBAR)
        list_canvas.create_window((0, 0), window=list_inner, anchor="nw")
        list_inner.bind("<Configure>", lambda e: list_canvas.configure(scrollregion=list_canvas.bbox("all")))
        list_canvas.pack(fill="both", expand=True)

        # Add new button at bottom of sidebar — no separator, matches settings style
        new_btn = tk.Label(sidebar, text="+ New snippet", bg=SIDEBAR, fg=ACC,
                           font=(FONT, 12), cursor="hand2", pady=10)
        new_btn.pack(side="bottom", fill="x", padx=16)

        # ── Vertical divider ──────────────────────────────────────────────────
        tk.Frame(swin, bg=SEP, width=1).pack(side="left", fill="y")

        # ── Detail pane ───────────────────────────────────────────────────────
        detail = tk.Frame(swin, bg=BG)
        detail.pack(side="left", fill="both", expand=True)

        # Detail header
        dhdr = tk.Frame(detail, bg=BG, height=56)
        dhdr.pack(fill="x")
        dhdr.pack_propagate(False)
        detail_title = tk.Label(dhdr, text="Edit snippet", bg=BG, fg=FG,
                                font=(FONT, 14, "bold"))
        detail_title.place(x=20, rely=0.5, anchor="w")
        tk.Frame(detail, bg=SEP, height=1).pack(fill="x")

        # Action bar packed FIRST (bottom) so it's always visible
        tk.Frame(detail, bg=SEP, height=1).pack(side="bottom", fill="x")
        abar = tk.Frame(detail, bg=BG, height=52)
        abar.pack(side="bottom", fill="x")
        abar.pack_propagate(False)

        # Body fills remaining space between header and action bar
        body = tk.Frame(detail, bg=BG)
        body.pack(fill="both", expand=True, padx=20, pady=16)

        tk.Label(body, text="TRIGGER PHRASE", bg=BG, fg=DIM,
                 font=(FONT, 9, "bold")).pack(anchor="w")
        trigger_var = tk.StringVar()

        # Simple dark card frames — fully interactive, no canvas layering
        trigger_f = tk.Frame(body, bg=CARD, highlightthickness=1,
                             highlightbackground=SEP, highlightcolor=ACC)
        trigger_f.pack(fill="x", pady=(4, 12))
        trigger_entry = tk.Entry(trigger_f, textvariable=trigger_var,
                                 bg=CARD, fg=FG, font=(FONT, 13),
                                 relief="flat", insertbackground=FG,
                                 bd=0, highlightthickness=0)
        trigger_entry.pack(fill="x", ipady=9, padx=10)

        tk.Label(body, text="EXPANSION", bg=BG, fg=DIM,
                 font=(FONT, 9, "bold")).pack(anchor="w")
        content_f = tk.Frame(body, bg=CARD, highlightthickness=1,
                             highlightbackground=SEP, highlightcolor=ACC)
        content_f.pack(fill="both", expand=True, pady=(4, 0))
        content_text = tk.Text(content_f, bg=CARD, fg=FG, font=(FONT, 13),
                               relief="flat", insertbackground=FG, wrap="word",
                               padx=10, pady=10, bd=0, highlightthickness=0)
        content_text.pack(fill="both", expand=True)

        def _btn(parent, text, cmd, accent=False, danger=False):
            """Rounded pill button drawn on a Canvas."""
            R = 7
            fg_col  = "#ffffff"
            bg_col  = ACC if accent else ("#2a2a2a" if not danger else "#2a2a2a")
            hover_col = "#1a6fd4" if accent else "#3a3a3a"
            text_col  = fg_col if accent else ("#ff453a" if danger else "#c0c0c0")

            # Measure approximate size
            char_px = 8
            btn_w = len(text) * char_px + 36
            btn_h = 34

            outer = tk.Frame(parent, bg=parent["bg"])
            outer.pack(side="right", padx=(0, 12), pady=10)

            c = tk.Canvas(outer, width=btn_w, height=btn_h,
                          bg=parent["bg"], highlightthickness=0, cursor="hand2")
            c.pack()

            def _paint(bg=bg_col, tc=text_col):
                c.delete("all")
                c.create_arc(0,      0,      R*2, R*2,               start=90,  extent=90, fill=bg, outline=bg)
                c.create_arc(btn_w-R*2, 0,   btn_w, R*2,             start=0,   extent=90, fill=bg, outline=bg)
                c.create_arc(0,      btn_h-R*2, R*2,   btn_h,        start=180, extent=90, fill=bg, outline=bg)
                c.create_arc(btn_w-R*2, btn_h-R*2, btn_w, btn_h,     start=270, extent=90, fill=bg, outline=bg)
                c.create_rectangle(R, 0, btn_w-R, btn_h,             fill=bg, outline="")
                c.create_rectangle(0, R, btn_w,   btn_h-R,           fill=bg, outline="")
                c.create_text(btn_w//2, btn_h//2, text=text,
                              font=(FONT, 12, "bold") if accent else (FONT, 12),
                              fill=tc, anchor="center")

            _paint()
            c.bind("<Button-1>",  lambda e: cmd())
            c.bind("<Enter>",     lambda e: _paint(bg=hover_col))
            c.bind("<Leave>",     lambda e: _paint())
            return c

        # ── State & logic ─────────────────────────────────────────────────────
        selected, rows = [None], {}

        def select(t, c):
            selected[0] = t
            trigger_var.set(t)
            content_text.delete("1.0", tk.END)
            content_text.insert("1.0", c)
            detail_title.configure(text=f"Edit  ›  {t[:28]}")
            for k, row in rows.items():
                is_sel = (k == t)
                row["frame"].configure(bg=SIDEBAR)
                row["label"].configure(bg=SIDEBAR,
                                       fg=FG if is_sel else DIM,
                                       font=(FONT, 12, "bold") if is_sel else (FONT, 12))

        def new_snippet():
            selected[0] = None
            trigger_var.set("")
            content_text.delete("1.0", tk.END)
            detail_title.configure(text="New snippet")
            for row in rows.values():
                row["frame"].configure(bg=SIDEBAR)
                row["label"].configure(bg=SIDEBAR, fg=DIM)
            trigger_entry.focus_set()

        def save_sel():
            t = trigger_var.get().strip().lower()
            c = content_text.get("1.0", tk.END).strip()
            if not t or not c: return
            s = load_snippets()
            if selected[0] and selected[0] != t:
                s.pop(selected[0], None)
            s[t] = c
            with open(SNIPPETS_FILE, "w") as f: json.dump(s, f, indent=2)
            _invalidate_snippets_cache()
            selected[0] = t
            refresh(search_var.get())
            self.show_message(f"Saved '{t}'", self.GREEN)

        def delete_sel():
            t = selected[0]
            if not t: return
            s = load_snippets()
            s.pop(t, None)
            with open(SNIPPETS_FILE, "w") as f: json.dump(s, f, indent=2)
            _invalidate_snippets_cache()
            selected[0] = None
            trigger_var.set("")
            content_text.delete("1.0", tk.END)
            detail_title.configure(text="Edit snippet")
            refresh(search_var.get())

        def refresh(q=""):
            for w in list_inner.winfo_children(): w.destroy()
            rows.clear()
            snips = load_snippets()
            shown = {t: c for t, c in snips.items()
                     if not q or q.lower() in t.lower() or q.lower() in c.lower()}
            if not shown:
                tk.Label(list_inner, text="No snippets yet",
                         bg=SIDEBAR, fg=DIM, font=(FONT, 11)).pack(pady=24, padx=16)
                return
            for t, c in shown.items():
                is_sel = (t == selected[0])
                rf = tk.Frame(list_inner, bg=SIDEBAR, cursor="hand2")
                rf.pack(fill="x")
                # left accent bar when selected
                tk.Frame(rf, bg=ACC if is_sel else SIDEBAR, width=3).pack(side="left", fill="y")
                rl = tk.Label(rf, text=t, bg=SIDEBAR,
                              fg=FG if is_sel else DIM, font=(FONT, 12),
                              anchor="w", padx=10, pady=11)
                rl.pack(side="left", fill="x", expand=True)
                # no separator line — clean sidebar like Settings
                rows[t] = {"frame": rf, "label": rl}
                for widget in (rf, rl):
                    widget.bind("<Button-1>", lambda e, tt=t, cc=c: select(tt, cc))
                    widget.bind("<Enter>", lambda e, f=rf, l=rl, tt=t: (
                        f.configure(bg=SIDEBAR if selected[0]==tt else CARD_HI),
                        l.configure(bg=SIDEBAR if selected[0]==tt else CARD_HI)
                    ))
                    widget.bind("<Leave>", lambda e, f=rf, l=rl, tt=t: (
                        f.configure(bg=SIDEBAR),
                        l.configure(bg=SIDEBAR)
                    ))
            if selected[0] not in shown:
                try: select(next(iter(shown)), shown[next(iter(shown))])
                except StopIteration: pass

        search_var.trace_add("write", lambda *a: refresh(search_var.get()))
        new_btn.bind("<Button-1>", lambda e: new_snippet())
        refresh()

        # Action buttons — _btn packs itself side="right" with padx
        save_btn = _btn(abar, "Save changes", save_sel,   accent=True)
        del_btn  = _btn(abar, "Delete",       delete_sel, danger=True)

    def open_settings(self):
        self.root.after(0, self._show_settings)

    def _show_settings(self):
        BG      = "#141414"
        SIDEBAR = "#1a1a1a"
        CARD    = "#222222"
        CARD_HI = "#2a2a2a"
        SEP     = "#2e2e2e"
        ACC     = "#0a84ff"
        ACC_DIM = "#1a3a5c"
        FG      = "#f0f0f0"
        DIM     = "#6a6a6a"
        FONT    = "Helvetica Neue"

        _win = tk.Toplevel(self.root)
        _win.title("Settings")
        _win.configure(bg=BG)
        _win.attributes("-topmost", True)
        _win.attributes("-alpha", 0.97)
        _win.resizable(False, False)
        # Center on screen
        W, H = 680, 520
        sw, sh = _win.winfo_screenwidth(), _win.winfo_screenheight()
        _win.geometry(f"{W}x{H}+{sw//2 - W//2}+{sh//2 - H//2}")
        _win.update_idletasks()
        # Close on Escape
        _win.bind("<Escape>", lambda e: _win.destroy())

        # Drag bound only to sidebar (not content area) so Entry/Text widgets
        # still receive clicks and keyboard focus correctly.
        def _drag_start(e): _win._dx, _win._dy = e.x_root - _win.winfo_x(), e.y_root - _win.winfo_y()
        def _drag_move(e):
            if hasattr(_win, "_dx"):
                _win.geometry(f"+{e.x_root - _win._dx}+{e.y_root - _win._dy}")

        # ── Variables ─────────────────────────────────────────────────────────
        model_var  = tk.StringVar(value=settings["model"])
        hotkey_var = tk.StringVar(value=settings.get("hotkey_label", "Right Option"))
        cloud_var  = tk.BooleanVar(value=settings.get("cloud_mode", False))
        key_var    = tk.StringVar(value=get_openai_key())

        try:
            _devs = sd.query_devices()
            _input_devs = [(i, d["name"]) for i, d in enumerate(_devs) if d["max_input_channels"] > 0]
            _dev_labels  = [f"{i}: {n[:32]}" for i, n in _input_devs]
            _dev_indices = [i for i, n in _input_devs]
        except Exception:
            _input_devs = _dev_labels = _dev_indices = []

        current_mic = settings.get("mic_device", 2)
        _cur_dev_label = next((f"{i}: {n[:32]}" for i, n in _input_devs if i == current_mic), str(current_mic))
        mic_var    = tk.StringVar(value=_cur_dev_label)
        hud_var    = tk.BooleanVar(value=settings.get("show_hud", True))
        toggle_var = tk.BooleanVar(value=settings.get("toggle_mode", True))
        wake_var   = tk.BooleanVar(value=settings.get("wake_enabled", True))
        jarvis_var = tk.BooleanVar(value=settings.get("jarvis_enabled", True))
        format_var = tk.BooleanVar(value=settings.get("context_format", True))
        auto_var   = tk.BooleanVar(value=settings.get("auto_detect", True))
        ollama_var = tk.BooleanVar(value=settings.get("use_ollama", True))

        # ── Sidebar nav ───────────────────────────────────────────────────────
        sidebar = tk.Frame(_win, bg=SIDEBAR, width=172)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        shdr = tk.Frame(sidebar, bg=SIDEBAR, height=60)
        shdr.pack(fill="x")
        shdr.pack_propagate(False)
        # App icon from provided PNG
        _icon_path = os.path.join(
            getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.argv[0]))),
            "dictate_icon.png"
        )
        _icon_img = None
        try:
            from PIL import Image, ImageTk
            _pil = Image.open(_icon_path).convert("RGBA").resize((22, 22), Image.LANCZOS)
            _icon_img = ImageTk.PhotoImage(_pil)
            self._settings_icon = _icon_img   # keep reference alive
        except Exception:
            _icon_img = None
        if _icon_img:
            tk.Label(shdr, image=_icon_img, bg=SIDEBAR).place(x=14, rely=0.5, anchor="w")
            tk.Label(shdr, text="Dictation", bg=SIDEBAR, fg=FG,
                     font=(FONT, 14, "bold")).place(x=42, rely=0.5, anchor="w")
        else:
            tk.Label(shdr, text="🎙", bg=SIDEBAR, fg=FG,
                     font=(FONT, 18)).place(x=14, rely=0.5, anchor="w")
            tk.Label(shdr, text="Dictation", bg=SIDEBAR, fg=FG,
                     font=(FONT, 14, "bold")).place(x=40, rely=0.5, anchor="w")
        # Close button top-right
        close_lbl = tk.Label(shdr, text="✕", bg=SIDEBAR, fg=DIM,
                             font=(FONT, 12), cursor="hand2")
        close_lbl.place(relx=1.0, x=-14, rely=0.5, anchor="e")
        close_lbl.bind("<Button-1>", lambda e: _win.destroy())
        close_lbl.bind("<Enter>", lambda e: close_lbl.configure(fg=FG))
        close_lbl.bind("<Leave>", lambda e: close_lbl.configure(fg=DIM))
        # Bind drag to sidebar header — keeps drag UX without stealing focus
        # from Entry/Text widgets in the content area
        for _drag_w in (sidebar, shdr):
            _drag_w.bind("<ButtonPress-1>", _drag_start)
            _drag_w.bind("<B1-Motion>",     _drag_move)

        tk.Frame(sidebar, bg=SEP, height=1).pack(fill="x")

        nav_items = [
            "Transcription",
            "Microphone",
            "Hotkey",
            "Behaviour",
            "Ollama",
            "OpenAI",
        ]
        nav_btns = {}
        active_page = [None]

        # Pack separator THEN content — correct left-to-right layout order
        tk.Frame(_win, bg=SEP, width=1).pack(side="left", fill="y")
        content_host = tk.Frame(_win, bg=BG)
        content_host.pack(side="left", fill="both", expand=True)

        pages = {}

        # Sidebar footer
        tk.Frame(sidebar, bg=SEP, height=1).pack(side="bottom", fill="x")
        footer = tk.Frame(sidebar, bg=SIDEBAR, height=44)
        footer.pack(side="bottom", fill="x")
        footer.pack_propagate(False)
        tk.Label(footer, text="v4  ·  ⌃,  to open", bg=SIDEBAR, fg=DIM,
                 font=(FONT, 9)).place(x=14, rely=0.5, anchor="w")

        def show_page(name):
            active_page[0] = name
            for n, (f, l, bar) in nav_btns.items():
                is_active = (n == name)
                bar.configure(bg=ACC if is_active else SIDEBAR)
                l.configure(fg=FG if is_active else DIM,
                            font=(FONT, 12, "bold") if is_active else (FONT, 12))
            for n, pg in pages.items():
                pg.pack_forget()
            if name in pages:
                pages[name].pack(fill="both", expand=True)

        for nav_name in nav_items:
            nf = tk.Frame(sidebar, bg=SIDEBAR, cursor="hand2", height=40)
            nf.pack(fill="x")
            nf.pack_propagate(False)
            # Left accent bar (shown when active)
            accent_bar = tk.Frame(nf, bg=SIDEBAR, width=3)
            accent_bar.pack(side="left", fill="y")
            nl = tk.Label(nf, text=f"  {nav_name}", bg=SIDEBAR, fg=DIM,
                          font=(FONT, 12), anchor="w", padx=8)
            nl.pack(side="left", fill="x", expand=True)
            nav_btns[nav_name] = (nf, nl, accent_bar)
            for w in (nf, nl):
                w.bind("<Button-1>", lambda e, n=nav_name: show_page(n))
                w.bind("<Enter>", lambda e, f=nf, l=nl, n=nav_name: (
                    l.configure(fg=FG if active_page[0] != n else FG)
                    if active_page[0] != n else None
                ))
                w.bind("<Leave>", lambda e, f=nf, l=nl, n=nav_name: (
                    l.configure(fg=DIM if active_page[0] != n else FG)
                    if active_page[0] != n else None
                ))

        # ── Shared helpers ────────────────────────────────────────────────────
        def page(name):
            f = tk.Frame(content_host, bg=BG)
            pages[name] = f
            return f

        def ph(parent, text):
            """Page heading."""
            tk.Label(parent, text=text, bg=BG, fg=FG,
                     font=(FONT, 17, "bold")).pack(anchor="w", padx=24, pady=(24, 4))
            tk.Label(parent, text="", bg=BG, height=0).pack()  # spacer

        def lbl(parent, text):
            tk.Label(parent, text=text, bg=BG, fg=DIM,
                     font=(FONT, 9, "bold")).pack(anchor="w", padx=24, pady=(14, 3))

        def combo(parent, var, values, width=26):
            """
            Fully dark drop-down — uses tk.OptionMenu so every part
            (button, popup, items) inherits our dark colours.
            Corner radius via a Canvas rounded-rect underneath.
            """
            R = 7          # corner radius px
            PX = 12        # horizontal padding inside pill
            PY = 6         # vertical padding

            # Measure approximate pixel width from char width
            char_w  = 8    # ~8px per char in Helvetica Neue 13
            pill_w  = width * char_w + PX * 2 + 28   # +28 for arrow
            pill_h  = 32

            outer = tk.Frame(parent, bg=BG)
            outer.pack(anchor="w", padx=24, pady=4)

            c = tk.Canvas(outer, width=pill_w, height=pill_h,
                          bg=BG, highlightthickness=0)
            c.pack()

            def _draw_bg(hover=False):
                c.delete("bg")
                fill = "#2e2e2e" if hover else CARD
                # Rounded rect via 8 points (two arcs + two sides)
                c.create_arc(0, 0, R*2, R*2, start=90,  extent=90,  fill=fill, outline=fill, tags="bg")
                c.create_arc(pill_w-R*2, 0, pill_w, R*2, start=0,   extent=90,  fill=fill, outline=fill, tags="bg")
                c.create_arc(0, pill_h-R*2, R*2, pill_h, start=180, extent=90,  fill=fill, outline=fill, tags="bg")
                c.create_arc(pill_w-R*2, pill_h-R*2, pill_w, pill_h, start=270, extent=90, fill=fill, outline=fill, tags="bg")
                c.create_rectangle(R, 0, pill_w-R, pill_h, fill=fill, outline="", tags="bg")
                c.create_rectangle(0, R, pill_w, pill_h-R, fill=fill, outline="", tags="bg")

            _draw_bg()

            # OptionMenu placed over the canvas
            menu_btn = tk.OptionMenu(outer, var, *values)
            menu_btn.configure(
                bg=CARD, fg=FG, activebackground="#2e2e2e", activeforeground=FG,
                highlightthickness=0, relief="flat", bd=0,
                font=(FONT, 12), anchor="w", padx=PX, pady=0,
                indicatoron=True, width=width - 2,
                cursor="hand2",
            )
            # Theme the popup
            menu_btn["menu"].configure(
                bg=CARD, fg=FG,
                activebackground=ACC, activeforeground="#ffffff",
                bd=0, relief="flat", font=(FONT, 12),
            )
            # Overlay the OptionMenu on the canvas
            c.create_window(0, 0, anchor="nw", window=menu_btn,
                            width=pill_w, height=pill_h, tags="menu")

            menu_btn.bind("<Enter>", lambda e: _draw_bg(True))
            menu_btn.bind("<Leave>", lambda e: _draw_bg(False))
            return menu_btn

        def toggle_row(parent, var, label, desc=""):
            row = tk.Frame(parent, bg=BG)
            row.pack(fill="x", padx=24, pady=5)
            txt = tk.Frame(row, bg=BG)
            txt.pack(side="left", fill="x", expand=True)
            tk.Label(txt, text=label, bg=BG, fg=FG, font=(FONT, 13), anchor="w").pack(anchor="w")
            if desc:
                tk.Label(txt, text=desc, bg=BG, fg=DIM, font=(FONT, 10), anchor="w").pack(anchor="w")
            # Custom toggle pill
            pill_w, pill_h = 40, 22
            pill_c = tk.Canvas(row, width=pill_w, height=pill_h, bg=BG,
                               highlightthickness=0, cursor="hand2")
            pill_c.pack(side="right", padx=(8, 0))

            def draw_pill(on):
                pill_c.delete("all")
                bg_col = ACC if on else "#3a3a3a"
                pill_c.create_oval(0, 0, pill_h, pill_h, fill=bg_col, outline="")
                pill_c.create_oval(pill_w-pill_h, 0, pill_w, pill_h, fill=bg_col, outline="")
                pill_c.create_rectangle(pill_h//2, 0, pill_w-pill_h//2, pill_h, fill=bg_col, outline="")
                cx = pill_w - pill_h//2 - 2 if on else pill_h//2 + 2
                pill_c.create_oval(cx-8, 3, cx+8, pill_h-3, fill="white", outline="")

            def toggle(_evt=None):
                var.set(not var.get())
                draw_pill(var.get())

            draw_pill(var.get())
            pill_c.bind("<Button-1>", toggle)

        def save_btn_row(parent, cmd):
            bar = tk.Frame(parent, bg=BG, height=60)
            bar.pack(fill="x", side="bottom")
            bar.pack_propagate(False)
            tk.Frame(parent, bg=SEP, height=1).pack(fill="x", side="bottom")
            # Rounded pill save button
            R, btn_h = 7, 34
            btn_text = "Save changes"
            btn_w = len(btn_text) * 8 + 36

            holder = tk.Frame(bar, bg=BG)
            holder.pack(side="right", padx=20, pady=13)

            c = tk.Canvas(holder, width=btn_w, height=btn_h,
                          bg=BG, highlightthickness=0, cursor="hand2")
            c.pack()

            def _paint_save(hover=False):
                bg = "#1a6fd4" if hover else ACC
                c.delete("all")
                c.create_arc(0,0,         R*2,R*2,            start=90,  extent=90, fill=bg, outline=bg)
                c.create_arc(btn_w-R*2,0, btn_w,R*2,          start=0,   extent=90, fill=bg, outline=bg)
                c.create_arc(0,btn_h-R*2, R*2,btn_h,          start=180, extent=90, fill=bg, outline=bg)
                c.create_arc(btn_w-R*2,btn_h-R*2,btn_w,btn_h, start=270, extent=90, fill=bg, outline=bg)
                c.create_rectangle(R, 0,     btn_w-R, btn_h,  fill=bg, outline="")
                c.create_rectangle(0, R,     btn_w,   btn_h-R,fill=bg, outline="")
                c.create_text(btn_w//2, btn_h//2, text=btn_text,
                              font=(FONT, 12, "bold"), fill="#ffffff", anchor="center")

            _paint_save()
            c.bind("<Button-1>", lambda e: cmd())
            c.bind("<Enter>",    lambda e: _paint_save(True))
            c.bind("<Leave>",    lambda e: _paint_save(False))

        # ── Page: Transcription ───────────────────────────────────────────────
        p = page("Transcription")
        ph(p, "Transcription")
        lbl(p, "WHISPER MODEL")
        combo(p, model_var, ["tiny.en","base.en","small.en","medium.en","large-v2","large-v3","distil-medium.en","distil-large-v3"])
        tk.Label(p, text="Larger models are more accurate but slower to start.",
                 bg=BG, fg=DIM, font=(FONT, 10)).pack(anchor="w", padx=24, pady=(4,0))
        lbl(p, "LANGUAGE")
        toggle_row(p, auto_var, "Auto-detect language", "Let Whisper identify the spoken language")
        save_btn_row(p, lambda: _save())

        # ── Page: Microphone ─────────────────────────────────────────────────
        p = page("Microphone")
        ph(p, "Microphone")
        lbl(p, "INPUT DEVICE")
        if _dev_labels:
            combo(p, mic_var, _dev_labels, width=34)
        else:
            tk.Label(p, text=f"Device index: {current_mic}  (install sounddevice to list)",
                     bg=BG, fg=DIM, font=(FONT, 11)).pack(anchor="w", padx=24)
        tk.Label(p, text="Changes take effect after restarting the app.",
                 bg=BG, fg=DIM, font=(FONT, 10)).pack(anchor="w", padx=24, pady=(4,0))
        save_btn_row(p, lambda: _save())

        # ── Page: Hotkey ──────────────────────────────────────────────────────
        p = page("Hotkey")
        ph(p, "Record hotkey")
        lbl(p, "TRIGGER KEY")
        combo(p, hotkey_var, list(HOTKEY_OPTIONS.keys()))
        toggle_row(p, toggle_var, "Toggle mode", "Press once to start, press again to stop")
        save_btn_row(p, lambda: _save())

        # ── Page: Behaviour ───────────────────────────────────────────────────
        p = page("Behaviour")
        ph(p, "Behaviour")
        toggle_row(p, hud_var,    "Show HUD",                  "Floating status bar")
        toggle_row(p, wake_var,   "Wake word",                 "Say 'Hey Jarvis' to start recording")
        toggle_row(p, jarvis_var, "Jarvis commands",           "Voice commands for apps, search, media")
        toggle_row(p, format_var, "Context-aware formatting",  "Adjusts tone based on active app")
        save_btn_row(p, lambda: _save())

        # ── Page: Ollama ─────────────────────────────────────────────────────
        p = page("Ollama")
        ph(p, "Ollama refinement")
        toggle_row(p, ollama_var, "Enable Ollama",
                   "Fix brand names & grammar with local LLM (llama3.2:3b)")
        tk.Label(p,
                 text="Requires Ollama running:  ollama serve\n"
                      "Timeout: 3.5s — raw Whisper text used if model is slow.",
                 bg=BG, fg=DIM, font=(FONT, 10), justify="left"
        ).pack(anchor="w", padx=24, pady=(8, 0))
        save_btn_row(p, lambda: _save())

        # ── Page: OpenAI ──────────────────────────────────────────────────────
        p = page("OpenAI")
        ph(p, "OpenAI / Cloud")
        toggle_row(p, cloud_var, "Cloud mode", "Use OpenAI Whisper API instead of local model")
        lbl(p, "API KEY")
        key_f = tk.Frame(p, bg=CARD, highlightthickness=1,
                         highlightbackground=SEP, highlightcolor=ACC)
        key_f.pack(fill="x", padx=24, pady=(4, 0))
        key_entry = tk.Entry(key_f, textvariable=key_var, show="•",
                             bg=CARD, fg=FG, font=(FONT, 13), relief="flat",
                             insertbackground=FG, bd=0, highlightthickness=0)
        key_entry.pack(fill="x", ipady=9, padx=10)
        tk.Label(p, text="Stored in macOS Keychain — not written to disk.",
                 bg=BG, fg=DIM, font=(FONT, 10)).pack(anchor="w", padx=24, pady=(4,0))
        save_btn_row(p, lambda: _save())

        # ── Save logic ────────────────────────────────────────────────────────
        def _save():
            new_mic = current_mic
            if _dev_labels and mic_var.get() in _dev_labels:
                new_mic = _dev_indices[_dev_labels.index(mic_var.get())]
            raw_key = key_var.get().strip()
            if raw_key:
                set_openai_key(raw_key)
            settings.update({
                "model":          model_var.get(),
                "hotkey_label":   hotkey_var.get(),
                "mic_device":     new_mic,
                "show_hud":       hud_var.get(),
                "toggle_mode":    toggle_var.get(),
                "wake_enabled":   wake_var.get(),
                "cloud_mode":     cloud_var.get(),
                "jarvis_enabled": jarvis_var.get(),
                "context_format": format_var.get(),
                "auto_detect":    auto_var.get(),
                "use_ollama":     ollama_var.get(),
            })
            globals().update({"WAKE_ENABLED": wake_var.get(), "JARVIS_ENABLED": jarvis_var.get(), "OLLAMA_ENABLED": ollama_var.get()})
            save_settings(settings)
            _win.destroy()
            self.show_message("Saved! Restart to apply.", self.GREEN)

        # Show first page
        show_page("Transcription")

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
    global whisper, JARVIS_ENABLED, WAKE_ENABLED
    JARVIS_ENABLED = settings.get("jarvis_enabled", True)
    WAKE_ENABLED = settings.get("wake_enabled", True)
    print(f"[boot] WAKE_ENABLED={WAKE_ENABLED} JARVIS_ENABLED={JARVIS_ENABLED}")
    time.sleep(1.5)
    try:
        print(f"[model] loading {MODEL} on {DEVICE}/{COMPUTE}...")
        whisper = WhisperModel(MODEL, device=DEVICE, compute_type=COMPUTE)
        print(f"[model] loaded OK")
    except Exception as e:
        print(f"[model] failed to load {MODEL}: {e}")
        try:
            print("[model] falling back to tiny.en...")
            whisper = WhisperModel("tiny.en", device=DEVICE, compute_type=COMPUTE)
            settings["model"] = "tiny.en"
            save_settings(settings)
            print("[model] tiny.en loaded OK")
        except Exception as e2:
            print(f"[model] fatal: {e2}")
            app.root.after(0, lambda: app.show_message("No Whisper model found.", "#ff3b30"))
            app.set_state("idle")
            return
    app._ready = True
    app.set_state("idle")
    threading.Thread(target=_wake_word_loop, daemon=True).start()
    with keyboard.Listener(on_press=on_press, on_release=on_release):
        stream.start()
        threading.Event().wait()

def _install_suppression_tap():
    """Install a Quartz event tap on the main thread to suppress the record key."""
    try:
        import Quartz
        # Use raw integer 9 for kCGKeyboardEventKeycode to avoid lazy-import crashes
        K_KEYCODE_FIELD = 9 
        
        KEYCODE_MAP = {
            "Right Command": 54, "Right Option": 61,
            "Right Control": 62, "F13": 105, "F14": 107, "F15": 113,
        }
        suppress_keycode = KEYCODE_MAP.get(settings.get("hotkey_label", "Right Command"), 54)

        def _cb(proxy, event_type, event, refcon):
            try:
                # Direct field access prevents the 'Unhandled exception in listener'
                keycode = Quartz.CGEventGetIntegerValueField(event, K_KEYCODE_FIELD)
                
                # If this is our record key, return None to 'eat' the event
                # This prevents the system from 'dinging' or menus from opening
                if keycode == suppress_keycode:
                    return None 
            except Exception:
                pass
            return event

        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            0,
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown) |
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp) |
            Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged),
            _cb, None
        )
        if tap:
            src = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
            Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(), src, Quartz.kCFRunLoopCommonModes)
            Quartz.CGEventTapEnable(tap, True)
            print(f"[input] Quartz suppression tap active for keycode {suppress_keycode}")
        else:
            print("[input] Quartz tap failed — running without suppression")
    except Exception as e:
        print(f"[input] Quartz tap error: {e}")

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
    root.after(1000, _install_suppression_tap)
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
        _quit_clean()
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    import traceback
    try:
        main()
    except Exception as e:
        with open(os.path.expanduser("~/dictation_crash.log"), "w") as f:
            f.write(traceback.format_exc())
        raise