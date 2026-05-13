#!/usr/bin/env python
"""
Jarvis Dictation v6.1.18 — Intel Mac
Hold Right Option to record, release to transcribe and type.
100% offline by default. Optional OpenAI/Ollama refinement.

v6.1.18 fixes:
  - Spark Desktop support on M1 Macs: email commands now try Spark Desktop,
    Spark, Mail, then Outlook; Email profile/formatting explicitly recognizes
    Spark Desktop.
  - Paste reliability preserved: clipboard is verified before Cmd+V and
    previous clipboard is restored after paste.

v6.1.15 fixes:
  - Menu bar icon restored: strong PyObjC reference prevents GC from wiping
    the NSImage; null-before-set + setNeedsDisplay_ forces clean redraw
  - Hey Jarvis wake word fixed: pass model name "hey_jarvis" (not file path)
    so prediction dict key matches oww.predict().get("hey_jarvis", 0)

v6.1.11 fixes:
  - openwakeword model loading in packaged .app (get_pretrained_model_paths
    stub + direct ONNX path resolution via _MEIPASS and package dir)
  - safe fallback when openwakeword is entirely unavailable
  - improved wake-word startup log messages
  - Ollama daemon thread print() crash (ValueError: I/O operation on closed
    file) fixed with _safe_print() wrapper

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
# CRITICAL CRASH FIX: Must be set BEFORE importing faster_whisper / onnxruntime
# to prevent "illegal hardware instruction" and GIL abort on macOS / Python 3.11.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["CT2_USE_EXPERIMENTAL_PACKED_GEMM"] = "0"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["MKL_DEBUG_CPU_TYPE"] = "5"
# Disable ONNX Runtime's internal thread pool entirely.  With more than one
# inter-op thread, onnxruntime spawns its own C++ threads that call
# Py_BEGIN_ALLOW_THREADS / PyEval_RestoreThread from contexts that have no
# PyThreadState on macOS / Python 3.11, causing the fatal GIL abort.
os.environ["ORT_DISABLE_ALL_OPTIMIZATIONS"] = "0"
os.environ["OMP_WAIT_POLICY"] = "PASSIVE"

import threading
import queue as _queue
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

def _bind_copy_paste(widget):
    """Bind reliable macOS copy/paste/cut/select-all plus a right-click menu.

    Tk on macOS can report right-click as Button-2, Button-3, or
    Control-Button-1 depending on the device and system settings, so we bind
    all three. This is intentionally widget-local so it does not interfere with
    the global recording hotkey or the Quartz event tap.
    """
    def _has_selection():
        try:
            if isinstance(widget, tk.Text):
                widget.get("sel.first", "sel.last")
            else:
                widget.selection_get()
            return True
        except Exception:
            return False

    def _copy(e=None):
        try:
            if isinstance(widget, tk.Text):
                try:
                    text = widget.get("sel.first", "sel.last")
                except Exception:
                    text = widget.get("1.0", "end-1c")
            else:
                try:
                    text = widget.selection_get()
                except Exception:
                    text = widget.get()
            widget.clipboard_clear()
            widget.clipboard_append(text)
        except Exception:
            pass
        return "break"

    def _paste(e=None):
        try:
            text = widget.clipboard_get()
            try:
                if _has_selection():
                    if isinstance(widget, tk.Text):
                        widget.delete("sel.first", "sel.last")
                    else:
                        widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
            except Exception:
                pass
            widget.insert(tk.INSERT, text)
        except Exception:
            pass
        return "break"

    def _cut(e=None):
        _copy(None)
        try:
            if isinstance(widget, tk.Text):
                widget.delete("sel.first", "sel.last")
            else:
                widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
        except Exception:
            pass
        return "break"

    def _select_all(e=None):
        try:
            if isinstance(widget, tk.Text):
                widget.tag_add("sel", "1.0", "end")
                widget.mark_set(tk.INSERT, "1.0")
            else:
                widget.select_range(0, "end")
                widget.icursor("end")
        except Exception:
            pass
        return "break"

    def _show_context_menu(e):
        try:
            widget.focus_set()
            menu = tk.Menu(widget, tearoff=0, bg="#2a2a2a", fg="#ffffff",
                           activebackground="#0a84ff", activeforeground="#ffffff")
            menu.add_command(label="Copy",       command=lambda: _copy(None))
            menu.add_command(label="Paste",      command=lambda: _paste(None))
            menu.add_command(label="Cut",        command=lambda: _cut(None))
            menu.add_separator()
            menu.add_command(label="Select All", command=lambda: _select_all(None))
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass
        return "break"

    # Standard macOS shortcuts plus common Tk virtual events.
    widget.bind("<Command-c>", _copy)
    widget.bind("<Command-v>", _paste)
    widget.bind("<Command-x>", _cut)
    widget.bind("<Command-a>", _select_all)
    widget.bind("<<Copy>>", _copy)
    widget.bind("<<Paste>>", _paste)
    widget.bind("<<Cut>>", _cut)

    # Right-click variants: mouse, trackpad, and Ctrl-click.
    widget.bind("<Button-2>", _show_context_menu)
    widget.bind("<Button-3>", _show_context_menu)
    widget.bind("<Control-Button-1>", _show_context_menu)
    widget.bind("<Shift-F10>", _show_context_menu)


def _bind_copy_paste_recursive(root):
    """Apply text editing bindings to every Entry/Text descendant in a window."""
    try:
        if isinstance(root, (tk.Entry, tk.Text)):
            _bind_copy_paste(root)
        for child in root.winfo_children():
            _bind_copy_paste_recursive(child)
    except Exception:
        pass

# Shared professional button metrics for secondary windows.
PRIMARY_BUTTON_W = 132
SECONDARY_BUTTON_W = 92
ACTION_BUTTON_H = 34
WINDOW_EDGE_PAD = 20

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
SILENCE_STOP_RMS   = 0.08    # legacy manual auto-stop threshold

# ── Jarvis wake-word dictation timing ────────────────────────────────────────
# Wake-word dictation should support full sentences, not just short commands.
# These defaults give users time to speak naturally after saying "Hey Jarvis".
WAKE_DICTATION_GRACE_SECONDS = 3.5    # never auto-stop before this many seconds
WAKE_DICTATION_SILENCE_SECONDS = 4.5  # sustained quiet required before auto-stop
WAKE_DICTATION_MAX_SECONDS = 45.0     # safety cap so wake dictation cannot run forever
WAKE_DICTATION_SILENCE_RMS = 0.025    # lower than legacy 0.08 to avoid cutting off soft speech

# ── audio_frames lock — every mutation must hold this ────────────────────────
_audio_lock = threading.Lock()

# ── Caps Lock suppression flag ────────────────────────────────────────────────
# Set to True while any settings/snippets/history Toplevel is open.
# The Quartz event tap reads this flag and drops kCGEventFlagsChanged events
# for keycode 57 (kVK_CapsLock) so they never reach tkinter's Cocoa event loop,
# preventing the Intel MKL / Tcl register conflict (SIGILL) on modifier events.
_suppress_caps_lock:  bool = False
_suppress_keycode:    int  = 54          # updated by _install_suppression_tap
_modifier_keys_down:  set  = set()       # keycodes of modifier keys currently held
_pressed_keys:        set  = set()       # keycodes of regular keys currently held

# Active record hotkey state for the Quartz HID tap.
# Stability rule: Right Option is always available as an emergency/default
# record key, even if Settings contains an older or unsupported hotkey value.
# Recent experiments with left/right Command/Control/Option variants caused some
# keyboards to stop recording entirely, so the public selector is conservative.
RECORD_KEYCODE_MAP = {
    "Right Option": 61,
    "F13": 105,
    "F14": 107,
    "F15": 113,
}
RIGHT_OPTION_KEYCODE = 61
MODIFIER_RECORD_KEYCODES = {61}
# Quartz flags used to determine whether the selected modifier is physically down.
# This is safer than toggling state blindly on every flagsChanged event.
# The actual mask constants are resolved inside _install_suppression_tap() after Quartz is imported.
_record_keycode: int = 61
_record_key_is_modifier: bool = True


# Quartz event taps are allowed to inspect/suppress low-level key events, but
# they must never call Tkinter directly.  Tk's Cocoa bridge is main-thread only,
# and calling root.after() from a CoreGraphics callback is what made the Option
# key path unstable after the Caps Lock fix.  The tap now drops tiny commands
# into this queue; Tk drains it from its own event loop.
_input_event_q: _queue.SimpleQueue = _queue.SimpleQueue()

APP_VERSION = "6.1.18 Spark Desktop Email Fix"
HOTKEY_DEBOUNCE_SECONDS = 0.18
MIN_RECORD_SECONDS = 0.30

_record_started_at: float = 0.0
_last_record_press_at: float = 0.0
_last_record_release_at: float = 0.0
_transcription_busy: bool = False

def log_event(area: str, message: str):
    """Consistent terminal logging without adding another dependency."""
    try:
        print(f"[{area}] {message}")
    except Exception:
        pass

def _setting_float(name: str, fallback: float) -> float:
    try:
        return float(settings.get(name, fallback))
    except Exception:
        return fallback


def _refresh_record_hotkey(log: bool = False):
    """Refresh the active Quartz hotkey from Settings.

    This must be cheap and safe because it is called from Settings saves,
    menu-bar selection changes, and before the HID tap starts. It does not
    reinstall the tap; the callback reads these globals dynamically.
    """
    global _record_keycode, _record_key_is_modifier, _suppress_keycode

    label = settings.get("hotkey_label", "Right Option")
    if label not in RECORD_KEYCODE_MAP:
        # Recover from any older/experimental hotkey setting that may have
        # been saved to ~/.dictation_settings.json. Do not let a bad stored
        # value make the app appear dead.
        old_label = label
        label = "Right Option"
        settings["hotkey_label"] = label
        if log:
            log_event("input", f"unsupported hotkey {old_label!r}; restored Right Option")

    _record_keycode = RECORD_KEYCODE_MAP.get(label, RIGHT_OPTION_KEYCODE)
    _record_key_is_modifier = _record_keycode in MODIFIER_RECORD_KEYCODES

    # Caps Lock is always suppressed by its own fixed keycode (57) while
    # Toplevel windows are open. Keep this variable for compatibility with
    # older call sites, but do not repurpose it as the record hotkey.
    _suppress_keycode = 57

    # Any hotkey change can leave a modifier/key marked as down from the old
    # selection. Clear state so the next physical press starts fresh.
    try:
        _modifier_keys_down.clear()
        _pressed_keys.clear()
    except Exception:
        pass

    if log:
        kind = "modifier" if _record_key_is_modifier else "regular"
        log_event("input", f"record hotkey active: {label} keycode={_record_keycode} ({kind})")


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
    "spark desktop": "formal email tone, proper punctuation, capitalize first word",
    "readdle":  "formal email tone, proper punctuation, capitalize first word",
    "outlook":  "formal email tone, proper punctuation, capitalize first word",
    "notes":    "clear concise notes format",
    # We use broader keywords to catch terminal/coding apps
    "iterm":    "technical precise language",
    "terminal": "technical precise language",
    "code":     "technical precise language",
    "visual studio code": "technical precise language",
}

# ── Writing Profiles ─────────────────────────────────────────────────────────
# Professional profile prompts are intentionally conservative. They guide
# Ollama's cleanup style without changing the working model/options.
WRITING_PROFILES = {
    "General": (
        "Use balanced everyday dictation cleanup. Preserve the speaker's wording and intent."
    ),
    "Professional": (
        "Make the text clear, polished, and professional without sounding stiff. Do not add content."
    ),
    "Email": (
        "Use complete sentences and a polite professional tone. Do not add greetings, sign-offs, subjects, or recipients unless dictated."
    ),
    "Developer": (
        "Preserve technical terms, commands, package names, filenames, paths, variables, acronyms, casing, and symbols. Do not convert commands into prose."
    ),
    "Medical": (
        "Preserve clinical terminology, medication names, measurements, acronyms, and dictated structure. Do not infer diagnoses, findings, or clinical facts."
    ),
    "Legal": (
        "Use precise formal language. Preserve names, dates, clauses, citations, and quoted language. Do not invent facts or legal conclusions."
    ),
    "Sales": (
        "Make the text concise, client-friendly, persuasive, and clear while preserving factual meaning."
    ),
    "Notes": (
        "Format as clean notes when appropriate. Keep wording concise. Use bullets only if the speaker clearly dictated a list."
    ),
    "Creative": (
        "Improve flow and readability while preserving the speaker's voice, style, and meaning."
    ),
    "Verbatim": (
        "Use minimal cleanup only. Preserve the original wording. Fix only punctuation, spacing, capitalization, and obvious recognition errors."
    ),
}

PROFILE_OPTIONS = list(WRITING_PROFILES.keys())

APP_PROFILE_RULES = {
    "mail": "Email",
    "spark": "Email",
    "spark desktop": "Email",
    "readdle": "Email",
    "outlook": "Email",
    "gmail": "Email",
    "terminal": "Developer",
    "iterm": "Developer",
    "visual studio code": "Developer",
    "code": "Developer",
    "xcode": "Developer",
    "notes": "Notes",
    "notion": "Notes",
    "obsidian": "Notes",
    "word": "Professional",
    "pages": "Professional",
    "slack": "General",
    "messages": "General",
    "teams": "General",
}

def get_active_writing_profile(app_name: str | None = None) -> str:
    """Return the selected writing profile, optionally auto-detected by app.

    This is deliberately a pure settings/app-name lookup. It does not touch
    Tkinter, audio, subprocesses, or model settings, so it is safe to call from
    the dictation pipeline.
    """
    default_profile = settings.get("writing_profile", "General")
    if default_profile not in WRITING_PROFILES:
        default_profile = "General"

    if settings.get("auto_profile_detection", True) and app_name:
        app_lower = app_name.lower()
        for key, profile in APP_PROFILE_RULES.items():
            if key in app_lower and profile in WRITING_PROFILES:
                return profile
    return default_profile

JARVIS_COMMANDS = {
    "open": "open_app", "search": "web_search", "email": "send_email",
    "volume": "set_volume", "screenshot": "take_screenshot", "remind": "set_reminder",
    "calendar": "check_calendar", "close": "close_app", "play": "play_media", "weather": "check_weather",
}

# ── Local intent detection & formatting (no Ollama) ─────────────────────────

# ── Packaged-app safe logging ─────────────────────────────────────────────────
# In a PyInstaller .app bundle stdout/stderr may be closed. Any print() call
# from a daemon thread after that raises ValueError: I/O operation on closed
# file. Use _safe_print() for all background-thread logging.
def _safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except (ValueError, OSError):
        pass

def _run_on_main(fn):
    """Run fn() on the Tk main thread and block until it completes.

    pynput's darwin Controller calls TSMGetInputSourceProperty to resolve
    characters to key codes.  TSM requires the main thread; calling it from
    a background thread raises dispatch_assert_queue_fail in the packaged
    .app.  Use this trampoline for every pynput press/type call that originates
    from a worker thread.
    """
    if threading.current_thread() is threading.main_thread():
        return fn()
    done = threading.Event()
    result_box = [None]
    def _call():
        try:
            result_box[0] = fn()
        finally:
            done.set()
    app.root.after(0, _call)
    done.wait()
    return result_box[0]

# ── openwakeword model path resolver ─────────────────────────────────────────
def _get_oww_model_path() -> str:
    """Return the absolute path to hey_jarvis_v0.1.onnx.

    Checks (in order):
      1. sys._MEIPASS — PyInstaller bundle, data files extracted here
      2. The openwakeword package's own resources directory

    Returns an empty string if the file cannot be found.
    """
    import os
    candidates = []

    # 1. Bundled app: PyInstaller extracts openwakeword data to _MEIPASS
    if hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(
            sys._MEIPASS, "openwakeword", "resources", "models",
            "hey_jarvis_v0.1.onnx"))

    # 2. Running from source: ask the package where it lives
    try:
        import openwakeword as _oww_pkg
        pkg_dir = os.path.dirname(_oww_pkg.__file__)
        candidates.append(os.path.join(
            pkg_dir, "resources", "models", "hey_jarvis_v0.1.onnx"))
    except Exception:
        pass

    for path in candidates:
        if os.path.exists(path):
            return path
    return ""

# ── Ollama async refinement engine ───────────────────────────────────────────
# A single persistent worker thread keeps the model warm between calls.
# transcribe_and_type submits a job and waits up to OLLAMA_TIMEOUT seconds.
# If Ollama is still thinking by then, raw Whisper text is used immediately.
#
# BUG FIX (stale result): the worker uses a job_id to tag each result.
# If the caller has already timed out, the worker discards its own result
# rather than leaving it in the queue to poison the next dictation.
OLLAMA_TIMEOUT = 12.0  # seconds — llama3:latest (8B) needs more headroom on Intel
OLLAMA_MODEL   = "qwen2.5:3b"   # recommended model — shown in onboarding UI

import uuid as _uuid

# ── Ollama status detection ───────────────────────────────────────────────────
# Values: "ready" | "not_installed" | "not_running" | "model_missing"
# Cached at startup; refreshed by the "Check Again" button in Settings.
_ollama_status_cache: str = "unknown"

def _check_ollama_status(model: str = OLLAMA_MODEL) -> str:
    """Return one of: ready | not_installed | not_running | model_missing.

    Checks are fast shell probes — this is safe to call from any thread.
    Does NOT start Ollama or download anything.
    """
    import shutil, subprocess as _sp
    # 1. Is the ollama Python library installed?
    try:
        import ollama as _ol  # noqa: F401
    except ImportError:
        _safe_print("[ollama] status: not installed")
        return "not_installed"

    # 2. Is the ollama CLI present on PATH?  (library can be installed even if
    #    the desktop app is not — check both.)
    cli_present = shutil.which("ollama") is not None

    # 3. Is the server responding?
    try:
        _sp.run(["ollama", "list"], capture_output=True, timeout=3, check=True)
    except (FileNotFoundError, _sp.CalledProcessError, _sp.TimeoutExpired):
        # CLI missing OR server not running
        if not cli_present:
            _safe_print("[ollama] status: not installed")
            return "not_installed"
        _safe_print("[ollama] status: server not running")
        return "not_running"
    except Exception:
        _safe_print("[ollama] status: server not running")
        return "not_running"

    # 4. Is the recommended model present?
    try:
        result = _sp.run(["ollama", "list"], capture_output=True, timeout=5, text=True)
        if model not in result.stdout:
            _safe_print(f"[ollama] status: model missing ({model})")
            return "model_missing"
    except Exception:
        _safe_print("[ollama] status: model missing (list failed)")
        return "model_missing"

    _safe_print("[ollama] status: ready")
    return "ready"


def _refresh_ollama_status() -> str:
    """Re-run status check, update cache, and return the result."""
    global _ollama_status_cache
    _ollama_status_cache = _check_ollama_status()
    return _ollama_status_cache

# Queues carry (job_id, text, writing_profile) tuples so stale results can be identified
_ollama_req_q: _queue.Queue = _queue.Queue(maxsize=1)
_ollama_res_q: _queue.Queue = _queue.Queue(maxsize=1)
_ollama_current_job_id: str = ""   # set by ollama_query, read by worker

# Strict minimal-edit prompt tuned for small models (1b/3b).
# Small models need a fill-in-the-blank frame rather than rule lists —
# rules get "reasoned about" which causes rewriting. The echo-with-fixes
# frame makes rewriting grammatically harder to do.
_OLLAMA_SYSTEM_PROMPT = (
    "You are a dictation cleanup engine. "
    "Correct only the text the user dictated. "
    "Preserve the user's exact meaning, wording, and intent. "
    "Do not answer questions. "
    "Do not continue the conversation. "
    "Do not add new information. "
    "Do not expand short phrases into longer responses. "
    "Do not rewrite the text unless it is clearly needed. "
    "Fix obvious speech-to-text errors, punctuation, capitalization, grammar, and spacing. "
    "If the input is already clear, return it unchanged. "
    "Return only the corrected dictation text."
)

def _ollama_prompt_for_strength(profile: str | None = None) -> str:
    strength = settings.get("correction_strength", "Standard")
    active_profile = profile if profile in WRITING_PROFILES else settings.get("writing_profile", "General")
    if active_profile not in WRITING_PROFILES:
        active_profile = "General"

    prompt = (
        _OLLAMA_SYSTEM_PROMPT + " "
        f"Active writing profile: {active_profile}. "
        + WRITING_PROFILES[active_profile] + " "
    )

    if strength == "Light":
        return (
            prompt +
            "Use light correction only: punctuation, capitalization, spacing, and obvious word errors. "
            "Keep the original wording whenever possible."
        )
    if strength == "Strong":
        return (
            prompt +
            "You may smooth awkward dictated phrasing, but you must not add ideas, answer questions, or change the speaker's intent."
        )
    return prompt


def _ollama_worker():
    """Persistent background thread — model stays warm, no cold-start per call."""
    try:
        import ollama as _ol
    except ImportError:
        _safe_print("[ollama] status: not installed")
        return
    _safe_print("[ollama] status: ready")
    while True:
        job = _ollama_req_q.get()         # blocks until a job arrives
        if job is None: break             # poison pill — exit
        job_id, text, profile = job
        try:
            t0 = time.time()
            resp = _ol.chat(
                model=OLLAMA_MODEL,
                messages=[
                    {"role": "system", "content": _ollama_prompt_for_strength(profile)},
                    {"role": "user", "content": text},
                ],
                options={
                    "repeat_penalty": 1.15,
                    "num_predict": 180,
                    "temperature": 0.35,
                    "top_P": 0.85,
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
            _safe_print(f"[ollama] {elapsed:.2f}s → {result!r}")
        except Exception as e:
            _safe_print(f"[ollama] worker error: {e}")
            result = None

        # Only post result if the caller is still waiting for THIS job_id.
        # If it already timed out (_ollama_current_job_id changed), discard.
        if job_id == _ollama_current_job_id:
            try:
                _ollama_res_q.put_nowait((job_id, result))
            except _queue.Full:
                pass   # caller timed out between our check and put — discard

# Probe Ollama status once at startup in a background thread so the UI
# can show the correct badge without blocking the main thread.
threading.Thread(target=_refresh_ollama_status, daemon=True, name="ollama-status").start()

threading.Thread(target=_ollama_worker, daemon=True, name="ollama-worker").start()

def ollama_query(text: str, profile: str | None = None) -> str:
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
        _ollama_req_q.put_nowait((job_id, text, profile or settings.get("writing_profile", "General")))
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


def _dictation_words(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9']+", text or "")

def _is_short_phrase_for_ollama(text: str) -> bool:
    """Short dictations are usually commands/questions; Whisper + punctuation is safer."""
    words = _dictation_words(text)
    return len(words) <= 4

def _is_question_like(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    question_starters = (
        "what", "when", "where", "who", "why", "how", "which", "whose",
        "is", "are", "was", "were", "will", "would", "could", "should",
        "do", "does", "did", "have", "has", "had", "can", "may", "might",
        "am", "isn't", "aren't", "wasn't", "weren't", "don't", "doesn't",
    )
    first = _dictation_words(t)[:1]
    return t.endswith("?") or (first and first[0] in question_starters)

def _looks_like_assistant_answer(text: str) -> bool:
    t = (text or "").strip().lower()
    suspicious_starts = (
        "sure", "certainly", "here is", "here's", "i can", "i will", "you should",
        "the next", "next is", "to improve", "it sounds like", "based on", "as an ai",
        "let's", "we should", "you asked", "the answer", "this means",
    )
    return any(t.startswith(p) for p in suspicious_starts)

def _ollama_result_is_safe(original: str, refined: str) -> tuple[bool, str]:
    """Reject Ollama results that look like replies, expansions, or meaning changes."""
    if not refined or refined.lower().strip() == "nothing":
        return False, "empty result"

    orig = (original or "").strip()
    out = (refined or "").strip()
    if not orig:
        return False, "empty original"

    orig_words = _dictation_words(orig.lower())
    out_words = _dictation_words(out.lower())
    if not out_words:
        return False, "empty output"

    # Most dangerous failure mode: short prompt becomes a long assistant answer.
    if len(orig_words) <= 6 and len(out_words) > max(10, len(orig_words) * 3):
        return False, "expanded short dictation"

    if _is_question_like(orig) and not _is_question_like(out):
        return False, "question became non-question"

    if _looks_like_assistant_answer(out):
        return False, "looks like assistant response"

    # Avoid accepting outputs that introduce too many new words.
    orig_set = set(orig_words)
    if len(orig_words) >= 3 and orig_set:
        new_words = [w for w in out_words if w not in orig_set]
        if len(new_words) > max(6, len(orig_words)):
            return False, "too many new words"

    # Very large expansion is almost never a dictation correction.
    if len(out) > max(len(orig) * 2.2, len(orig) + 80):
        return False, "output too long"

    return True, "accepted"

def _should_skip_ollama(text: str) -> tuple[bool, str]:
    if settings.get("safe_mode", False):
        return True, "safe mode"

    # ai_cleanup_mode: "off" always skips; "on" skips if unavailable;
    # "auto" (default) skips silently if unavailable — never shows an error.
    mode = settings.get("ai_cleanup_mode", "auto")
    if mode == "off":
        return True, "disabled"
    if not settings.get("use_ollama", True) or not OLLAMA_ENABLED:
        return True, "disabled"

    # For "on" mode, check live status and log clearly.
    # For "auto" mode, the worker will fail gracefully anyway — no extra check needed.
    if mode == "on":
        status = _ollama_status_cache
        if status == "not_installed":
            _safe_print("[ollama] cleanup skipped — unavailable (not installed)")
            return True, "unavailable"
        if status == "not_running":
            _safe_print("[ollama] cleanup skipped — unavailable (server not running)")
            return True, "unavailable"
        if status == "model_missing":
            _safe_print("[ollama] cleanup skipped — unavailable (model missing)")
            return True, "unavailable"

    if settings.get("correction_strength", "Standard") == "Off":
        return True, "correction off"
    if _is_short_phrase_for_ollama(text):
        return True, "short phrase"
    return False, ""

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

    if rule_key in ("mail", "spark", "spark desktop", "readdle", "outlook", "word", "pages"):
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


def _open_first_available_app(candidates, show_message=True):
    """Open the first macOS app name that exists.

    Some apps use different bundle/display names on different Macs. Spark is
    commonly reported as "Spark Desktop" on Apple Silicon and "Spark" on some
    Intel installs. Keep this helper small and side-effect-light so Jarvis
    commands can try safe fallbacks without changing the rest of the command
    system.
    """
    seen = set()
    for candidate in candidates:
        candidate = (candidate or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            result = subprocess.run(
                ["open", "-a", candidate],
                capture_output=True,
                text=True,
                timeout=4,
            )
            if result.returncode == 0:
                if show_message and app:
                    app.show_message(f"Opening {candidate}", "#30d158")
                return candidate
        except Exception as e:
            print(f"[jarvis] open app fallback failed for {candidate}: {e}")
    return ""


def _preferred_email_app_candidates(preferred: str = ""):
    """Return email app fallbacks, with Spark Desktop first for M1 Macs."""
    candidates = [preferred, "Spark Desktop", "Spark", "Mail", "Microsoft Outlook"]
    cleaned = []
    for item in candidates:
        item = (item or "").strip()
        if item and item not in cleaned:
            cleaned.append(item)
    return cleaned

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

        elif action == "open_email_app":
            opened = _open_first_available_app(
                _preferred_email_app_candidates(params.get("preferred", "")),
                show_message=True,
            )
            if not opened and app:
                app.show_message("Could not open email app", "#ff3b30")

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
            spark_app = _open_first_available_app(["Spark Desktop", "Spark"], show_message=False) or "Spark Desktop"
            safe_spark_app = _osa_escape(spark_app)
            lines = [
                f'tell application "{safe_spark_app}" to activate',
                'delay 2.5',
                'tell application "System Events"',
                f'    tell process "{safe_spark_app}"',
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
            if app: app.show_message(f"Composing email to {to[:20]}" if to else f"Opening {spark_app}", "#30d158")

        elif action == "close_app":
            app_name = params.get("app", "")
            safe_name = _osa_escape(app_name)
            subprocess.run(["osascript", "-e", f'tell application "{safe_name}" to quit'])
            if app: app.show_message(f"Closing {app_name}", "#30d158")

        elif action == "custom_command":
            cmd_action = params.get("action", "")
            target     = params.get("target", "").strip()
            trigger    = params.get("trigger", "command")
            if cmd_action == "open_url":
                if target:
                    subprocess.Popen(["open", target])
                    if app: app.show_message(f"Opening {target[:35]}", "#30d158")
            elif cmd_action == "open_app":
                if target:
                    result = subprocess.run(["open", "-a", target], capture_output=True)
                    if result.returncode != 0:
                        subprocess.Popen(["open", "-a", target.lower()])
                    if app: app.show_message(f"Opening {target}", "#30d158")
            elif cmd_action == "type_text":
                if target:
                    paste_text(target)

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
    import symspellpy as _symspellpy_pkg
    _sym = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
    _DICT = os.path.join(os.path.dirname(_symspellpy_pkg.__file__), "frequency_dictionary_en_82_765.txt")
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
    "use_ollama": True,
    "play_sounds": True,
    "show_startup_tips": True,
    "first_run_complete": False,
    "onboarding_shown_version": "",
    "min_record_seconds": MIN_RECORD_SECONDS,
    "hotkey_debounce_seconds": HOTKEY_DEBOUNCE_SECONDS,
    "safe_mode": False,
    "ai_cleanup_mode": "auto",   # "auto" | "on" | "off"
    "correction_strength": "Standard",
    "writing_profile": "General",
    "auto_profile_detection": True,
    "show_active_profile": True,
    "wake_dictation_grace_seconds": WAKE_DICTATION_GRACE_SECONDS,
    "wake_dictation_silence_seconds": WAKE_DICTATION_SILENCE_SECONDS,
    "wake_dictation_max_seconds": WAKE_DICTATION_MAX_SECONDS,
    "wake_dictation_silence_rms": WAKE_DICTATION_SILENCE_RMS,
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


HOTKEY_OPTIONS = {
    "Right Option": Key.alt_r,
    "F13": Key.f13,
    "F14": Key.f14,
    "F15": Key.f15,
}

def get_record_key(): return HOTKEY_OPTIONS.get(settings.get("hotkey_label", "Right Option"), Key.alt_r)

# Recover immediately from unsupported hotkeys saved by earlier experimental builds.
# This keeps Right Option working on first launch before the Settings window is opened.
if settings.get("hotkey_label", "Right Option") not in HOTKEY_OPTIONS:
    settings["hotkey_label"] = "Right Option"
    try:
        save_settings(settings)
    except Exception:
        pass

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
# Live input level is updated by the existing audio stream. Mic Test must read
# this value instead of opening a second PortAudio stream, which can crash
# macOS/PortAudio when the main dictation stream is already active.
_live_audio_rms, _live_audio_ts = 0.0, 0.0
snippet_state, snippet_trigger, dictation_history, history_index, last_transcribed_text = None, "", [], -1, ""
_last_jarvis_time, wake_listening, wake_frames, wake_lock, wake_whisper = 0.0, False, [], threading.Lock(), None
_wake_cooldown_until = 0.0
_wake_active = threading.Event()
_recording_started_by_wake = False

# ── Keyboard listener — kept as an explicit reference so settings windows can
# temporarily stop it while open (prevents Caps Lock SIGILL on Intel Mac)
_kb_listener: "keyboard.Listener | None" = None
_open_wins:   int  = 0   # number of Toplevel windows currently open

def _start_kb_listener():
    """Start (or restart) the pynput keyboard listener.
    Must be called from a background thread — _kb_listener.wait() blocks."""
    global _kb_listener
    if _kb_listener is not None:
        try:
            _kb_listener.stop()
        except Exception:
            pass
        _kb_listener = None
    current_keys.clear()
    _kb_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    _kb_listener.start()
    try:
        _kb_listener.wait()   # block until the tap is fully installed and ready
    except Exception:
        pass

def _stop_kb_listener():
    """Stop the pynput keyboard listener synchronously."""
    global _kb_listener
    if _kb_listener is not None:
        try:
            _kb_listener.stop()
        except Exception:
            pass
        _kb_listener = None
    current_keys.clear()

def _toplevel_opened():
    """Call immediately when any Toplevel window (history/snippets/settings) opens.
    Sets the Caps Lock suppression flag and stops pynput on the first open."""
    global _open_wins
    _open_wins += 1
    globals()["_suppress_caps_lock"] = True
    # Flush modifier state so the record key can't be "stuck down" while the
    # window is open — mismatched press/release across the open/close boundary
    # corrupts Tkinter thread state and causes the GIL abort on next dictation.
    _modifier_keys_down.clear()
    if _open_wins == 1:           # first window: shut down pynput thread
        _stop_kb_listener()
        print("[system] pynput listener stopped (window open)")

def _toplevel_closed():
    """Call when any Toplevel window closes (from its <Destroy> handler).
    Restarts pynput 800 ms after the LAST window is gone, giving Tk time to
    finish all Destroy processing before pynput installs a new CGEventTap."""
    global _open_wins
    _open_wins = max(0, _open_wins - 1)
    # Flush modifier state on close too — the key may have been pressed/released
    # while the window had focus and never reached the tap's tracking set.
    _modifier_keys_down.clear()
    if _open_wins == 0:
        # Delay restart: Tk must finish processing Destroy events completely
        # before we install a new pynput tap in a background thread.
        app.root.after(800, _schedule_listener_restart)

def _schedule_listener_restart():
    """Kept for compatibility — just clears the Caps Lock suppression flag.
    pynput is never stopped/restarted (restarting while Tkinter runs causes SIGILL).
    The two active Quartz taps handle Caps Lock suppression instead."""
    globals()["_suppress_caps_lock"] = False

def _release_caps_suppress():
    """Legacy: clear Caps Lock suppression flag (kept for any remaining callsites)."""
    globals()["_suppress_caps_lock"] = False

_shutdown_event = threading.Event()   # set by _quit_clean to unblock start_backend

def _quit_clean():
    """Graceful shutdown — avoids the semaphore leak warning from os._exit."""
    _shutdown_event.set()
    try:
        if app and app.root:
            app.root.quit()   # exits mainloop cleanly
    except Exception:
        pass
    import sys as _sys
    _sys.exit(0)

SNIPPETS_FILE         = os.path.expanduser("~/.dictation_snippets.json")
CUSTOM_COMMANDS_FILE  = os.path.expanduser("~/.dictation_custom_commands.json")

def load_custom_commands() -> list:
    try:
        if os.path.exists(CUSTOM_COMMANDS_FILE):
            with open(CUSTOM_COMMANDS_FILE) as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception:
        pass
    return []

def save_custom_commands(commands: list):
    try:
        with open(CUSTOM_COMMANDS_FILE, "w") as f:
            json.dump(commands, f, indent=2)
    except Exception as e:
        print(f"[custom_commands] save error: {e}")

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

def save_history(text, app_name, whisper_text=None, ollama_text=None, final_text=None, status="pasted", profile=None):
    """Save dictation history with enough detail to review quality later."""
    try:
        history = []
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE) as f:
                history = json.load(f)
        history.append({
            "text": text,
            "final_text": final_text or text,
            "whisper_text": whisper_text or "",
            "ollama_text": ollama_text or "",
            "status": status,
            "app": app_name,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "model": settings.get("model", "unknown"),
            "ollama_enabled": bool(settings.get("use_ollama", True)),
            "safe_mode": bool(settings.get("safe_mode", False)),
            "correction_strength": settings.get("correction_strength", "Standard"),
            "writing_profile": profile or settings.get("writing_profile", "General"),
            "auto_profile_detection": bool(settings.get("auto_profile_detection", True)),
        })
        with open(HISTORY_FILE, "w") as f:
            json.dump(history[-500:], f, indent=2)
    except Exception as e:
        print(f"[history] save error: {e}")

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
    """Combines manual vocabulary from settings with learned history."""
    try:
        # 1. Grab your manual list from the Settings window
        manual_vocab = settings.get("manual_vocabulary", "").strip()
        
        # 2. Grab the automated history
        vocab = load_vocab()
        word_counts = vocab.get("word_counts", {})
        top_words = sorted(word_counts, key=word_counts.get, reverse=True)[:20]
        
        # 3. Combine them into one hint for Whisper
        prompt = "Transcribe accurately."
        if manual_vocab:
            prompt += f" Technical terms: {manual_vocab}."
        if top_words:
            prompt += f" Common words: {', '.join(top_words)}."
            
        return prompt
    except Exception:
        return "Transcribe spoken English accurately."

def get_active_app_name():
    try: return subprocess.check_output(["osascript", "-e", 'tell application "System Events" to get name of first application process whose frontmost is true'], timeout=1).decode().strip()
    except Exception: return ""

def play_sound(name, block=False):
    if not settings.get("play_sounds", True):
        return
    sounds = {"start": "/System/Library/Sounds/Tink.aiff", "stop": "/System/Library/Sounds/Pop.aiff"}
    sound_path = sounds.get(name)
    if not sound_path:
        return
    try:
        if block:
            subprocess.run(["afplay", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["afplay", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log_event("audio", f"sound skipped: {e}")

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

def get_live_input_rms(max_age: float = 2.0):
    """Return the latest input RMS from the already-open audio stream.

    This avoids opening a second sounddevice/PortAudio stream for mic testing,
    which can crash on macOS when the dictation/wake stream is active.
    """
    if _live_audio_ts <= 0 or (time.time() - _live_audio_ts) > max_age:
        return None
    return float(_live_audio_rms)

def audio_callback(indata, frames, time_info, status):
    global _live_audio_rms, _live_audio_ts
    try:
        _live_audio_rms = float(np.sqrt(np.mean(indata ** 2)))
        _live_audio_ts = time.time()
    except Exception:
        pass

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
    """Paste dictated text reliably without leaving the clipboard changed.

    Clipboard flow: save → write → verify → send Cmd+V → restore (always).

    Cmd+V transport order:
      1. pynput Controller (works in .app without Automation/System Events)
      2. Quartz CGEventPost (fallback if pynput unavailable)
      3. typer.type() character-by-character (last resort)

    osascript / System Events is intentionally not used — it requires a separate
    Automation TCC grant that the packaged .app does not have by default.
    """
    with _paste_lock:
        paste_payload = (text + " ").encode()
        import subprocess as _sp
        import time as _t

        log_event("paste", f"preparing {len(text)} chars")
        prev = _sp.run(["pbpaste"], capture_output=True, timeout=2).stdout

        try:
            # ── 1. Write + verify clipboard ───────────────────────────────────
            verified = False
            for attempt in range(8):
                _sp.run(["pbcopy"], input=paste_payload, timeout=2)
                _t.sleep(0.08 + attempt * 0.03)
                if _sp.run(["pbpaste"], capture_output=True, timeout=2).stdout == paste_payload:
                    verified = True
                    log_event("paste", "clipboard verified")
                    break
                log_event("paste", f"retry {attempt + 1}")

            if not verified:
                log_event("paste", "clipboard verification failed — typing directly")
                _run_on_main(lambda: typer.type(text + " "))
                return

            # ── 2. Send Cmd+V ─────────────────────────────────────────────────
            sent = False

            # Primary: pynput Controller — no osascript/System Events needed.
            # Must run on main thread: pynput calls TSMGetInputSourceProperty
            # to resolve 'v' → keycode, which requires the main dispatch queue.
            try:
                from pynput.keyboard import Controller as _KbdCtrl, Key as _Key
                def _pynput_cmd_v():
                    _kbd = _KbdCtrl()
                    with _kbd.pressed(_Key.cmd):
                        _kbd.press('v')
                        _kbd.release('v')
                _run_on_main(_pynput_cmd_v)
                log_event("paste", "sent cmd+v")
                sent = True
            except Exception as _pe:
                log_event("paste", f"pynput cmd+v failed ({_pe})")

            # Fallback: Quartz CGEventPost.
            if not sent:
                try:
                    import Quartz as _Q
                    _V = 9  # keycode for 'v'
                    _dn = _Q.CGEventCreateKeyboardEvent(None, _V, True)
                    _up = _Q.CGEventCreateKeyboardEvent(None, _V, False)
                    _Q.CGEventSetFlags(_dn, _Q.kCGEventFlagMaskCommand)
                    _Q.CGEventSetFlags(_up, _Q.kCGEventFlagMaskCommand)
                    _Q.CGEventPost(_Q.kCGHIDEventTap, _dn)
                    _t.sleep(0.05)
                    _Q.CGEventPost(_Q.kCGHIDEventTap, _up)
                    log_event("paste", "sent cmd+v")
                    sent = True
                except Exception as _qe:
                    log_event("paste", f"CGEventPost cmd+v failed ({_qe})")

            if not sent:
                log_event("paste", "cmd+v failed — typing directly")
                _run_on_main(lambda: typer.type(text + " "))
                return

            # Give the target app time to consume the clipboard before restore.
            _t.sleep(0.35)

        finally:
            # Always restore the previous clipboard.
            try:
                _sp.run(["pbcopy"], input=prev, timeout=2)
                log_event("paste", "restored previous clipboard")
            except Exception:
                pass

def smart_punctuate(text):
    if not text or text.rstrip()[-1] in ".!?": return text
    question_starters = ("what", "when", "where", "who", "why", "how", "which", "whose", "is ", "are ", "was ", "were ", "will ", "would ", "could ", "should ", "do ", "does ", "did ", "have ", "has ", "had ", "can ", "may ", "might ", "shall ", "am ", "isn't", "aren't", "wasn't", "weren't", "don't", "doesn't", "didn't", "won't", "wouldn't", "couldn't")
    if any(text.lower().strip().startswith(q) for q in question_starters): return text.rstrip() + "?"
    return text.rstrip() + "."

def _fast_jarvis_match(lower):
    import re
    # ── Custom user commands — checked before all built-ins ───────────────
    for _cmd in load_custom_commands():
        _trigger = _cmd.get("trigger", "").lower().strip()
        if not _trigger or len(_trigger.split()) < 2:
            continue
        if lower == _trigger:
            return ("custom_command", _cmd)
    # ── Built-in commands ─────────────────────────────────────────────────
    open_match = re.match(r"^open (.+)$", lower)
    if open_match:
        target = open_match.group(1).strip()
        if target in ("email", "inbox", "mail", "spark", "my email"):
            return ("open_email_app", {"preferred": "Spark Desktop"})
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
        return ("open_email_app", {"preferred": "Spark Desktop"})

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

def _deduplicate_whisper(text: str) -> str:
    """Collapse Whisper hallucination loops (e.g. 'Testing. Testing. Testing...').

    Whisper sometimes gets stuck generating the same word or phrase hundreds of
    times on short or noisy audio. This detects a repeating window of 1-6 words
    at the start of the output and returns only the first occurrence.
    """
    words = text.split()
    if len(words) < 8:
        return text
    for window in range(1, 7):
        chunk = words[:window]
        i, repeats = window, 1
        while i + window <= len(words) and words[i:i + window] == chunk:
            repeats += 1
            i += window
        if repeats >= 3:
            log_event("whisper", f"hallucination detected — collapsed {len(words)} words to {window}")
            return " ".join(chunk)
    return text


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

    # --- THIS IS THE AREA TO REPLACE ---
    personal_prompt = get_personal_prompt()
    
    # ADD THIS: This lets you see the Vocabulary list in your terminal
    print(f"[whisper-hint] {personal_prompt}")

    language_to_use = "en" if not settings.get("auto_detect", True) else None

    # beam_size=1 (greedy) is 3-5x faster than beam_size=5 on Intel CPU
    _BEAM = 1

    if settings.get("cloud_mode") and not settings.get("safe_mode", False) and get_openai_key():
        raw_text = transcribe_cloud(wav_path)
        if not raw_text:
            segments, _ = whisper.transcribe(wav_path, beam_size=_BEAM, language=language_to_use, condition_on_previous_text=False, initial_prompt=personal_prompt, vad_filter=True, no_speech_threshold=0.6, compression_ratio_threshold=2.4)
            raw_text = " ".join(seg.text for seg in segments).strip()
    else:
        segments, _ = whisper.transcribe(wav_path, beam_size=_BEAM, language=language_to_use, condition_on_previous_text=False, initial_prompt=personal_prompt, vad_filter=True, no_speech_threshold=0.6, compression_ratio_threshold=2.4)
        raw_text = " ".join(seg.text for seg in segments).strip()

    # Ollama refinement — protected by short-phrase bypass and a safety filter.
    # This keeps Ollama as a cleanup layer instead of letting it answer the user.
    def _is_repetitive(t):
        words = t.lower().split()
        return len(words) >= 4 and len(set(words)) / len(words) < 0.4

    raw_text = _deduplicate_whisper(raw_text)
    whisper_text = raw_text
    ollama_text = ""
    ollama_status = "not used"
    active_app = get_active_app_name()
    active_profile = get_active_writing_profile(active_app)
    log_event("whisper", repr(whisper_text))
    log_event("profile", f"{active_profile}" + (f" via {active_app}" if active_app else ""))

    skip_ollama, skip_reason = _should_skip_ollama(raw_text)
    if raw_text and not _is_repetitive(raw_text) and not skip_ollama:
        refined = ollama_query(raw_text, active_profile)
        ollama_text = refined or ""
        ok, reason = _ollama_result_is_safe(raw_text, refined or "")
        if ok:
            log_event("ollama", f"accepted — {refined!r}")
            ollama_status = "accepted"
            raw_text = refined
        else:
            log_event("ollama", f"rejected — {reason} — {refined!r}")
            ollama_status = f"rejected: {reason}"
            if app and settings.get("show_startup_tips", True):
                app.show_message("AI cleanup rejected — used original text", "#ff9f0a")
    else:
        ollama_status = f"skipped: {skip_reason or 'repetitive input'}"
        log_event("ollama", ollama_status)
        if app and settings.get("show_startup_tips", True) and skip_reason == "short phrase":
            app.show_message("Short phrase — skipped AI cleanup", "#0a84ff")

    if not raw_text:
        app.set_state("idle")
        return

    # 1. Use the final protected raw_text for output so "UI" stays "UI"
    _prev_last_text = last_text   # save before overwrite — used by formatting commands
    text = smart_punctuate(apply_snippets(symspell_correct(raw_text)))
    last_text = text
    log_event("final", repr(text))
    
    # 2. Use a separate variable 'lower' ONLY for background command checks
    lower = re.sub(r"[^a-z0-9 ]", "", raw_text.lower()).strip()
    print(f"[cmd] {lower!r}")

    if JARVIS_ENABLED and not settings.get("safe_mode", False):
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
        _run_on_main(lambda cmd=PUNCT_COMMANDS[lower]: typer.type(cmd))
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
        def _select_all():
            with typer.pressed(Key.cmd):
                typer.press("a"); typer.release("a")
        _run_on_main(_select_all)
        app.show_message("Select all", "#0a84ff")
        app.set_state("idle")
        return

    # ── Formatting commands ────────────────────────────────────────────────────
    # Two modes:
    #   Inline:     "testing one two all caps"  → strips trigger, formats preceding text only
    #   Standalone: says "all caps" alone        → backspaces prev recording, formats it
    def _apply_fmt(triggers, fmt_fn, label):
        global last_text
        hit = next((p for p in triggers if p in lower), None)
        if hit is None:
            return False
        # Inline: check whether there is real content before the trigger in this transcription
        hit_idx = text.lower().find(hit)
        before = text[:hit_idx].strip(" .,!? ") if hit_idx > 0 else ""
        if before:
            # Inline — type only the formatted preceding text, skip the trigger phrase
            formatted = fmt_fn(before)
            last_text = formatted
            paste_text(formatted)
            app.show_message(label, "#0a84ff")
            app.set_state("idle")
            return True
        # Standalone — backspace the previous recording and replace with formatted version
        target = _prev_last_text
        if not target:
            return False
        for _ in range(len(target) + 1):
            typer.press(Key.backspace); typer.release(Key.backspace)
        formatted = fmt_fn(target)
        last_text = formatted
        paste_text(formatted)
        app.show_message(label, "#0a84ff")
        app.set_state("idle")
        return True

    if _apply_fmt(("make bold", "bold that"),                                    lambda t: f"**{t}**",                                                "Bolded!"): return
    if _apply_fmt(("make italic", "italic that"),                                lambda t: f"*{t}*",                                                  "Italicized!"): return
    if _apply_fmt(("format as code", "code that", "make code"),                  lambda t: f"`{t}`",                                                  "Code formatted!"): return
    if _apply_fmt(("make heading", "heading that", "make title"),                lambda t: f"# {t}",                                                  "Heading!"): return
    if _apply_fmt(("all caps", "make caps", "capitalize that"),                  lambda t: t.upper(),                                                 "ALL CAPS!"): return
    if _apply_fmt(("make bullet", "bullet that", "create list", "make list"),    lambda t: "\n".join(f"• {s.strip()}" for s in t.split('.') if s.strip()), "Bulleted!"): return
    if _apply_fmt(("make quote", "quote that", "block quote"),                   lambda t: f"> {t}",                                                  "Quoted!"): return
    if _apply_fmt(("strikethrough that", "strike that"),                         lambda t: f"~~{t}~~",                                                "Strikethrough!"): return

    if lower in ("copy that", "copy last"):
        if last_text:
            subprocess.run(["osascript", "-e", f'set the clipboard to "{last_text}"'], timeout=2)
            app.show_message("Copied!", "#0a84ff")
        else:
            app.show_message("Nothing to copy", "#ff9f0a")
        app.set_state("idle")
        return
        
    if lower == "copy all":
        def _copy_all():
            with typer.pressed(Key.cmd):
                typer.press("a"); typer.release("a")
            time.sleep(0.05)
            with typer.pressed(Key.cmd):
                typer.press("c"); typer.release("c")
        _run_on_main(_copy_all)
        app.show_message("Copied all!", "#0a84ff")
        app.set_state("idle")
        return

    if lower in ("paste", "paste that"):
        def _paste_cmd():
            with typer.pressed(Key.cmd):
                typer.press("v"); typer.release("v")
        _run_on_main(_paste_cmd)
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

    if settings.get("context_format") and active_app:
        app.show_message("Formatting...", "#0a84ff")
        formatted = format_for_app(text, active_app)
        if formatted and formatted != text:
            text = formatted

    app.set_transcript(text)
    paste_text(text)

    def _background_tasks(t=text, a=active_app, w=whisper_text, o=ollama_text, st=ollama_status, prof=active_profile):
        save_history(t, a, whisper_text=w, ollama_text=o, final_text=t, status=st, profile=prof)
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
        hwin = tk.Toplevel(app.root)
        hwin.title("Dictation History")
        hwin.geometry("850x600") # Larger window to prevent cutting off text
        hwin.configure(bg="#1a1a1a")
        hwin.attributes("-topmost", True)
        # Keep History visually consistent with Settings and Snippets.
        # This was accidentally lost during the v6 menu-bar stability pass.
        hwin.attributes("-alpha", 0.97)
        globals()["_suppress_caps_lock"] = True
        def _hwin_close():
            hwin.destroy()
            try:
                app.root.after(300, _release_caps_suppress)
            except Exception:
                _release_caps_suppress()
        hwin.protocol("WM_DELETE_WINDOW", _hwin_close)
        hwin.bind("<Escape>", lambda e: _hwin_close())

        # --- Sidebar (exact colours from Settings/Snippets) ---
        BG      = "#141414"
        SIDEBAR = "#1e1e1e"
        SEP     = "#2e2e2e"
        FG      = "#f0f0f0"
        DIM     = "#6a6a6a"
        ACC     = "#0a84ff"
        FONT    = "Helvetica Neue"
        hwin.configure(bg=BG)
        sidebar = tk.Frame(hwin, bg=SIDEBAR, width=210)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        # Vertical separator between sidebar and content — matches Settings
        tk.Frame(hwin, bg=SEP, width=1).pack(side="left", fill="y")
        # Header — exact same pattern as Snippets window
        hdr = tk.Frame(sidebar, bg=SIDEBAR, height=60)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        _hist_icon = None
        try:
            from PIL import Image, ImageTk
            _hist_path = os.path.join(
                getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.argv[0]))),
                "dictate_icon.png"
            )
            _hist_pil = Image.open(_hist_path).convert("RGBA").resize((22, 22), Image.LANCZOS)
            _hist_icon = ImageTk.PhotoImage(_hist_pil)
            hwin._hist_icon = _hist_icon
        except Exception:
            _hist_icon = None
        if _hist_icon:
            tk.Label(hdr, image=_hist_icon, bg=SIDEBAR).place(x=14, rely=0.5, anchor="w")
            tk.Label(hdr, text="History", bg=SIDEBAR, fg=FG,
                     font=(FONT, 14, "bold")).place(x=42, rely=0.5, anchor="w")
        else:
            tk.Label(hdr, text="🎙", bg=SIDEBAR, fg=FG,
                     font=(FONT, 18)).place(x=14, rely=0.5, anchor="w")
            tk.Label(hdr, text="History", bg=SIDEBAR, fg=FG,
                     font=(FONT, 14, "bold")).place(x=40, rely=0.5, anchor="w")
        close_btn_h = tk.Label(hdr, text="✕", bg=SIDEBAR, fg=DIM,
                               font=(FONT, 12), cursor="hand2")
        close_btn_h.place(relx=1.0, x=-14, rely=0.5, anchor="e")
        close_btn_h.bind("<Button-1>", lambda e: hwin.destroy())
        close_btn_h.bind("<Enter>", lambda e: close_btn_h.configure(fg=FG))
        close_btn_h.bind("<Leave>", lambda e: close_btn_h.configure(fg=DIM))
        tk.Frame(sidebar, bg="#2e2e2e", height=1).pack(fill="x")

        BG_CARD = "#242424"
        BG_MAIN = BG

        # --- Close button packed first so it anchors to bottom ---
        tk.Frame(hwin, bg="#2e2e2e", height=1).pack(side="bottom", fill="x")
        btn_bar = tk.Frame(hwin, bg=BG_MAIN, height=60)
        btn_bar.pack(side="bottom", fill="x")
        btn_bar.pack_propagate(False)

        # Rounded blue Close button drawn on a Canvas
        def _make_rounded_btn(parent, text, cmd, bg_col, fg_col, font):
            btn_w, btn_h = PRIMARY_BUTTON_W, ACTION_BUTTON_H
            c = tk.Canvas(parent, width=btn_w, height=btn_h, bg=BG_MAIN,
                          highlightthickness=0, cursor="hand2")
            def _draw(col):
                c.delete("all")
                r = 8
                c.create_arc(0, 0, 2*r, 2*r, start=90, extent=90, fill=col, outline=col)
                c.create_arc(btn_w-2*r, 0, btn_w, 2*r, start=0, extent=90, fill=col, outline=col)
                c.create_arc(0, btn_h-2*r, 2*r, btn_h, start=180, extent=90, fill=col, outline=col)
                c.create_arc(btn_w-2*r, btn_h-2*r, btn_w, btn_h, start=270, extent=90, fill=col, outline=col)
                c.create_rectangle(r, 0, btn_w-r, btn_h, fill=col, outline=col)
                c.create_rectangle(0, r, btn_w, btn_h-r, fill=col, outline=col)
                c.create_text(btn_w//2, btn_h//2, text=text, fill=fg_col, font=font)
            _draw(bg_col)
            c.bind("<Button-1>", lambda e: cmd())
            c.bind("<Enter>",    lambda e: _draw("#1a6fd4"))
            c.bind("<Leave>",    lambda e: _draw(bg_col))
            return c

        cb = _make_rounded_btn(btn_bar, "Close", hwin.destroy, ACC, FG,
                               (FONT, 12, "bold"))
        cb.pack(side="right", padx=(0, WINDOW_EDGE_PAD), pady=13)

        # --- Main Content Pane ---
        content = tk.Frame(hwin, bg=BG_MAIN)
        content.pack(side="right", fill="both", expand=True, padx=16, pady=16)
        tk.Label(content, text="Recent Dictations",
                 font=(FONT, 18, "bold"), bg=BG_MAIN, fg=FG).pack(anchor="w", pady=(0, 12))

        h_frame = tk.Frame(content, bg=BG_MAIN)
        h_frame.pack(fill="both", expand=True)

        h_scroll = tk.Scrollbar(h_frame, orient="vertical", bg=BG_MAIN,
                                troughcolor=BG_MAIN, width=10, bd=0)
        h_scroll.pack(side="right", fill="y")

        list_canvas = tk.Canvas(h_frame, bg=BG_MAIN, highlightthickness=0,
                                yscrollcommand=h_scroll.set)
        list_canvas.pack(side="left", fill="both", expand=True)
        h_scroll.config(command=list_canvas.yview)

        inner = tk.Frame(list_canvas, bg=BG_MAIN)
        inner.bind("<Configure>",
                   lambda e: list_canvas.configure(scrollregion=list_canvas.bbox("all")))
        list_canvas.create_window((0, 0), window=inner, anchor="nw",
                                  width=list_canvas.winfo_reqwidth())
        # Keep inner width in sync when canvas resizes
        list_canvas.bind("<Configure>",
            lambda e: list_canvas.itemconfig(1, width=e.width))

        # --- GLOBAL HOVER SCROLL FIX ---
        def _on_mousewheel(event):
            # This forces the list to scroll even if the mouse is over a card
            list_canvas.yview_scroll(int(-1 * event.delta), "units")

        # We bind to 'hwin' (the whole window) instead of just the canvas
        # This makes the entire area "active" for scrolling
        hwin.bind_all("<MouseWheel>", _on_mousewheel)

        # Cleanup — fires when hwin itself is destroyed (all close paths reach here).
        # The widget check is CRITICAL: <Destroy> propagates from child widgets too,
        # so without it every _rounded_card's temporary measure.destroy() would
        # trigger this handler mid-construction and corrupt listener state.
        def _hwin_destroy(e):
            if e.widget is not hwin:
                return
            hwin.unbind_all("<MouseWheel>")
            app.root.after(300, _release_caps_suppress)
        hwin.bind("<Destroy>", _hwin_destroy)

        # --- History rows with rounded-corner canvas cards ---
        def _rounded_card(parent, text_str, meta_str):
            """Draw a rounded-corner card using Canvas, embed Text widget inside."""
            W_CARD = 580
            PAD    = 12

            # Height estimate: ~22px per line, min 2 lines.
            # The temporary measure-widget approach was removed because it called
            # measure.destroy() which bubbled a <Destroy> event to hwin and
            # triggered the cleanup handler mid-construction.
            char_per_line = 62
            n_lines = max(2, -(-len(text_str) // char_per_line))
            card_h = n_lines * 22 + 58  # text + meta + padding

            c = tk.Canvas(parent, width=W_CARD, height=card_h, bg=BG_MAIN,
                          highlightthickness=0)
            c.pack(fill="x", padx=8, pady=5)

            # Draw rounded rect
            r = 10
            x1, y1, x2, y2 = 0, 0, W_CARD, card_h
            col = BG_CARD
            c.create_arc(x1, y1, x1+2*r, y1+2*r, start=90,  extent=90,  fill=col, outline=col)
            c.create_arc(x2-2*r, y1, x2, y1+2*r, start=0,   extent=90,  fill=col, outline=col)
            c.create_arc(x1, y2-2*r, x1+2*r, y2, start=180, extent=90,  fill=col, outline=col)
            c.create_arc(x2-2*r, y2-2*r, x2, y2, start=270, extent=90,  fill=col, outline=col)
            c.create_rectangle(x1+r, y1, x2-r, y2,   fill=col, outline=col)
            c.create_rectangle(x1, y1+r, x2, y2-r,   fill=col, outline=col)

            # Embed selectable Text widget inside canvas
            tf = tk.Frame(c, bg=BG_CARD, bd=0)
            t = tk.Text(tf, font=(FONT, 14), bg=BG_CARD, fg=FG,
                        height=n_lines, wrap="word", relief="flat",
                        highlightthickness=0, padx=0, pady=0, bd=0)
            t.insert("1.0", text_str)
            t.config(state="disabled")
            t.pack(fill="x")
            _bind_copy_paste(t)

            ml = tk.Label(tf, text=meta_str, bg=BG_CARD, fg="#888888",
                          font=(FONT, 11))
            ml.pack(anchor="w", pady=(4, 0))
            c.create_window(PAD, PAD, window=tf, anchor="nw",
                            width=W_CARD - 2*PAD)

        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, "r") as f:
                    history = json.load(f)
                for item in reversed(history[-100:]):
                    final_txt = item.get("final_text") or item.get("text", "")
                    whisper_txt = item.get("whisper_text", "")
                    ollama_txt = item.get("ollama_text", "")
                    status = item.get("status", "")
                    profile = item.get("writing_profile", "")
                    if whisper_txt or ollama_txt or status or profile:
                        detail_lines = [f"Final: {final_txt}"]
                        if whisper_txt and whisper_txt != final_txt:
                            detail_lines.append(f"Whisper: {whisper_txt}")
                        if ollama_txt:
                            detail_lines.append(f"Ollama: {ollama_txt}")
                        if status:
                            detail_lines.append(f"Status: {status}")
                        if profile:
                            detail_lines.append(f"Profile: {profile}")
                        display_txt = "\n".join(detail_lines)
                    else:
                        display_txt = final_txt
                    _rounded_card(inner, display_txt,
                                  f"{item.get('app', '')} • {item.get('timestamp', '')}")
        except Exception:
            pass

# This is th    e start of the next function, at the very edge of the left margin
def _trigger_wake():
    global recording, audio_frames, cancelled, _wake_cooldown_until, _recording_started_by_wake, _record_started_at
    if recording or time.time() < _wake_cooldown_until:
        return
    with wake_lock:
        wake_frames.clear()
    with _audio_lock:
        audio_frames = []
    # Small buffer so the wake phrase itself is not included in the dictation.
    time.sleep(0.3)
    with _audio_lock:
        audio_frames = []
    cancelled = False
    recording = True
    _recording_started_by_wake = True
    # Wake-word recording is a real dictation session, not a record-key tap.
    # Set the start timestamp so the shared stop path can measure duration
    # correctly and will not show the short-tap HUD message when silence stops it.
    _record_started_at = time.time()
    _wake_active.set()
    _wake_cooldown_until = time.time() + 5.0
    app.capture_active_app()
    app.set_state("recording")
    app.root.after(0, app.start_wave)
    app.root.after(100, lambda: app.canvas.itemconfig(
        app.label, text="Keep speaking · press ⌥ to stop", fill=app.TEXT_WHITE
    ))
    log_event("wake", "Jarvis dictation started")
    threading.Thread(target=play_sound, args=("start",), daemon=True).start()
    threading.Thread(target=_silence_stop_monitor, daemon=True).start()

def _silence_stop_monitor():
    """Auto-stop only wake-word dictation after a natural pause.

    The old values were tuned for short Jarvis commands and could cut off longer
    Developer/Profile tests. This monitor gives wake dictation a longer grace
    period, lower silence threshold, and longer required quiet window.
    """
    start_time = time.time()
    silence_since = None
    grace_seconds = _setting_float("wake_dictation_grace_seconds", WAKE_DICTATION_GRACE_SECONDS)
    silence_seconds = _setting_float("wake_dictation_silence_seconds", WAKE_DICTATION_SILENCE_SECONDS)
    max_seconds = _setting_float("wake_dictation_max_seconds", WAKE_DICTATION_MAX_SECONDS)
    silence_rms = _setting_float("wake_dictation_silence_rms", WAKE_DICTATION_SILENCE_RMS)

    while recording and _recording_started_by_wake:
        time.sleep(0.1)
        elapsed = time.time() - start_time

        if elapsed >= max_seconds:
            log_event("wake", f"auto-stop after max duration ({max_seconds:.0f}s)")
            _queue_input_event("wake_auto_stop")
            return

        if elapsed < grace_seconds:
            silence_since = None
            continue

        with _audio_lock:
            last_frame = audio_frames[-1] if audio_frames else None
        if last_frame is None:
            continue

        rms = float(np.sqrt(np.mean(last_frame ** 2)))
        if rms < silence_rms:
            if silence_since is None:
                silence_since = time.time()
            elif time.time() - silence_since >= silence_seconds:
                log_event("wake", f"auto-stop after {silence_seconds:.1f}s silence")
                _queue_input_event("wake_auto_stop")
                return
        else:
            silence_since = None

def _wake_word_loop():
    """Wake word listener — restarts automatically if onnxruntime crashes."""
    global recording
    _restart_delay = 5.0   # seconds to wait before restarting after a crash
    while True:
        try:
            _wake_word_loop_inner()
        except Exception as e:
            _safe_print(f"[wake] crashed ({type(e).__name__}: {e}) — restarting in {_restart_delay:.0f}s")
            time.sleep(_restart_delay)
        else:
            # _wake_word_loop_inner returned normally (wake disabled / not available)
            return

def _wake_word_loop_inner():
    global recording
    try:
        # ── Load hey_jarvis wake-word model ───────────────────────────────────
        # Pass the model NAME "hey_jarvis" (not a file path) so openwakeword
        # uses it as the prediction dict key.  Passing a full path makes the
        # key the filename-without-extension ("hey_jarvis_v0.1"), which breaks
        # the oww.predict(...).get("hey_jarvis", 0) check below.
        #
        # In a packaged .app, openwakeword.get_pretrained_model_paths() may be
        # missing.  We patch a stub onto the module so Model.__init__ doesn't
        # crash, then let it resolve the bundled .onnx via the stub.
        import openwakeword as _oww_mod
        if not hasattr(_oww_mod, "get_pretrained_model_paths"):
            _oww_path = _get_oww_model_path()
            def _oww_stub(framework="onnx"):
                return [_oww_path] if _oww_path else []
            _oww_mod.get_pretrained_model_paths = _oww_stub
            _safe_print("[wake] patched openwakeword.get_pretrained_model_paths (bundled app)")

        # Force ONNX Runtime to use a single thread with no internal thread pool.
        # Multiple inter-op threads cause onnxruntime to spawn C++ threads that
        # call Py_BEGIN_ALLOW_THREADS from contexts with no PyThreadState on
        # macOS / Python 3.11, producing the fatal GIL abort.
        try:
            import onnxruntime as _ort
            _sess_opts = _ort.SessionOptions()
            _sess_opts.inter_op_num_threads = 1
            _sess_opts.intra_op_num_threads = 1
            _sess_opts.execution_mode = _ort.ExecutionMode.ORT_SEQUENTIAL
            from openwakeword.model import Model as WakeModel
            oww = WakeModel(wakeword_models=["hey_jarvis"], inference_framework="onnx",
                            openwakeword_models_kwargs={"sess_options": _sess_opts})
        except Exception:
            # SessionOptions kwarg not supported in all versions — fall back without it
            from openwakeword.model import Model as WakeModel
            oww = WakeModel(wakeword_models=["hey_jarvis"], inference_framework="onnx")

        _safe_print("[wake] ready — say 'Hey Jarvis' to start dictating")
    except Exception as e:
        _safe_print(f"[wake] openwakeword failed ({e}), wake word disabled")
        return

    buf = []
    while True:
        if recording or not WAKE_ENABLED:
            buf.clear()
            time.sleep(0.1)
            continue

        if time.time() < _wake_cooldown_until:
            time.sleep(0.1)
            continue

        with wake_lock:
            new_frames = list(wake_frames)
            wake_frames.clear()

        for frame in new_frames:
            audio = frame[:, 0]
            target_len = int(len(audio) * 16000 / SAMPLE_RATE)
            if target_len < 1:
                continue
            resampled = np.interp(
                np.linspace(0, len(audio) - 1, target_len),
                np.arange(len(audio)), audio
            )
            buf.extend(resampled.tolist())

        triggered = False
        while len(buf) >= 1280:
            chunk = np.array(buf[:1280], dtype=np.float32)
            del buf[:1280]
            try:
                if oww.predict((chunk * 32767).astype(np.int16)).get("hey_jarvis", 0) > 0.75:
                    triggered = True
                    buf.clear()
                    break
            except Exception:
                buf.clear()
                break

        if triggered and not recording:
            threading.Thread(target=_trigger_wake, daemon=True).start()
            time.sleep(0.3)
            while recording:
                time.sleep(0.2)
            buf.clear()
            try:
                oww.reset()
            except Exception:
                pass
            while time.time() < _wake_cooldown_until:
                time.sleep(0.1)
            try:
                for key in oww.prediction_buffer:
                    oww.prediction_buffer[key] = [0.0] * len(oww.prediction_buffer[key])
            except Exception:
                pass
            _safe_print("[wake] listening for 'Hey Jarvis'...")
            continue

        time.sleep(0.05)

def _stop_recording():
    global recording, _wake_cooldown_until, _recording_started_by_wake
    if not recording: return
    recording = False
    _recording_started_by_wake = False
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
    global _transcription_busy
    if _transcription_busy:
        log_event("record", "transcription already running — skipped overlapping request")
        if app:
            app.show_message("Still finishing previous dictation", "#ff9f0a")
        return

    _transcription_busy = True
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name
    try:
        log_event("record", f"processing {len(frames)} audio chunks")
        save_wav(frames, wav_path)
        transcribe_and_type(wav_path, frames)
    except Exception as e:
        log_event("error", f"processing failed: {e}")
        if app:
            app.show_message("Dictation processing error", "#ff3b30")
    finally:
        _transcription_busy = False
        try:
            os.unlink(wav_path)
        except Exception:
            pass

def on_press(key):
    global recording, audio_frames, cancelled
    # INTEL STABILITY: Caps Lock is the specific trigger for the Intel MKL /
    # Tkinter register conflict ("illegal hardware instruction"). Return
    # immediately so the audio thread is never disturbed. All other keys,
    # including modifier keys used for recording and shortcuts, must pass through.
    if key == Key.caps_lock:
        return
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

def _get_app_launch_target() -> str:
    """Return the best path to launch this app from Login Items."""
    exe = os.path.abspath(getattr(sys, "executable", "") or sys.argv[0])
    # PyInstaller/py2app .app layout: .../Name.app/Contents/MacOS/Name
    marker = ".app/Contents/MacOS"
    if marker in exe:
        return exe[:exe.index(marker) + 4]
    return os.path.abspath(sys.argv[0])


def _app_launch_name() -> str:
    target = _get_app_launch_target()
    if target.endswith('.app'):
        return os.path.basename(target[:-4])
    return "Jarvis Dictation"


def _launch_at_login_enabled() -> bool:
    """Check login item status. Best-effort; returns False if unavailable."""
    try:
        name = _osa_escape(_app_launch_name())
        script = f'tell application "System Events" to exists login item "{name}"'
        out = subprocess.check_output(["osascript", "-e", script], timeout=3).decode().strip().lower()
        return out == "true"
    except Exception:
        return bool(settings.get("launch_at_login", False))


def _set_launch_at_login(enabled: bool) -> bool:
    """Create/remove a macOS Login Item for the packaged app or current script."""
    target = _get_app_launch_target()
    name = _osa_escape(_app_launch_name())
    target_esc = _osa_escape(target)
    try:
        if enabled:
            script = (
                'tell application "System Events"\n'
                f'    if not (exists login item "{name}") then\n'
                f'        make login item at end with properties {{path:"{target_esc}", hidden:false, name:"{name}"}}\n'
                '    end if\n'
                'end tell'
            )
        else:
            script = (
                'tell application "System Events"\n'
                f'    if exists login item "{name}" then delete login item "{name}"\n'
                'end tell'
            )
        subprocess.run(["osascript", "-e", script], timeout=5, check=True)
        settings["launch_at_login"] = bool(enabled)
        save_settings(settings)
        return True
    except Exception as e:
        log_event("menu", f"launch-at-login update failed: {e}")
        return False


def _open_system_permissions() -> None:
    """Open the most useful macOS privacy pane for this app."""
    try:
        subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])
    except Exception:
        try:
            subprocess.Popen(["open", "/System/Applications/System Settings.app"])
        except Exception:
            pass


def _show_about_window() -> None:
    if not app or not getattr(app, "root", None):
        return
    def _show():
        BG, CARD, FG, DIM, ACC = "#141414", "#222222", "#f0f0f0", "#8a8a8a", "#0a84ff"
        w = tk.Toplevel(app.root)
        w.title("About Jarvis Dictation")
        w.configure(bg=BG)
        w.attributes("-topmost", True)
        # Match the subtle translucency used by Settings, Snippets, and History.
        try:
            w.attributes("-alpha", 0.97)
        except Exception:
            pass
        w.resizable(False, False)
        W, H = 460, 360
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        w.geometry(f"{W}x{H}+{sw//2-W//2}+{sh//2-H//2}")
        w.bind("<Escape>", lambda e: w.destroy())
        _toplevel_opened()
        def _destroy(evt):
            if evt.widget == w:
                _toplevel_closed()
        w.bind("<Destroy>", _destroy)

        # Use the app PNG when available. Emoji rendering differs between
        # Tk/macOS builds and can display as a broken/glitched icon.
        icon_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.argv[0])))
        icon_path = os.path.join(icon_dir, "dictate_icon.png")
        icon_loaded = False
        try:
            from PIL import Image, ImageTk
            if os.path.exists(icon_path):
                img = Image.open(icon_path).convert("RGBA").resize((58, 58), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                w._about_icon = photo
                tk.Label(w, image=photo, bg=BG).pack(pady=(24, 4))
                icon_loaded = True
        except Exception:
            icon_loaded = False
        if not icon_loaded:
            badge = tk.Label(w, text="J", bg=ACC, fg="#ffffff", width=3, height=1,
                             font=("Helvetica Neue", 26, "bold"))
            badge.pack(pady=(26, 6))
        tk.Label(w, text="Jarvis Dictation", bg=BG, fg=FG,
                 font=("Helvetica Neue", 22, "bold")).pack()
        tk.Label(w, text=APP_VERSION, bg=BG, fg=DIM,
                 font=("Helvetica Neue", 12)).pack(pady=(4, 16))
        card = tk.Frame(w, bg=CARD)
        card.pack(fill="x", padx=28, pady=(0, 18))
        msg = (
            "Private Mac-first dictation powered by local Whisper, optional Ollama cleanup, "
            "and Jarvis voice commands.\n\n"
            "Hold or press your record key, speak naturally, and let the app type into the active Mac app."
        )
        tk.Label(card, text=msg, bg=CARD, fg=FG, wraplength=370,
                 justify="center", font=("Helvetica Neue", 12)).pack(padx=18, pady=18)
        # Match the rounded canvas button style used by Settings, Snippets,
        # and History. Native Tk buttons can render square/inconsistent on macOS.
        btn_w, btn_h, r = PRIMARY_BUTTON_W, ACTION_BUTTON_H, 8
        btn = tk.Canvas(w, width=btn_w, height=btn_h, bg=BG,
                        highlightthickness=0, cursor="hand2")
        btn.pack(pady=(0, 18))

        def _paint_done(hover=False):
            col = "#1a6fd4" if hover else ACC
            btn.delete("all")
            btn.create_arc(0, 0, 2*r, 2*r, start=90, extent=90, fill=col, outline=col)
            btn.create_arc(btn_w-2*r, 0, btn_w, 2*r, start=0, extent=90, fill=col, outline=col)
            btn.create_arc(0, btn_h-2*r, 2*r, btn_h, start=180, extent=90, fill=col, outline=col)
            btn.create_arc(btn_w-2*r, btn_h-2*r, btn_w, btn_h, start=270, extent=90, fill=col, outline=col)
            btn.create_rectangle(r, 0, btn_w-r, btn_h, fill=col, outline=col)
            btn.create_rectangle(0, r, btn_w, btn_h-r, fill=col, outline=col)
            btn.create_text(btn_w//2, btn_h//2, text="Done", fill="#ffffff",
                            font=("Helvetica Neue", 12, "bold"), anchor="center")

        _paint_done(False)
        btn.bind("<Button-1>", lambda e: w.destroy())
        btn.bind("<Enter>", lambda e: _paint_done(True))
        btn.bind("<Leave>", lambda e: _paint_done(False))
    app.root.after(0, _show)


class MenuBarApp:
    """Native macOS menu-bar controller.

    The menu is intentionally a thin control layer over the stable Tk/Quartz
    app.  It does not touch audio, Whisper, Ollama, or the low-level HID tap
    directly; it schedules the same safe queue/Tk actions used by the hotkey.
    """
    def __init__(self):
        self._available = False
        self._state = "idle"
        try:
            from AppKit import NSStatusBar, NSVariableStatusItemLength, NSMenu, NSMenuItem, NSImage
            from Foundation import NSObject

            class MenuDelegate(NSObject):
                def startStop_(self, sender):
                    _queue_input_event("menu_start_stop")

                def cancelDictation_(self, sender):
                    _queue_input_event("cancel")

                def toggleHUD_(self, sender):
                    _queue_input_event("menu_toggle_hud")

                def toggleSafeMode_(self, sender):
                    _queue_input_event("menu_toggle_safe_mode")

                def toggleWake_(self, sender):
                    _queue_input_event("menu_toggle_wake")

                def toggleJarvis_(self, sender):
                    _queue_input_event("menu_toggle_jarvis")

                def toggleLaunchAtLogin_(self, sender):
                    _queue_input_event("menu_toggle_launch_at_login")

                def openSettings_(self, sender):
                    _queue_input_event("open_settings")

                def showSnippets_(self, sender):
                    _queue_input_event("menu_show_snippets")

                def showHistory_(self, sender):
                    _queue_input_event("menu_show_history")

                def showAbout_(self, sender):
                    _queue_input_event("menu_show_about")

                def openPermissions_(self, sender):
                    _queue_input_event("menu_open_permissions")


                def selectModel_(self, sender):
                    _queue_input_event("menu_select_model::" + str(sender.title()))

                def selectHotkey_(self, sender):
                    _queue_input_event("menu_select_hotkey::" + str(sender.title()))

                def selectStrength_(self, sender):
                    _queue_input_event("menu_select_strength::" + str(sender.title()))

                def selectProfile_(self, sender):
                    _queue_input_event("menu_select_profile::" + str(sender.title()))

                def quitApp_(self, sender):
                    _queue_input_event("menu_quit")

            self._delegate = MenuDelegate.alloc().init()
            self._NSImage = NSImage
            bar = NSStatusBar.systemStatusBar()
            self._item = bar.statusItemWithLength_(NSVariableStatusItemLength)
            self._menu = NSMenu.alloc().init()

            self._status_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Status: Idle", None, "")
            self._menu.addItem_(self._status_item)

            self._primary_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Start Dictation", "startStop:", "")
            self._primary_item.setTarget_(self._delegate)
            self._menu.addItem_(self._primary_item)

            self._cancel_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Cancel Recording", "cancelDictation:", "")
            self._cancel_item.setTarget_(self._delegate)
            self._menu.addItem_(self._cancel_item)
            self._menu.addItem_(NSMenuItem.separatorItem())

            self._toggle_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Hide HUD", "toggleHUD:", "")
            self._toggle_item.setTarget_(self._delegate)
            self._menu.addItem_(self._toggle_item)

            self._safe_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Safe Mode", "toggleSafeMode:", "")
            self._safe_item.setTarget_(self._delegate)
            self._menu.addItem_(self._safe_item)

            self._wake_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Wake Word", "toggleWake:", "")
            self._wake_item.setTarget_(self._delegate)
            self._menu.addItem_(self._wake_item)

            self._jarvis_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Jarvis Commands", "toggleJarvis:", "")
            self._jarvis_item.setTarget_(self._delegate)
            self._menu.addItem_(self._jarvis_item)
            self._menu.addItem_(NSMenuItem.separatorItem())

            self._model_menu = NSMenu.alloc().init()
            model_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Whisper Model", None, "")
            for m in ["tiny.en", "base.en", "small.en", "medium.en", "large-v2", "large-v3", "distil-medium.en", "distil-large-v3"]:
                mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(m, "selectModel:", "")
                mi.setTarget_(self._delegate)
                self._model_menu.addItem_(mi)
            model_item.setSubmenu_(self._model_menu)
            self._menu.addItem_(model_item)

            self._hotkey_menu = NSMenu.alloc().init()
            hotkey_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Record Key", None, "")
            for k in ["Right Option", "F13", "F14", "F15"]:
                hi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(k, "selectHotkey:", "")
                hi.setTarget_(self._delegate)
                self._hotkey_menu.addItem_(hi)
            hotkey_item.setSubmenu_(self._hotkey_menu)
            self._menu.addItem_(hotkey_item)

            self._strength_menu = NSMenu.alloc().init()
            strength_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Correction Strength", None, "")
            for s in ["Light", "Standard", "Strong", "Off"]:
                si = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(s, "selectStrength:", "")
                si.setTarget_(self._delegate)
                self._strength_menu.addItem_(si)
            strength_item.setSubmenu_(self._strength_menu)
            self._menu.addItem_(strength_item)

            self._profile_menu = NSMenu.alloc().init()
            profile_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Writing Profile", None, "")
            for pr in PROFILE_OPTIONS:
                pi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(pr, "selectProfile:", "")
                pi.setTarget_(self._delegate)
                self._profile_menu.addItem_(pi)
            profile_item.setSubmenu_(self._profile_menu)
            self._menu.addItem_(profile_item)
            self._menu.addItem_(NSMenuItem.separatorItem())

            for title, action in [
                ("Open Settings...", "openSettings:"),
                ("Manage Snippets...", "showSnippets:"),
                ("Show History...", "showHistory:"),
                ("Open macOS Permissions...", "openPermissions:"),
            ]:
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
                item.setTarget_(self._delegate)
                self._menu.addItem_(item)

            self._menu.addItem_(NSMenuItem.separatorItem())
            self._launch_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Launch at Login", "toggleLaunchAtLogin:", "")
            self._launch_item.setTarget_(self._delegate)
            self._menu.addItem_(self._launch_item)

            about_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("About Jarvis Dictation", "showAbout:", "")
            about_item.setTarget_(self._delegate)
            self._menu.addItem_(about_item)

            quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit Jarvis Dictation", "quitApp:", "")
            quit_item.setTarget_(self._delegate)
            self._menu.addItem_(quit_item)

            self._item.setMenu_(self._menu)
            self._available = True
            self._refresh_menu_state()
            self._set_icon("idle")
            log_event("menu", "native macOS menu bar ready")
        except Exception as e:
            self._available = False
            log_event("menu", f"menu bar unavailable: {e}")

    def _set_check(self, item, checked: bool):
        try:
            item.setState_(1 if checked else 0)
        except Exception:
            pass

    def _refresh_menu_state(self):
        if not self._available:
            return
        self._toggle_item.setTitle_("Hide HUD" if settings.get("show_hud", True) else "Show HUD")
        self._set_check(self._safe_item, settings.get("safe_mode", False))
        self._set_check(self._wake_item, settings.get("wake_enabled", True))
        self._set_check(self._jarvis_item, settings.get("jarvis_enabled", True))
        self._set_check(self._launch_item, _launch_at_login_enabled())

        for i in range(self._model_menu.numberOfItems()):
            item = self._model_menu.itemAtIndex_(i)
            self._set_check(item, item.title() == settings.get("model"))
        for i in range(self._hotkey_menu.numberOfItems()):
            item = self._hotkey_menu.itemAtIndex_(i)
            self._set_check(item, item.title() == settings.get("hotkey_label"))
        for i in range(self._strength_menu.numberOfItems()):
            item = self._strength_menu.itemAtIndex_(i)
            self._set_check(item, item.title() == settings.get("correction_strength", "Standard"))
        if hasattr(self, "_profile_menu"):
            for i in range(self._profile_menu.numberOfItems()):
                item = self._profile_menu.itemAtIndex_(i)
                self._set_check(item, item.title() == settings.get("writing_profile", "General"))

        if self._state == "recording":
            self._primary_item.setTitle_("Stop Dictation")
            self._cancel_item.setEnabled_(True)
        elif self._state == "transcribing":
            self._primary_item.setTitle_("Processing...")
            self._primary_item.setEnabled_(False)
            self._cancel_item.setEnabled_(False)
        else:
            self._primary_item.setTitle_("Start Dictation")
            self._primary_item.setEnabled_(True)
            self._cancel_item.setEnabled_(False)

    def _set_icon(self, state):
        if not self._available:
            return
        # The shipped icon set only has idle/recording/transcribing.  Treat
        # any transient or unknown state as idle so the menu bar never stays
        # stuck on a status-only state after dictation completes.
        icon_state = state if state in ("idle", "recording", "transcribing") else "idle"
        icon_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.argv[0])))
        path = os.path.join(icon_dir, f"icon_{icon_state}.png")
        button = self._item.button()
        if os.path.exists(path):
            img = self._NSImage.alloc().initWithContentsOfFile_(path)
            if img:
                img.setSize_((18, 18))
                img.setTemplate_(True)
                # Keep a strong Python reference.  Without this, PyObjC/AppKit
                # can occasionally leave the previous status image displayed.
                self._current_icon = img
                button.setImage_(None)
                button.setTitle_("")
                button.setImage_(img)
                try:
                    button.setNeedsDisplay_(True)
                except Exception:
                    pass
                return
        self._current_icon = None
        button.setImage_(None)
        button.setTitle_({
            "idle": "🎙",
            "recording": "●",
            "transcribing": "…",
        }.get(icon_state, "🎙"))
        try:
            button.setNeedsDisplay_(True)
        except Exception:
            pass

    def _apply_state_now(self, state):
        if not self._available:
            return
        self._state = state
        self._set_icon(state)
        labels = {
            "idle": "Ready",
            "recording": "Recording...",
            "transcribing": "Transcribing...",
            "typing": "Typing...",
        }
        self._status_item.setTitle_(f"Status: {labels.get(state, state.capitalize())}")
        self._refresh_menu_state()

    def set_state(self, state):
        if not self._available:
            return
        if app and getattr(app, "root", None):
            app.root.after(0, lambda st=state: self._apply_state_now(st))
        else:
            self._apply_state_now(state)

    def force_state(self, state):
        """Apply a menu-bar state immediately from the Tk/AppKit thread."""
        self._apply_state_now(state)

    def _update_hud_label(self):
        self._refresh_menu_state()

menubar = None

class DictationApp:
    BG, PILL, TEXT_WHITE, TEXT_DIM, RED, BLUE, GREEN, ORANGE, W, H = "#1c1c1c", "#242424", "#ffffff", "#4a4a4a", "#ff3b30", "#0a84ff", "#30d158", "#ff9f0a", 420, 52

    def __init__(self, root):
        self.root, self._ready, self._blink_job, self._blink_on, self._msg_timer = root, False, None, True, None
        self._marquee_item = None
        self._marquee_running = False
        self._scroll_job = None
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

    def _start_marquee(self, text, color):
        """Scroll text across the HUD content area (x=47…W-55) in a loop."""
        self._stop_marquee()
        self.canvas.itemconfig(self.label, text="")          # hide static label
        self._marquee_item = self.canvas.create_text(
            self.W + 20, self.H // 2,
            text=text, font=("Helvetica Neue", 13), fill=color, anchor="w"
        )
        # Keep dot, appname, appicon and ✕ visually above the scrolling text
        self.canvas.tag_raise(self.dot)
        self.canvas.tag_raise(self.appname)
        self.canvas.tag_raise(self.appicon)
        self.canvas.tag_raise("close")
        self._marquee_x = float(self.W + 20)
        self._marquee_running = True
        self._tick_marquee()

    def _tick_marquee(self):
        if not self._marquee_running or not self._marquee_item:
            return
        self._marquee_x -= 1.5
        bb = self.canvas.bbox(self._marquee_item)
        if bb and bb[2] < 47:               # text fully past the divider — loop
            self._marquee_x = float(self.W + 20)
        self.canvas.coords(self._marquee_item, self._marquee_x, self.H // 2)
        self._scroll_job = self.root.after(30, self._tick_marquee)

    def _stop_marquee(self):
        self._marquee_running = False
        if self._scroll_job:
            self.root.after_cancel(self._scroll_job)
            self._scroll_job = None
        if self._marquee_item:
            try:
                self.canvas.delete(self._marquee_item)
            except Exception:
                pass
            self._marquee_item = None
        # Restore static label to its normal position/width
        self.canvas.coords(self.label, 80, self.H // 2)
        self.canvas.itemconfig(self.label, width=260)

    def _apply_state(self, state):
        if self._blink_job:
            self.root.after_cancel(self._blink_job)
            self._blink_job = None
        if state != "recording":
            self.stop_wave()
            self._stop_marquee()
        if state == "idle":
            self.canvas.itemconfig(self.dot, fill=self.TEXT_DIM)
            self.canvas.itemconfig(self.label, text="Hold ⌥ to dictate", fill=self.TEXT_DIM)
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

    _NUM_BARS = 22
    _BAR_W    = 2
    _BAR_STEP = 3   # 2px bar + 1px gap — 22 bars x 3px = 66px starting at x=8

    def start_wave(self):
        self.canvas.itemconfig(self.dot, state="hidden")
        self._bars = []
        cx = self.H // 2
        for i in range(self._NUM_BARS):
            x1 = 8 + i * self._BAR_STEP
            x2 = x1 + self._BAR_W
            self._bars.append(self.canvas.create_rectangle(
                x1, cx - 1, x2, cx + 1, fill=self.RED, outline=""))
        self._wave_phase = 0.0
        if recording:
            self._wave_job = self.root.after(30, self._animate_wave)
        else:
            self.root.after(0, self.stop_wave)

    def _animate_wave(self):
        if not hasattr(self, '_bars') or not self._bars: return
        try:
            import math
            scale = min(1.0, get_current_rms() * 18 + 0.15)
            self._wave_phase += 0.18
            cx  = self.H // 2
            mid = self._NUM_BARS / 2
            for i, bar in enumerate(self._bars):
                coords = self.canvas.coords(bar)
                if not coords: continue          # bar was deleted — skip safely
                dist   = abs(i - mid) / mid
                height = max(2, int((cx - 6) * scale *
                             (math.sin(self._wave_phase + i * 0.45) * 0.5 + 0.5) *
                             (1 - dist * 0.5)))
                brightness = int(255 * (1 - dist * 0.65))
                x1, _, x2, _ = coords
                self.canvas.coords(bar, x1, cx - height, x2, cx + height)
                self.canvas.itemconfig(bar,
                    fill=f"#{brightness:02x}{int(brightness*0.18):02x}{int(brightness*0.12):02x}")
        except Exception:
            pass  # never let a frame error kill the animation loop
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
        swin.attributes("-alpha", 1.0)
        swin.resizable(False, False)
        # Center on screen
        W, H = 720, 520
        sw, sh = swin.winfo_screenwidth(), swin.winfo_screenheight()
        swin.geometry(f"{W}x{H}+{sw//2 - W//2}+{sh//2 - H//2}")
        swin.update_idletasks()
        globals()["_suppress_caps_lock"] = True
        def _swin_close():
            swin.destroy()
            app.root.after(300, _release_caps_suppress)
        swin.protocol("WM_DELETE_WINDOW", _swin_close)
        # Close on Escape
        swin.bind("<Escape>", lambda e: _swin_close())
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
        _bind_copy_paste(se)

        # Snippet list
        list_canvas = tk.Canvas(sidebar, bg=SIDEBAR, highlightthickness=0)
        list_inner  = tk.Frame(list_canvas, bg=SIDEBAR)
        list_canvas.create_window((0, 0), window=list_inner, anchor="nw")
        list_inner.bind("<Configure>", lambda e: list_canvas.configure(scrollregion=list_canvas.bbox("all")))
        list_canvas.pack(fill="both", expand=True)

        # How-it-works note in sidebar
        tk.Frame(sidebar, bg=SEP, height=1).pack(fill="x")
        note_frame = tk.Frame(sidebar, bg=SIDEBAR)
        note_frame.pack(fill="x", padx=14, pady=10)
        tk.Label(note_frame, text="How snippets work", bg=SIDEBAR, fg=FG,
                 font=(FONT, 10, "bold"), justify="left").pack(anchor="w")
        tk.Label(note_frame,
                 text="Say a trigger phrase while\ndictating and Jarvis replaces\nit with the full expansion.",
                 bg=SIDEBAR, fg=DIM, font=(FONT, 9), justify="left").pack(anchor="w", pady=(3, 0))
        tk.Frame(sidebar, bg=SEP, height=1).pack(fill="x")
        tk.Label(sidebar,
                 text="Example:\n\"sign email\" →\n\"Best regards, John\"",
                 bg=SIDEBAR, fg=DIM, font=(FONT, 9), justify="left").pack(anchor="w", padx=14, pady=8)
        tk.Frame(sidebar, bg=SEP, height=1).pack(fill="x")

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

        tk.Label(body, text="TRIGGER PHRASE  —  what you say to activate this snippet",
                 bg=BG, fg=DIM, font=(FONT, 9, "bold")).pack(anchor="w")
        trigger_var = tk.StringVar()

        # Simple dark card frames — fully interactive, no canvas layering
        trigger_f = tk.Frame(body, bg=CARD, highlightthickness=0)
        trigger_f.pack(fill="x", pady=(4, 12))
        trigger_entry = tk.Entry(trigger_f, textvariable=trigger_var,
                                 bg=CARD, fg=FG, font=(FONT, 13),
                                 relief="flat", insertbackground=FG,
                                 bd=0, highlightthickness=0)
        trigger_entry.pack(fill="x", ipady=9, padx=10)
        _bind_copy_paste(trigger_entry)

        tk.Label(body, text="EXPANSION  —  the full text that gets typed when triggered",
                 bg=BG, fg=DIM, font=(FONT, 9, "bold")).pack(anchor="w")
        content_f = tk.Frame(body, bg=CARD, highlightthickness=0)
        content_f.pack(fill="both", expand=True, pady=(4, 8))
        content_text = tk.Text(content_f, bg=CARD, fg=FG, font=(FONT, 13),
                               relief="flat", insertbackground=FG, wrap="word",
                               padx=10, pady=10, bd=0, highlightthickness=0)
        content_text.pack(fill="both", expand=True)
        _bind_copy_paste(content_text)
        tk.Label(body, text="Tip: snippets match inside dictated sentences — you don't need to say them in isolation.",
                 bg=BG, fg=DIM, font=(FONT, 9), justify="left", wraplength=420).pack(anchor="w")

        def _btn(parent, text, cmd, accent=False, danger=False):
            """Rounded pill button drawn on a Canvas."""
            R = 7
            fg_col  = "#ffffff"
            bg_col  = ACC if accent else ("#2a2a2a" if not danger else "#2a2a2a")
            hover_col = "#1a6fd4" if accent else "#3a3a3a"
            text_col  = fg_col if accent else ("#ff453a" if danger else "#c0c0c0")

            # Consistent professional action-button sizing across Settings,
            # Snippets, and History windows. Primary buttons sit the same
            # distance from the right edge in every window.
            btn_w = PRIMARY_BUTTON_W if accent else SECONDARY_BUTTON_W
            btn_h = ACTION_BUTTON_H

            outer = tk.Frame(parent, bg=parent["bg"])
            right_pad = WINDOW_EDGE_PAD if accent else 12
            outer.pack(side="right", padx=(0, right_pad), pady=10)

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
        _bind_copy_paste_recursive(swin)

    def open_settings(self):
        # Pause wake word while settings UI is open.
        # NOTE: stream.stop()/close() was removed here — the Quartz HID tap
        # already prevents the Caps Lock SIGILL, so killing the audio stream
        # is unnecessary and causes a GIL abort when dictation resumes after
        # the window closes (stream is closed but never reopened).
        global WAKE_ENABLED
        globals()["WAKE_ENABLED"] = False

        # Brief yield so the UI thread is idle before opening the window.
        self.root.after(50, self._actual_open_ui)

    def _actual_open_ui(self):
        # 3. CLEAR UI QUEUE & LAUNCH (Only once!)
        self.root.update_idletasks()
        self.root.after(0, self._show_settings)

    def _show_settings(self):
        # --- STABILITY GUARD: Pause Wake Word while UI is active ---
        global WAKE_ENABLED
        old_wake_state = WAKE_ENABLED
        globals()["WAKE_ENABLED"] = False
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
        _win.attributes("-alpha", 1.0)
        _win.resizable(False, False)
        # Center on screen
        # Slightly taller to prevent bottom action buttons from being clipped
        # by the macOS/Tk title-bar/client-area calculation on some displays.
        W, H = 700, 680
        sw, sh = _win.winfo_screenwidth(), _win.winfo_screenheight()
        _win.geometry(f"{W}x{H}+{sw//2 - W//2}+{sh//2 - H//2}")
        _win.update_idletasks()
        # Treat Settings like the other utility windows so modifier state is
        # flushed correctly while changing record keys. This keeps Right Option
        # stable after switching away and back.
        _toplevel_opened()
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
        ai_cleanup_mode_var = tk.StringVar(value=settings.get("ai_cleanup_mode", "auto"))
        sounds_var = tk.BooleanVar(value=settings.get("play_sounds", True))
        startup_tips_var = tk.BooleanVar(value=settings.get("show_startup_tips", True))
        safe_mode_var = tk.BooleanVar(value=settings.get("safe_mode", False))
        correction_strength_var = tk.StringVar(value=settings.get("correction_strength", "Standard"))
        writing_profile_var = tk.StringVar(value=settings.get("writing_profile", "General"))
        auto_profile_var = tk.BooleanVar(value=settings.get("auto_profile_detection", True))
        show_profile_var = tk.BooleanVar(value=settings.get("show_active_profile", True))
        wake_grace_var = tk.StringVar(value=str(settings.get("wake_dictation_grace_seconds", WAKE_DICTATION_GRACE_SECONDS)))
        wake_silence_var = tk.StringVar(value=str(settings.get("wake_dictation_silence_seconds", WAKE_DICTATION_SILENCE_SECONDS)))
        wake_max_var = tk.StringVar(value=str(settings.get("wake_dictation_max_seconds", WAKE_DICTATION_MAX_SECONDS)))

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
            "Setup",
            "Dictation",
            "Audio",
            "AI Cleanup",
            "Writing Profiles",
            "Jarvis",
            "Custom Commands",
            "Vocabulary",
            "Cloud",
            "Help",
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
        tk.Label(footer, text="v6.1  ·  ⌃,  to open", bg=SIDEBAR, fg=DIM,
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
        def page(name, scrollable=False):
            outer = tk.Frame(content_host, bg=BG)
            pages[name] = outer
            if not scrollable:
                return outer
            canvas = tk.Canvas(outer, bg=BG, highlightthickness=0, bd=0)
            inner = tk.Frame(canvas, bg=BG)
            win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
            # Lock inner frame width to canvas width — prevents horizontal overflow.
            canvas.bind("<Configure>",
                lambda e: canvas.itemconfig(win_id, width=e.width))
            canvas.pack(fill="both", expand=True)
            def _on_mousewheel(e):
                canvas.yview_scroll(int(-1 * e.delta), "units")
            def _bind_scroll_recursive(widget):
                widget.bind("<MouseWheel>", _on_mousewheel)
                for child in widget.winfo_children():
                    _bind_scroll_recursive(child)
            canvas.bind("<MouseWheel>", _on_mousewheel)
            inner.bind("<Configure>", lambda e: (
                canvas.configure(scrollregion=canvas.bbox("all")),
                _bind_scroll_recursive(inner)
            ))
            return inner

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
            # Bottom action row. Keep a little bottom padding so macOS/Tk
            # cannot clip the save button on shorter displays or when the
            # title-bar/client-area height is calculated slightly differently.
            bar = tk.Frame(parent, bg=BG, height=68)
            bar.pack(fill="x", side="bottom", pady=(0, 10))
            bar.pack_propagate(False)
            tk.Frame(parent, bg=SEP, height=1).pack(fill="x", side="bottom")
            # Rounded pill save button
            R, btn_h = 7, ACTION_BUTTON_H
            btn_text = "Save changes"
            btn_w = PRIMARY_BUTTON_W

            holder = tk.Frame(bar, bg=BG)
            holder.pack(side="right", padx=(0, WINDOW_EDGE_PAD), pady=(10, 14))

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

        # ── Shared polish helpers ────────────────────────────────────────────
        def helper_text(parent, text):
            tk.Label(parent, text=text, bg=BG, fg=DIM,
                     font=(FONT, 10), justify="left", wraplength=430
            ).pack(anchor="w", padx=24, pady=(4, 8))

        def _rounded_card_canvas(parent, bg_col, radius, padx, pady):
            """Return an inner tk.Frame sitting inside a Canvas rounded-corner card.

            The canvas draws a filled rounded rectangle behind the inner frame.
            All content should be packed into the returned inner frame.
            """
            R = radius
            outer = tk.Frame(parent, bg=BG)
            outer.pack(fill="x", padx=padx, pady=pady)

            c = tk.Canvas(outer, bg=BG, highlightthickness=0, bd=0)
            c.pack(fill="x", expand=True)

            inner = tk.Frame(c, bg=bg_col)
            win_id = c.create_window(0, 0, window=inner, anchor="nw")

            def _redraw(event=None):
                w = c.winfo_width()
                if w <= 1:
                    c.after(20, _redraw)
                    return
                h = max(inner.winfo_reqheight(), 20)
                c.configure(height=h)
                c.itemconfig(win_id, width=w, height=h)
                c.delete("rr")
                fill = bg_col
                c.create_arc(0, 0, 2*R, 2*R,             start=90,  extent=90,  fill=fill, outline="", tags="rr")
                c.create_arc(w-2*R, 0, w, 2*R,           start=0,   extent=90,  fill=fill, outline="", tags="rr")
                c.create_arc(0, h-2*R, 2*R, h,           start=180, extent=90,  fill=fill, outline="", tags="rr")
                c.create_arc(w-2*R, h-2*R, w, h,         start=270, extent=90,  fill=fill, outline="", tags="rr")
                c.create_rectangle(R, 0, w-R, h,         fill=fill, outline="",  tags="rr")
                c.create_rectangle(0, R, w, h-R,         fill=fill, outline="",  tags="rr")
                c.tag_lower("rr")   # background behind the inner frame window

            inner.bind("<Configure>", _redraw)
            c.bind("<Configure>",     _redraw)
            return inner

        def section_note(parent, title, text):
            inner = _rounded_card_canvas(parent, "#191919", radius=12,
                                         padx=24, pady=(10, 8))
            tk.Label(inner, text=title, bg="#191919", fg=FG,
                     font=(FONT, 11, "bold"), anchor="w").pack(anchor="w", padx=12, pady=(10, 2))
            tk.Label(inner, text=text, bg="#191919", fg=DIM,
                     font=(FONT, 10), justify="left", wraplength=410
            ).pack(anchor="w", padx=12, pady=(0, 10))

        def small_button(parent, text, cmd, accent=False):
            btn = tk.Label(parent, text=text, bg=ACC if accent else CARD, fg="#ffffff" if accent else FG,
                           font=(FONT, 11, "bold"), padx=14, pady=8, cursor="hand2")
            btn.pack(anchor="w", padx=24, pady=(8, 4))
            btn.bind("<Button-1>", lambda e: cmd())
            btn.bind("<Enter>", lambda e: btn.configure(bg="#1a6fd4" if accent else CARD_HI))
            btn.bind("<Leave>", lambda e: btn.configure(bg=ACC if accent else CARD))
            return btn

        def info_card(parent, title, body):
            inner = _rounded_card_canvas(parent, CARD, radius=12,
                                         padx=24, pady=(8, 6))
            tk.Label(inner, text=title, bg=CARD, fg=FG,
                     font=(FONT, 12, "bold"), anchor="w").pack(anchor="w", padx=12, pady=(10, 3))
            tk.Label(inner, text=body, bg=CARD, fg=DIM,
                     font=(FONT, 10), justify="left", wraplength=410
            ).pack(anchor="w", padx=12, pady=(0, 10))
            return inner

        def copy_to_clipboard(text, message="Copied to clipboard"):
            try:
                _win.clipboard_clear()
                _win.clipboard_append(text)
                self.show_message(message, self.GREEN)
            except Exception:
                self.show_message("Could not copy text", self.ORANGE)

        def _safe_float(value, fallback):
            try:
                return float(value)
            except Exception:
                return fallback

        def reset_recommended_defaults():
            model_var.set("small.en")
            hotkey_var.set("Right Option")
            hud_var.set(True)
            toggle_var.set(True)
            wake_var.set(True)
            jarvis_var.set(True)
            format_var.set(True)
            auto_var.set(True)
            ollama_var.set(True)
            sounds_var.set(True)
            startup_tips_var.set(True)
            cloud_var.set(False)
            safe_mode_var.set(False)
            correction_strength_var.set("Standard")
            writing_profile_var.set("General")
            auto_profile_var.set(True)
            show_profile_var.set(True)
            wake_grace_var.set(str(WAKE_DICTATION_GRACE_SECONDS))
            wake_silence_var.set(str(WAKE_DICTATION_SILENCE_SECONDS))
            wake_max_var.set(str(WAKE_DICTATION_MAX_SECONDS))
            self.show_message("Recommended defaults selected. Click Save changes.", self.BLUE)

        def _selected_mic_index():
            if _dev_labels and mic_var.get() in _dev_labels:
                return _dev_indices[_dev_labels.index(mic_var.get())]
            return current_mic

        def mark_setup_complete():
            settings["first_run_complete"] = True
            settings["onboarding_shown_version"] = APP_VERSION
            save_settings(settings)
            self.show_message("Setup marked complete", self.GREEN)

        # ── Page: Setup ──────────────────────────────────────────────────────
        p = page("Setup")
        ph(p, "Professional Setup")
        section_note(p, "Recommended first-run path",
                     "Confirm the hotkey, keep local transcription on, choose the correct microphone if needed, and try one short dictation.")
        info_card(p, "1. Confirm your record key",
                  "Right Option with toggle mode is the stable Mac default. F13/F14/F15 are available as advanced alternatives for keyboards that support them.")
        info_card(p, "2. Confirm your microphone",
                  "Use the Audio page to choose the right input device if the default microphone is not working. Restart after changing microphone devices.")
        info_card(p, "3. Keep the simple defaults",
                  "Use small.en, local Whisper, Ollama cleanup, Jarvis enabled, and Cloud mode off unless you specifically need cloud transcription.")
        info_card(p, "4. Try a short dictation",
                  "Say one complete sentence, then stop recording. If the result is clean, your setup is ready.")
        small_button(p, "Mark setup complete", mark_setup_complete, accent=True)
        helper_text(p, "This setup page saves the completion step immediately. Use Save changes on the other pages after editing settings.")

        # ── Page: Dictation ──────────────────────────────────────────────────
        p = page("Dictation")
        ph(p, "Dictation")
        section_note(p, "Recommended setup",
                     "Right Option + toggle mode is the stable default. F13/F14/F15 are optional alternatives for keyboards that support them. Hotkey changes apply immediately after saving.")
        lbl(p, "RECORD HOTKEY")
        combo(p, hotkey_var, list(HOTKEY_OPTIONS.keys()))
        helper_text(p, "Recommended: Right Option. Advanced options: F13/F14/F15 only. Left/Right Command, Left Option, and Control variants are hidden because they were unreliable on some Mac keyboards.")
        toggle_row(p, toggle_var, "Toggle mode", "Press once to start recording, press again to stop")
        toggle_row(p, hud_var,    "Show HUD",    "Floating status bar while dictating")
        toggle_row(p, sounds_var, "Start / stop sounds", "Play a small sound when recording starts and stops")
        toggle_row(p, startup_tips_var, "Helpful HUD tips", "Show simple guidance instead of technical status whenever possible")
        small_button(p, "Reset to recommended defaults", reset_recommended_defaults)
        save_btn_row(p, lambda: _save())

        # ── Page: Audio ──────────────────────────────────────────────────────
        p = page("Audio")
        ph(p, "Audio")
        lbl(p, "MICROPHONE")
        if _dev_labels:
            combo(p, mic_var, _dev_labels, width=34)
        else:
            tk.Label(p, text=f"Device index: {current_mic}  (install sounddevice to list)",
                     bg=BG, fg=DIM, font=(FONT, 11)).pack(anchor="w", padx=24)
        helper_text(p, "Microphone changes are safest after restarting the app. The built-in mic test has been removed for stability.")

        lbl(p, "WHISPER MODEL")
        combo(p, model_var, ["tiny.en","base.en","small.en","medium.en","large-v2","large-v3","distil-medium.en","distil-large-v3"])
        helper_text(p, "Recommended: small.en. Larger models can be more accurate, but they load slower on Intel Macs.")
        lbl(p, "LANGUAGE")
        toggle_row(p, auto_var, "Auto-detect language", "Let Whisper identify the spoken language")
        section_note(p, "Restart recommended",
                     "Whisper model, microphone, and sample-rate style changes are most reliable after restarting.")
        save_btn_row(p, lambda: _save())

        # ── Page: AI Cleanup ─────────────────────────────────────────────────
        p = page("AI Cleanup", scrollable=True)
        ph(p, "Local AI Cleanup")

        # ── Status card ───────────────────────────────────────────────────────
        STATUS_COLORS = {
            "ready":         "#30d158",
            "not_installed": "#ff9f0a",
            "not_running":   "#ff9f0a",
            "model_missing": "#ff9f0a",
            "unknown":       "#6a6a6a",
        }
        STATUS_LABELS = {
            "ready":         "✓  Local AI Cleanup ready",
            "not_installed": "⚠  Ollama not installed",
            "not_running":   "⚠  Ollama installed but not running",
            "model_missing": "⚠  Recommended model not installed",
            "unknown":       "—  Status unknown",
        }
        STATUS_DETAIL = {
            "ready":
                f"Ollama is installed, running, and the recommended model ({OLLAMA_MODEL}) is available. "
                "Dictated text will be polished automatically.",
            "not_installed":
                "Ollama is not installed on this Mac. "
                "Dictation still works normally without it — you just won't get AI cleanup.",
            "not_running":
                "Ollama is installed but the server is not running. "
                "Start Ollama from your Applications folder, then click Check Again.",
            "model_missing":
                f"Ollama is running but the recommended model ({OLLAMA_MODEL}) is not downloaded yet. "
                "Click 'Install Recommended Model' below.",
            "unknown":
                "Status has not been checked yet. Click 'Check Again' to probe.",
        }

        status_frame = _rounded_card_canvas(p, CARD, radius=12, padx=24, pady=(4, 8))

        status_icon_lbl = tk.Label(status_frame, text="", bg=CARD,
                                   font=(FONT, 13, "bold"))
        status_icon_lbl.pack(anchor="w", padx=14, pady=(10, 2))

        status_detail_lbl = tk.Label(status_frame, text="", bg=CARD, fg=DIM,
                                     font=(FONT, 10), wraplength=420, justify="left")
        status_detail_lbl.pack(anchor="w", padx=14, pady=(0, 10))

        fallback_lbl = tk.Label(p, text="Dictation still works without Local AI Cleanup.",
                                bg=BG, fg=DIM, font=(FONT, 10, "italic"))
        fallback_lbl.pack(anchor="w", padx=24, pady=(0, 6))

        def _update_status_card(s: str):
            col = STATUS_COLORS.get(s, "#6a6a6a")
            status_icon_lbl.configure(text=STATUS_LABELS.get(s, s), fg=col)
            status_detail_lbl.configure(text=STATUS_DETAIL.get(s, ""))

        _update_status_card(_ollama_status_cache)

        # ── Action buttons ────────────────────────────────────────────────────
        # Layout: 3 rows, max 2 buttons per row.
        # Row 1: Check Again | Open Ollama Download Page  (220px each)
        # Row 2: Install Recommended Model  (full-width accent)
        # Row 3: Test Cleanup | Disable AI Cleanup  (220px each)
        # All rows are padded to 24px on each side to match the rest of the page.

        BTN_W  = 220   # standard button width — two fit comfortably in ~460px content
        BTN_WF = 460   # full-width button — Install Recommended Model

        def _make_action_btn(parent, label, cmd, width=BTN_W, accent=False):
            bg_col   = ACC if accent else CARD
            fg_col   = "#ffffff" if accent else FG
            hover_c  = "#1a6fd4" if accent else "#2e2e2e"
            c = tk.Canvas(parent, width=width, height=ACTION_BUTTON_H, bg=BG,
                          highlightthickness=0, cursor="hand2")
            def _draw(col):
                c.delete("all")
                r = 7
                c.create_arc(0, 0, 2*r, 2*r,             start=90,  extent=90, fill=col, outline=col)
                c.create_arc(width-2*r, 0, width, 2*r,   start=0,   extent=90, fill=col, outline=col)
                c.create_arc(0, ACTION_BUTTON_H-2*r, 2*r, ACTION_BUTTON_H, start=180, extent=90, fill=col, outline=col)
                c.create_arc(width-2*r, ACTION_BUTTON_H-2*r, width, ACTION_BUTTON_H, start=270, extent=90, fill=col, outline=col)
                c.create_rectangle(r, 0, width-r, ACTION_BUTTON_H, fill=col, outline=col)
                c.create_rectangle(0, r, width, ACTION_BUTTON_H-r, fill=col, outline=col)
                c.create_text(width//2, ACTION_BUTTON_H//2, text=label,
                              fill=fg_col, font=(FONT, 11))
            _draw(bg_col)
            c.bind("<Enter>",    lambda e: _draw(hover_c))
            c.bind("<Leave>",    lambda e: _draw(bg_col))
            c.bind("<Button-1>", lambda e: cmd())
            return c

        def _do_check_again():
            _update_status_card("unknown")
            p.after(80, lambda: _update_status_card(_refresh_ollama_status()))

        def _do_open_download():
            import subprocess as _sp
            _sp.Popen(["open", "https://ollama.com/download"])

        install_btn_ref = [None]

        def _do_install_model():
            """Pull qwen2.5:3b — only runs when user explicitly clicks the button."""
            import subprocess as _sp, threading as _th
            status_icon_lbl.configure(
                text=f"⏳  Downloading {OLLAMA_MODEL} — this may take a minute…",
                fg="#0a84ff")
            status_detail_lbl.configure(
                text="Do not close the app. The download runs in the background.")
            def _pull():
                try:
                    result = _sp.run(
                        ["ollama", "pull", OLLAMA_MODEL],
                        capture_output=True, text=True, timeout=600
                    )
                    if result.returncode == 0:
                        p.after(0, lambda: _update_status_card(_refresh_ollama_status()))
                        p.after(0, lambda: self.show_message(
                            f"{OLLAMA_MODEL} installed!", self.GREEN))
                    else:
                        p.after(0, lambda: status_icon_lbl.configure(
                            text="✗  Download failed — see terminal for details",
                            fg="#ff3b30"))
                        p.after(0, lambda: status_detail_lbl.configure(
                            text="Make sure Ollama is running, then try again."))
                except Exception as exc:
                    p.after(0, lambda: status_icon_lbl.configure(
                        text="✗  Download error: " + str(exc)[:50], fg="#ff3b30"))
            _th.Thread(target=_pull, daemon=True, name="ollama-pull").start()

        def _do_test_cleanup():
            """Run one sample phrase through the local model and show the result."""
            sample = "this is a test of the local ai cleanup feature its working great"
            status_icon_lbl.configure(text="⏳  Testing cleanup…", fg="#0a84ff")
            status_detail_lbl.configure(text='Input: "' + sample + '"')
            def _run():
                try:
                    import ollama as _ol
                    resp = _ol.chat(
                        model=OLLAMA_MODEL,
                        messages=[
                            {"role": "system", "content": _ollama_prompt_for_strength()},
                            {"role": "user",   "content": sample},
                        ],
                        options={"repeat_penalty": 1.15, "num_predict": 180,
                                 "temperature": 0.35, "top_P": 0.85},
                    )
                    out = resp["message"]["content"].strip()
                    p.after(0, lambda: status_icon_lbl.configure(
                        text="✓  Test passed", fg="#30d158"))
                    p.after(0, lambda o=out: status_detail_lbl.configure(
                        text='Output: "' + o + '"'))
                except Exception as exc:
                    p.after(0, lambda: status_icon_lbl.configure(
                        text="✗  Test failed", fg="#ff3b30"))
                    p.after(0, lambda: status_detail_lbl.configure(
                        text=str(exc)[:120]))
            import threading as _th
            _th.Thread(target=_run, daemon=True, name="ollama-test").start()

        def _do_disable():
            ollama_var.set(False)
            ai_cleanup_mode_var.set("off")
            self.show_message("Local AI Cleanup disabled", "#ff9f0a")

        # Row 1: Check Again | Open Ollama Download Page
        _r1 = tk.Frame(p, bg=BG)
        _r1.pack(fill="x", padx=24, pady=(0, 6))
        _make_action_btn(_r1, "Check Again",               _do_check_again).pack(side="left", padx=(0, 8))
        _make_action_btn(_r1, "Open Ollama Download Page",  _do_open_download).pack(side="left")

        # Row 2: Test Cleanup | Disable AI Cleanup
        _r2 = tk.Frame(p, bg=BG)
        _r2.pack(fill="x", padx=24, pady=(0, 6))
        _make_action_btn(_r2, "Test Cleanup",       _do_test_cleanup).pack(side="left", padx=(0, 8))
        _make_action_btn(_r2, "Disable AI Cleanup",  _do_disable).pack(side="left")

        # Row 3: Install Recommended Model — full-width accent button (last)
        _r3 = tk.Frame(p, bg=BG)
        _r3.pack(fill="x", padx=24, pady=(0, 6))
        ib = _make_action_btn(_r3, "Install Recommended Model", _do_install_model,
                              width=BTN_WF, accent=True)
        ib.pack(side="left")
        install_btn_ref[0] = ib

        tk.Frame(p, bg=SEP, height=1).pack(fill="x", padx=24, pady=(10, 8))

        # ── Mode selector ─────────────────────────────────────────────────────
        lbl(p, "LOCAL AI CLEANUP MODE")
        combo(p, ai_cleanup_mode_var,
              ["auto", "on", "off"], width=14)
        helper_text(p, (
            "auto — use Local AI Cleanup if available, skip silently if not (recommended).\n"
            "on   — always try to use it; show a warning in the HUD if unavailable.\n"
            "off  — never use Local AI Cleanup."
        ))

        # ── Correction strength + other toggles ──────────────────────────────
        lbl(p, "CORRECTION STRENGTH")
        combo(p, correction_strength_var, ["Light", "Standard", "Strong", "Off"], width=20)
        helper_text(p, "Recommended: Standard. Short phrases and unsafe AI rewrites are always protected.")
        toggle_row(p, safe_mode_var, "Safe Mode",
                   "Pure dictation: disables Local AI Cleanup, Jarvis commands, and cloud transcription")
        toggle_row(p, format_var, "Context-aware formatting",
                   "Adjusts tone based on the active app — Mail, Spark, Notes, Terminal, etc.")
        section_note(p, "How it works",
                     "Local AI Cleanup only polishes your dictated words. It never answers questions, "
                     "adds content, or changes your meaning. Unsafe rewrites are rejected automatically.")
        save_btn_row(p, lambda: _save())

        # ── Page: Writing Profiles ─────────────────────────────────────────────
        p = page("Writing Profiles")
        ph(p, "Writing Profiles")
        section_note(p, "Professional language modes",
                     "Profiles tune the cleanup prompt for different contexts without changing the working Ollama model, temperature, or sampling settings.")
        lbl(p, "DEFAULT PROFILE")
        combo(p, writing_profile_var, PROFILE_OPTIONS, width=24)
        helper_text(p, "Recommended: General. Use Verbatim for minimal cleanup, Developer for code/terminal work, and Email for polished messages.")
        toggle_row(p, auto_profile_var, "Auto-detect profile by app",
                   "Mail uses Email, Terminal and code editors use Developer, and Notes apps use Notes")
        toggle_row(p, show_profile_var, "Show active profile",
                   "Logs the selected profile during dictation and stores it in History")
        info_card(p, "How profiles work",
                  "The active profile guides Ollama's wording style only. The safety filter still rejects answers, expansions, and meaning changes.")
        info_card(p, "Public-friendly defaults",
                  "General users can leave this on Auto. Power users can choose Developer, Legal, Medical, Sales, Creative, Notes, Professional, Email, or Verbatim.")
        save_btn_row(p, lambda: _save())

        # ── Page: Jarvis ─────────────────────────────────────────────────────
        p = page("Jarvis")
        ph(p, "Jarvis")

        toggle_row(p, wake_var,   "Wake word",       "Say 'Hey Jarvis' to start recording")
        toggle_row(p, jarvis_var, "Jarvis commands", "Voice commands for apps, search, reminders, media, and screenshots")
        section_note(p, "Wake dictation length",
                     "Jarvis wake dictation is tuned for natural sentences. It waits longer before auto-stopping, so you can use Writing Profiles without being cut off.")
        lbl(p, "WAKE DICTATION TIMING")
        row = tk.Frame(p, bg=BG); row.pack(fill="x", padx=24, pady=(2, 8))
        for label, var, width in (("Grace", wake_grace_var, 6), ("Silence", wake_silence_var, 6), ("Max", wake_max_var, 6)):
            cell = tk.Frame(row, bg=BG); cell.pack(side="left", padx=(0, 14))
            tk.Label(cell, text=label + " sec", bg=BG, fg=DIM, font=(FONT, 10)).pack(anchor="w")
            ent = tk.Entry(cell, textvariable=var, width=width, bg=CARD, fg=FG, insertbackground=FG, relief="flat", highlightthickness=0)
            ent.pack(anchor="w", ipady=5)
        helper_text(p, "Recommended: Grace 3.5, Silence 4.5, Max 45. Increase Silence if Jarvis still stops too soon.")
        section_note(p, "Stability note",
                     "The wake word is paused while Settings is open, then restored when the window closes.")
        save_btn_row(p, lambda: _save())
        
        # ── Page: Custom Commands ────────────────────────────────────────────
        p = page("Custom Commands", scrollable=True)
        ph(p, "Custom Commands")
        tk.Label(p, text="Say your trigger phrase after 'Jarvis' to run the command.\nTrigger must be at least two words. Custom commands run before built-ins.\nChanges save automatically — no save button needed.",
                 bg=BG, fg=DIM, font=(FONT, 10), justify="left").pack(anchor="w", padx=24, pady=(0, 12))

        # ── Command list ──────────────────────────────────────────────────
        list_outer = tk.Frame(p, bg=BG)
        list_outer.pack(fill="x", padx=24)

        ACTION_LABELS = {"open_url": "URL", "open_app": "APP", "type_text": "TYPE"}
        ACTION_COLORS = {"open_url": "#0a84ff", "open_app": "#30d158", "type_text": "#ff9f0a"}

        def _refresh_list():
            for w in list_outer.winfo_children():
                w.destroy()
            cmds = load_custom_commands()
            if not cmds:
                tk.Label(list_outer, text="No custom commands yet. Add one below.",
                         bg=BG, fg=DIM, font=(FONT, 10)).pack(anchor="w", pady=(0, 8))
                return
            for i, cmd in enumerate(cmds):
                row = _rounded_card_canvas(list_outer, CARD, radius=8, padx=0, pady=(0, 4))

                # Action badge
                act = cmd.get("action", "open_url")
                badge_bg = ACTION_COLORS.get(act, ACC)
                badge_lbl = ACTION_LABELS.get(act, "?")
                tk.Label(row, text=badge_lbl, bg=badge_bg, fg="#ffffff",
                         font=(FONT, 9, "bold"), width=5).pack(side="left", ipady=8)

                # ✕ must be packed BEFORE the expanding info frame so Tkinter
                # reserves space for it on the right before fill="x" consumes the rest.
                def _delete(idx=i):
                    c = load_custom_commands()
                    c.pop(idx)
                    save_custom_commands(c)
                    _refresh_list()
                del_btn = tk.Label(row, text="✕", bg=CARD, fg=DIM,
                                   font=(FONT, 12), cursor="hand2", padx=12)
                del_btn.pack(side="right")
                del_btn.bind("<Button-1>", lambda e, d=_delete: d())
                del_btn.bind("<Enter>", lambda e, b=del_btn: b.configure(fg="#ff3b30"))
                del_btn.bind("<Leave>", lambda e, b=del_btn: b.configure(fg=DIM))

                # Trigger + target (packed after ✕ so expand stays within bounds)
                info = tk.Frame(row, bg=CARD)
                info.pack(side="left", fill="x", expand=True, padx=10, pady=6)
                tk.Label(info, text=f'"{cmd.get("trigger","")}"',
                         bg=CARD, fg=FG, font=(FONT, 11, "bold"),
                         anchor="w").pack(anchor="w")
                tk.Label(info, text=cmd.get("target", ""),
                         bg=CARD, fg=DIM, font=(FONT, 10),
                         anchor="w", wraplength=360, justify="left").pack(anchor="w")

        _refresh_list()

        # ── Add form ──────────────────────────────────────────────────────
        tk.Frame(p, bg=SEP, height=1).pack(fill="x", padx=24, pady=(14, 12))
        lbl(p, "ADD COMMAND")

        action_var = tk.StringVar(value="Open URL")
        action_map = {"Open URL": "open_url", "Open App": "open_app", "Type Text": "type_text"}

        def _field(parent, label_text):
            tk.Label(parent, text=label_text, bg=BG, fg=DIM,
                     font=(FONT, 9, "bold")).pack(anchor="w", padx=24, pady=(8, 2))
            f = _rounded_card_canvas(parent, CARD, radius=8, padx=24, pady=(0, 0))
            e = tk.Entry(f, bg=CARD, fg=FG, font=(FONT, 13), relief="flat",
                         insertbackground=FG, bd=0, highlightthickness=0)
            e.pack(fill="x", ipady=8, padx=10)
            _bind_copy_paste(e)
            return e

        trig_entry = _field(p, "TRIGGER PHRASE")
        trig_entry.insert(0, "e.g. open my website")
        trig_entry.configure(fg=DIM)
        def _trig_in(e):
            if trig_entry.get() == "e.g. open my website":
                trig_entry.delete(0, "end"); trig_entry.configure(fg=FG)
        def _trig_out(e):
            if not trig_entry.get().strip():
                trig_entry.insert(0, "e.g. open my website"); trig_entry.configure(fg=DIM)
        trig_entry.bind("<FocusIn>",  _trig_in)
        trig_entry.bind("<FocusOut>", _trig_out)

        # Action — row of three toggle-style buttons
        tk.Label(p, text="ACTION", bg=BG, fg=DIM,
                 font=(FONT, 9, "bold")).pack(anchor="w", padx=24, pady=(8, 2))
        act_row = tk.Frame(p, bg=BG)
        act_row.pack(anchor="w", padx=24)
        act_btns = {}
        def _select_action(chosen):
            action_var.set(chosen)
            for name, (btn, lbl_w) in act_btns.items():
                on = (name == chosen)
                btn.configure(bg=ACC if on else CARD)
                lbl_w.configure(bg=ACC if on else CARD,
                                fg="#fff" if on else DIM)
        for act_name in action_map:
            btn_f = tk.Frame(act_row, bg=CARD, highlightthickness=0, cursor="hand2")
            btn_f.pack(side="left", padx=(0, 6))
            btn_l = tk.Label(btn_f, text=act_name, bg=CARD, fg=DIM,
                             font=(FONT, 11), padx=14, cursor="hand2")
            btn_l.pack(ipady=6)
            act_btns[act_name] = (btn_f, btn_l)
            for w in (btn_f, btn_l):
                w.bind("<Button-1>", lambda e, n=act_name: _select_action(n))
        _select_action("Open URL")

        tgt_entry = _field(p, "TARGET  —  URL / app name / text to type")

        err_lbl = tk.Label(p, text="", bg=BG, fg="#ff3b30", font=(FONT, 10))
        err_lbl.pack(anchor="w", padx=24, pady=(6, 0))

        def _add_command():
            trigger = trig_entry.get().strip().lower()
            action  = action_map.get(action_var.get(), "open_url")
            target  = tgt_entry.get().strip()

            if not trigger or trigger == "e.g. open my website":
                err_lbl.configure(text="Trigger phrase is required."); return
            if len(trigger.split()) < 2:
                err_lbl.configure(text="Trigger must be at least two words."); return
            if not target:
                err_lbl.configure(text="Target is required."); return
            if action == "open_url" and not target.startswith(("http://", "https://", "spotify:", "music:", "mailto:")):
                target = "https://" + target

            cmds = load_custom_commands()
            if any(c.get("trigger", "").lower() == trigger for c in cmds):
                err_lbl.configure(text="A command with that trigger already exists."); return

            cmds.append({"trigger": trigger, "action": action, "target": target})
            save_custom_commands(cmds)
            err_lbl.configure(text="")
            trig_entry.delete(0, "end")
            trig_entry.insert(0, "e.g. open my website")
            trig_entry.configure(fg=DIM)
            tgt_entry.delete(0, "end")
            _select_action("Open URL")
            _refresh_list()

        add_btn = tk.Frame(p, bg=ACC, cursor="hand2")
        add_btn.pack(anchor="w", padx=24, pady=(10, 0))
        add_lbl = tk.Label(add_btn, text="  Add Command  ", bg=ACC, fg="#fff",
                           font=(FONT, 11, "bold"), cursor="hand2")
        add_lbl.pack(ipady=7)
        for w in (add_btn, add_lbl):
            w.bind("<Button-1>", lambda e: _add_command())
            w.bind("<Enter>", lambda e: add_btn.configure(bg="#1a94ff") or add_lbl.configure(bg="#1a94ff"))
            w.bind("<Leave>", lambda e: add_btn.configure(bg=ACC) or add_lbl.configure(bg=ACC))

        # ── Page: Vocabulary ─────────────────────────────────────────────────
        p = page("Vocabulary")
        ph(p, "Custom Vocabulary")
        lbl(p, "USER DICTIONARY")
        tk.Label(p, text="Type words or names you want Whisper to recognize better.\nSeparate them with commas or new lines.",
                 bg=BG, fg=DIM, font=(FONT, 10), justify="left").pack(anchor="w", padx=24, pady=(0, 10))

        # Save button gets its bottom space before the text box expands.
        save_btn_row(p, lambda: _save())

        v_frame = tk.Frame(p, bg=CARD, highlightthickness=0)
        v_frame.pack(fill="both", expand=True, padx=24, pady=10)

        v_scroll = tk.Scrollbar(v_frame, orient="vertical", bg=BG, troughcolor=BG,
                                 width=10, elementborderwidth=0, bd=0)
        v_scroll.pack(side="right", fill="y")

        v_box = tk.Text(v_frame, bg=CARD, fg=FG, font=(FONT, 13), relief="flat",
                        insertbackground=FG, bd=0, highlightthickness=0,
                        yscrollcommand=v_scroll.set)
        v_box.insert("1.0", settings.get("manual_vocabulary", ""))
        v_box.pack(fill="both", expand=True, padx=10, pady=10)
        _bind_copy_paste(v_box)
        v_scroll.configure(command=v_box.yview)
        
        def pause_on_any_key(event):
            # Guard for modifier-heavy typing inside the Settings text field on Intel Macs.
            globals()["WAKE_ENABLED"] = False
            
        v_box.bind("<KeyPress>", pause_on_any_key)
        v_box.bind("<Shift-KeyPress>", pause_on_any_key)
        
        # ── Page: Cloud ──────────────────────────────────────────────────────
        p = page("Cloud")
        ph(p, "Cloud transcription")
        toggle_row(p, cloud_var, "Cloud mode", "Use OpenAI Whisper API instead of the local model when an API key is available")
        lbl(p, "OPENAI API KEY")
        key_f = _rounded_card_canvas(p, CARD, radius=8, padx=24, pady=(4, 0))
        key_entry = tk.Entry(key_f, textvariable=key_var, show="•",
                             bg=CARD, fg=FG, font=(FONT, 13), relief="flat",
                             insertbackground=FG, bd=0, highlightthickness=0)
        key_entry.pack(fill="x", ipady=9, padx=10)
        _bind_copy_paste(key_entry)
        section_note(p, "Privacy",
                     "Local mode keeps transcription on your Mac. Cloud mode sends audio to OpenAI Whisper only when enabled and an API key is saved.")
        tk.Label(p, text="The API key is stored in macOS Keychain when possible.",
                 bg=BG, fg=DIM, font=(FONT, 10)).pack(anchor="w", padx=24, pady=(4,0))
        save_btn_row(p, lambda: _save())

        # ── Page: Help ───────────────────────────────────────────────────────
        p = page("Help", scrollable=True)
        ph(p, "Help & Quick Start")
        info_card(p, "Professional app checklist",
                  "Use the Setup page for first-run configuration, keep the recommended defaults for reliability, and copy the setup summary when debugging or sharing support details.")
        info_card(p, "Start dictating",
                  "Press Right Option once to start, then press it again to stop. Say 'Hey Jarvis' to start by voice; Jarvis will then wait for a natural pause instead of assuming a short command.")
        info_card(p, "What each status means",
                  "Gray means ready. Red means recording. Blue means transcribing or processing. Green means the text was inserted or a command completed.")
        info_card(p, "Best results",
                  "Speak in complete phrases, pause briefly before stopping, and keep the microphone close enough that the HUD does not report quiet audio.")
        info_card(p, "Ollama cleanup",
                  "Ollama only cleans up dictated text after Whisper transcribes it. It does not automatically correct normal manual typing.")
        info_card(p, "Writing Profiles",
                  "Profiles adjust cleanup style for everyday writing, email, professional writing, developer work, notes, sales, legal, medical, creative, or verbatim dictation.")
        info_card(p, "Safe troubleshooting",
                  "If recording feels stuck, release the hotkey, wait a second, then try again. If audio or model settings were changed, restart the app.")

        def copy_support_summary():
            summary = (
                f"Dictation app {APP_VERSION}\n"
                f"Hotkey: {hotkey_var.get()}\n"
                f"Whisper model: {model_var.get()}\n"
                f"Mic: {mic_var.get()}\n"
                f"Toggle mode: {toggle_var.get()}\n"
                f"Wake word: {wake_var.get()}\n"
                f"Jarvis: {jarvis_var.get()}\n"
                f"Ollama: {ollama_var.get()}\n"
                f"Cloud mode: {cloud_var.get()}\n"
                f"Safe Mode: {safe_mode_var.get()}\n"
                f"Correction strength: {correction_strength_var.get()}\n"
                f"Writing profile: {writing_profile_var.get()}\n"
                f"Auto profile detection: {auto_profile_var.get()}\n"
                f"Wake timing: grace={wake_grace_var.get()}s silence={wake_silence_var.get()}s max={wake_max_var.get()}s\n"
                f"First-run setup complete: {settings.get('first_run_complete', False)}\n"
            )
            copy_to_clipboard(summary, "Support summary copied")

        small_button(p, "Copy setup summary", copy_support_summary)

        # ── Save logic ────────────────────────────────────────────────────────
        def _save():
            # --- HARDWARE SAFETY GUARD ---
            # Temporarily disable wake word to prevent Intel CPU instruction conflicts
            global WAKE_ENABLED
            original_wake_state = WAKE_ENABLED
            globals()["WAKE_ENABLED"] = False 

            new_mic = current_mic
            if _dev_labels and mic_var.get() in _dev_labels:
                new_mic = _dev_indices[_dev_labels.index(mic_var.get())]
            
            raw_key = key_var.get().strip()
            if raw_key:
                set_openai_key(raw_key)

            settings["manual_vocabulary"] = v_box.get("1.0", "end-1c").strip()    
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
                "play_sounds":    sounds_var.get(),
                "show_startup_tips": startup_tips_var.get(),
                "safe_mode":        safe_mode_var.get(),
                "ai_cleanup_mode":  ai_cleanup_mode_var.get(),
                "correction_strength": correction_strength_var.get(),
                "writing_profile": writing_profile_var.get() if writing_profile_var.get() in WRITING_PROFILES else "General",
                "auto_profile_detection": auto_profile_var.get(),
                "show_active_profile": show_profile_var.get(),
                "wake_dictation_grace_seconds": max(1.0, min(10.0, _safe_float(wake_grace_var.get(), WAKE_DICTATION_GRACE_SECONDS))),
                "wake_dictation_silence_seconds": max(1.0, min(12.0, _safe_float(wake_silence_var.get(), WAKE_DICTATION_SILENCE_SECONDS))),
                "wake_dictation_max_seconds": max(10.0, min(120.0, _safe_float(wake_max_var.get(), WAKE_DICTATION_MAX_SECONDS))),
                "wake_dictation_silence_rms": WAKE_DICTATION_SILENCE_RMS,
            })

            # Sync the global flags
            globals().update({
                "WAKE_ENABLED":   wake_var.get(), 
                "JARVIS_ENABLED": jarvis_var.get(), 
                "OLLAMA_ENABLED": ollama_var.get() and not safe_mode_var.get()
            })
            
            save_settings(settings)
            _refresh_record_hotkey(log=True)
            _win.destroy()
            self.show_message("Saved! Hotkey changes apply now.", self.GREEN)

        # Ensure every editable field in Settings supports Cmd+C/V/X/A and
        # right-click / Ctrl-click context menus, including fields added later.
        _bind_copy_paste_recursive(_win)

        # Show first page
        show_page("Setup" if not settings.get("first_run_complete", False) else "Dictation")
        
# --- ST# --- IRONCLAD STABILITY: Hardware Cleanup ---
        def on_settings_destroy(event):
            if event.widget == _win:
                print("[system] Settings closed.")
                # Restore WAKE_ENABLED from persisted settings so Jarvis resumes
                # whether the user saved or just closed the window.
                globals()["WAKE_ENABLED"] = settings.get("wake_enabled", True)
                print(f"[system] WAKE_ENABLED restored to {globals()['WAKE_ENABLED']}")
                _toplevel_closed()

        _win.bind("<Destroy>", on_settings_destroy)        

    def show_first_run_welcome(self):
        """Small first-run welcome window for a more professional setup flow."""
        if settings.get("first_run_complete", False):
            return
        BG = "#141414"
        CARD = "#222222"
        SEP = "#2e2e2e"
        ACC = "#0a84ff"
        FG = "#f0f0f0"
        DIM = "#8a8a8a"
        FONT = "Helvetica Neue"
        globals()["_suppress_caps_lock"] = True
        win = tk.Toplevel(self.root)
        win.title("Welcome")
        win.configure(bg=BG)
        win.attributes("-topmost", True)
        win.resizable(False, False)
        W, H = 460, 360
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{W}x{H}+{sw//2 - W//2}+{sh//2 - H//2}")

        tk.Label(win, text="Welcome to Dictation", bg=BG, fg=FG,
                 font=(FONT, 21, "bold")).pack(anchor="w", padx=28, pady=(28, 6))
        tk.Label(win, text="Let's do a quick setup so recording feels reliable from the first use.",
                 bg=BG, fg=DIM, font=(FONT, 12), wraplength=390, justify="left").pack(anchor="w", padx=28, pady=(0, 18))

        card = tk.Frame(win, bg=CARD, highlightthickness=0)
        card.pack(fill="x", padx=28, pady=(0, 16))
        for txt in (
            "1. Confirm Right Option as the record key",
            "2. Select the correct microphone if needed",
            "3. Keep local Whisper + Ollama cleanup enabled",
            "4. Try one short dictation"
        ):
            tk.Label(card, text=txt, bg=CARD, fg=FG, font=(FONT, 12),
                     anchor="w").pack(anchor="w", padx=14, pady=6)

        def _button(parent, text, cmd, accent=False):
            btn = tk.Label(parent, text=text, bg=ACC if accent else CARD, fg="#ffffff" if accent else FG,
                           font=(FONT, 12, "bold"), padx=16, pady=10, cursor="hand2")
            btn.pack(side="right", padx=(8, 0))
            btn.bind("<Button-1>", lambda e: cmd())
            return btn

        row = tk.Frame(win, bg=BG)
        row.pack(fill="x", padx=28, pady=(4, 0))

        def _open_setup():
            settings["onboarding_shown_version"] = APP_VERSION
            save_settings(settings)
            win.destroy()
            self.open_settings()

        def _skip():
            settings["onboarding_shown_version"] = APP_VERSION
            save_settings(settings)
            win.destroy()
            self.show_message("Setup is available from Settings", self.BLUE)

        _button(row, "Open setup", _open_setup, accent=True)
        _button(row, "Later", _skip, accent=False)
        win.bind("<Escape>", lambda e: _skip())
        win.protocol("WM_DELETE_WINDOW", _skip)

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
    log_event("boot", f"Dictation v{APP_VERSION} — WAKE_ENABLED={WAKE_ENABLED} JARVIS_ENABLED={JARVIS_ENABLED}")
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
    if not settings.get("first_run_complete", False) and settings.get("onboarding_shown_version", "") != APP_VERSION:
        app.root.after(1200, app.show_first_run_welcome)
    # Start the audio stream FIRST so PortAudio's Core Audio thread is fully
    # initialised before any Python thread calls time.sleep() or any other
    # GIL-releasing function.  Starting the stream after the wake-word thread
    # caused PortAudio's C-level thread init to corrupt the wake-word thread's
    # PyThreadState, producing the fatal GIL abort on time.sleep().
    stream.start()
    # Key detection is now handled entirely by the Quartz HID tap installed via
    # root.after(1000, _install_suppression_tap).  No pynput keyboard.Listener
    # thread is started here — eliminating the concurrent-SIMD SIGILL entirely.
    threading.Thread(target=_wake_word_loop, daemon=True).start()
    # Wait until _quit_clean() signals shutdown.  Using the named
    # _shutdown_event (rather than a fresh anonymous Event) lets the
    # main thread unblock this daemon thread cleanly, which allows
    # Python's resource_tracker to reclaim semaphores before exit.
    _shutdown_event.wait()

# ── Quartz-tap key handlers (replace pynput callbacks) ───────────────────────
# These run on the main thread (scheduled via root.after from the HID tap),
# so there is NO background thread and NO concurrent-SIMD / SIGILL risk.

def _tap_record_start():
    global recording, cancelled, _record_started_at, _last_record_press_at, _recording_started_by_wake
    now = time.time()
    debounce = _setting_float("hotkey_debounce_seconds", HOTKEY_DEBOUNCE_SECONDS)

    if now - _last_record_press_at < debounce:
        log_event("input", "ignored duplicate record press")
        return
    _last_record_press_at = now

    if recording:
        log_event("record", "start ignored — already recording")
        return
    if _transcription_busy:
        log_event("record", "start ignored — transcription still running")
        if app:
            app.show_message("Finishing previous dictation...", "#ff9f0a")
        return

    recording = True
    _recording_started_by_wake = False
    _record_started_at = now
    _wake_active.set()
    globals()["_wake_cooldown_until"] = now + 2.0
    cancelled = False
    globals()["_recording_had_audio"] = False
    with _audio_lock:
        audio_frames.clear()
    with wake_lock:
        wake_frames.clear()

    if app:
        app.set_state("recording")
        app.root.after(0, app.start_wave)

    def _side_effects():
        play_sound("start")
        pause_media()
        if app:
            app.capture_active_app()

    threading.Thread(target=_side_effects, daemon=True).start()
    log_event("record", f"start via {settings.get('hotkey_label', 'Right Option')}")


def _finish_short_recording(duration: float):
    """Cleanly end an accidental tap without sending empty audio to Whisper."""
    global recording, _wake_cooldown_until, _recording_started_by_wake
    recording = False
    _recording_started_by_wake = False
    _wake_active.clear()
    _wake_cooldown_until = time.time() + 1.0
    with _audio_lock:
        audio_frames.clear()
    if app:
        app.root.after(0, app.stop_wave)
        app.show_message("Tap ignored — hold a little longer", "#ff9f0a")
    threading.Thread(target=resume_media, daemon=True).start()
    log_event("record", f"ignored short tap ({duration:.2f}s)")


def _tap_record_stop():
    global recording, _wake_cooldown_until, _last_record_release_at, _recording_started_by_wake
    now = time.time()
    debounce = _setting_float("hotkey_debounce_seconds", HOTKEY_DEBOUNCE_SECONDS)

    if now - _last_record_release_at < debounce:
        log_event("input", "ignored duplicate record release")
        return
    _last_record_release_at = now

    if not recording:
        log_event("record", "stop ignored — not recording")
        return

    was_wake_recording = bool(_recording_started_by_wake)
    duration = max(0.0, now - (_record_started_at or now))
    min_seconds = _setting_float("min_record_seconds", MIN_RECORD_SECONDS)
    # The short-tap guard is only for physical record-key taps. Wake-word
    # sessions stop by silence/max-duration and should never display
    # "Tap ignored" after Jarvis captured speech.
    if (not was_wake_recording) and duration < min_seconds:
        _finish_short_recording(duration)
        return

    recording = False
    _recording_started_by_wake = False
    _wake_active.clear()
    _wake_cooldown_until = now + 2.0
    if app:
        app.root.after(0, app.stop_wave)
        app.set_state("transcribing")
    with _audio_lock:
        frames = list(audio_frames)
    source = "wake" if was_wake_recording else "record"
    log_event(source, f"stop — {duration:.2f}s captured, {len(frames)} chunks")

    def _stop_and_process():
        resume_media()
        play_sound("stop")
        if frames:
            _process(frames)
        elif app:
            app.set_state("idle")

    threading.Thread(target=_stop_and_process, daemon=True).start()


def _tap_record_toggle_stop():
    # Toggle mode uses the same stop path so debounce, minimum duration, media
    # resume, and transcription locking stay consistent.
    _tap_record_stop()


def _tap_cancel():
    global recording, cancelled, _recording_started_by_wake
    if not recording:
        return
    recording = False
    _recording_started_by_wake = False
    cancelled = True
    _wake_active.clear()
    with _audio_lock:
        audio_frames.clear()
    if app:
        app.root.after(0, app.stop_wave)
        app.show_message("Cancelled", "#ff9f0a")
    threading.Thread(target=resume_media, daemon=True).start()
    if app:
        app.root.after(1500, lambda: app.set_state("idle"))
    log_event("record", "cancelled")


def _queue_input_event(name: str):
    """Queue UI/input work for Tk's main loop.

    Called from Quartz HID callbacks and PyObjC menu callbacks.  It must stay
    tiny: no Tkinter, no subprocess, no audio, no Whisper, no settings writes.
    """
    try:
        _input_event_q.put_nowait(name)
    except Exception:
        pass


def _drain_input_events():
    """Run keyboard actions from Tk's own event loop.

    This is the critical stability boundary: Quartz may observe/suppress keys,
    but every action that touches Tk, AppKit, subprocess, audio state, or worker
    threads is executed here from the Tk main loop.
    """
    try:
        while True:
            try:
                action = _input_event_q.get_nowait()
            except _queue.Empty:
                break

            if not app or not getattr(app, "root", None):
                continue

            # Ignore global hotkeys while settings/snippets/history windows are
            # open. Caps Lock suppression is still handled inside the tap.
            if _open_wins > 0 and action in {"record_press", "record_release", "cancel", "scratch_last"}:
                log_event("input", f"ignored {action} while a settings window is open")
                continue

            if action == "record_press":
                if not recording:
                    _tap_record_start()
                elif settings.get("toggle_mode", False):
                    _tap_record_toggle_stop()
            elif action == "record_release":
                if recording and not settings.get("toggle_mode", False):
                    _tap_record_stop()
            elif action == "cancel":
                _tap_cancel()
            elif action == "wake_auto_stop":
                if recording and _recording_started_by_wake:
                    _tap_record_stop()
            elif action == "scratch_last":
                _scratch_last(1)
            elif action == "open_settings":
                app.open_settings()
            elif action == "menu_start_stop":
                if recording:
                    _tap_record_stop() if settings.get("toggle_mode", False) else _tap_record_stop()
                else:
                    _tap_record_start()
            elif action == "menu_toggle_hud":
                settings["show_hud"] = not settings.get("show_hud", True)
                save_settings(settings)
                if settings["show_hud"]:
                    app.root.deiconify()
                else:
                    app.root.withdraw()
                if menubar: menubar._refresh_menu_state()
            elif action == "menu_toggle_safe_mode":
                settings["safe_mode"] = not settings.get("safe_mode", False)
                globals()["OLLAMA_ENABLED"] = settings.get("use_ollama", True) and not settings["safe_mode"]
                save_settings(settings)
                if menubar: menubar._refresh_menu_state()
                app.show_message("Safe Mode " + ("On" if settings["safe_mode"] else "Off"), "#0a84ff")
            elif action == "menu_toggle_wake":
                settings["wake_enabled"] = not settings.get("wake_enabled", True)
                globals()["WAKE_ENABLED"] = settings["wake_enabled"]
                save_settings(settings)
                if menubar: menubar._refresh_menu_state()
                app.show_message("Wake word " + ("On" if settings["wake_enabled"] else "Off"), "#0a84ff")
            elif action == "menu_toggle_jarvis":
                settings["jarvis_enabled"] = not settings.get("jarvis_enabled", True)
                globals()["JARVIS_ENABLED"] = settings["jarvis_enabled"]
                save_settings(settings)
                if menubar: menubar._refresh_menu_state()
                app.show_message("Jarvis commands " + ("On" if settings["jarvis_enabled"] else "Off"), "#0a84ff")
            elif action == "menu_toggle_launch_at_login":
                new_val = not _launch_at_login_enabled()
                ok = _set_launch_at_login(new_val)
                if menubar: menubar._refresh_menu_state()
                app.show_message(("Launch at login " + ("enabled" if new_val else "disabled")) if ok else "Could not update Login Items", "#30d158" if ok else "#ff9f0a")
            elif action == "menu_show_snippets":
                app._show_snippets()
            elif action == "menu_show_history":
                _show_history()
            elif action == "menu_show_about":
                _show_about_window()
            elif action == "menu_open_permissions":
                _open_system_permissions()
            elif action.startswith("menu_select_model::"):
                new_model = action.split("::", 1)[1]
                if new_model and new_model != settings.get("model"):
                    settings["model"] = new_model
                    save_settings(settings)
                    if menubar: menubar._refresh_menu_state()
                    app.show_message("Loading " + new_model + "...", "#0a84ff")
                    threading.Thread(target=reload_model, daemon=True).start()
            elif action.startswith("menu_select_hotkey::"):
                new_key = action.split("::", 1)[1]
                if new_key:
                    settings["hotkey_label"] = new_key
                    save_settings(settings)
                    _refresh_record_hotkey(log=True)
                    if menubar: menubar._refresh_menu_state()
                    app.show_message("Record key: " + new_key, "#0a84ff")
            elif action.startswith("menu_select_strength::"):
                strength = action.split("::", 1)[1]
                if strength:
                    settings["correction_strength"] = strength
                    save_settings(settings)
                    if menubar: menubar._refresh_menu_state()
                    app.show_message("Correction: " + strength, "#0a84ff")
            elif action.startswith("menu_select_profile::"):
                profile = action.split("::", 1)[1]
                if profile in WRITING_PROFILES:
                    settings["writing_profile"] = profile
                    save_settings(settings)
                    if menubar: menubar._refresh_menu_state()
                    app.show_message("Profile: " + profile, "#0a84ff")
            elif action == "menu_quit":
                _quit_clean()
    finally:
        # Keep polling lightweight.  10 ms feels instant for a hotkey but keeps
        # Quartz and Tk fully decoupled.
        if app and getattr(app, "root", None):
            app.root.after(10, _drain_input_events)


def _install_suppression_tap():
    """Install one Quartz HID event tap for global input.

    The tap does only two jobs:
      1. Suppress Caps Lock while a Tk Toplevel is open, preventing the original
         Caps Lock/Tk/Cocoa crash.
      2. Convert global keyboard activity into small queue messages.

    It intentionally does NOT call app.root.after(), app methods, subprocess,
    Whisper, audio, or worker-thread code.  Those actions are performed by
    _drain_input_events() on Tk's main loop.
    """
    global _suppress_keycode
    try:
        import Quartz

        _DISABLED_TIMEOUT = Quartz.kCGEventTapDisabledByTimeout
        _DISABLED_USER    = Quartz.kCGEventTapDisabledByUserInput
        _CTRL_MASK        = Quartz.kCGEventFlagMaskControl
        _RIGHT_OPTION_MASK = Quartz.kCGEventFlagMaskAlternate
        _MODIFIER_FLAG_MASKS = {
            RIGHT_OPTION_KEYCODE: _RIGHT_OPTION_MASK,  # Right Option
        }

        _refresh_record_hotkey(log=True)

        KEY_MASK = (
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)      |
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)        |
            Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged)
        )

        tap_holder = [None]

        def _cb(proxy, event_type, event, refcon):
            if event_type in (_DISABLED_TIMEOUT, _DISABLED_USER):
                if tap_holder[0] is not None:
                    Quartz.CGEventTapEnable(tap_holder[0], True)
                return event

            try:
                keycode = Quartz.CGEventGetIntegerValueField(event, 9)

                if event_type == Quartz.kCGEventFlagsChanged:
                    # Caps Lock is the only key we actually suppress.  When a
                    # Toplevel is open, dropping this event keeps it away from
                    # Tk/Cocoa and preserves the prior Caps Lock fix.
                    if keycode == 57:
                        return None if _suppress_caps_lock else event

                    # Option / Control / Command record keys are
                    # modifier keys. They arrive as flagsChanged events, not
                    # keyDown/keyUp. The selected hotkey is read dynamically so
                    # Settings changes apply without restarting the app.
                    # Right Option is always accepted as a recovery/default hotkey.
                    # This prevents a stale or unsupported saved setting from making
                    # all record keys appear dead. Other hotkeys are handled only when
                    # explicitly selected and supported.
                    is_selected_modifier = _record_key_is_modifier and keycode == _record_keycode
                    is_right_option_fallback = keycode == RIGHT_OPTION_KEYCODE
                    if is_selected_modifier or is_right_option_fallback:
                        if _open_wins > 0:
                            _modifier_keys_down.discard(keycode)
                            return event

                        flags = Quartz.CGEventGetFlags(event)
                        mask = _MODIFIER_FLAG_MASKS.get(keycode, _RIGHT_OPTION_MASK if keycode == RIGHT_OPTION_KEYCODE else 0)
                        is_down = bool(flags & mask) if mask else (keycode not in _modifier_keys_down)

                        # Do not blindly alternate press/release on every flagsChanged event.
                        if is_down and keycode not in _modifier_keys_down:
                            _modifier_keys_down.add(keycode)
                            _queue_input_event("record_press")
                        elif (not is_down) and keycode in _modifier_keys_down:
                            _modifier_keys_down.discard(keycode)
                            _queue_input_event("record_release")

                elif event_type == Quartz.kCGEventKeyDown:
                    if keycode not in _pressed_keys:
                        _pressed_keys.add(keycode)
                        flags = Quartz.CGEventGetFlags(event)
                        ctrl = bool(flags & _CTRL_MASK)

                        # F13/F14/F15 are normal keys, not modifiers, so they
                        # must start recording from keyDown.
                        if (not _record_key_is_modifier) and keycode == _record_keycode:
                            if _open_wins <= 0:
                                _queue_input_event("record_press")
                        elif keycode == 53:            # ESC
                            _queue_input_event("cancel")
                        elif ctrl and keycode == 6:  # Ctrl+Z
                            _queue_input_event("scratch_last")
                        elif ctrl and keycode == 43: # Ctrl+Comma
                            _queue_input_event("open_settings")

                elif event_type == Quartz.kCGEventKeyUp:
                    _pressed_keys.discard(keycode)
                    # F13/F14/F15 stop recording from keyUp when toggle mode is
                    # off. In toggle mode this release is ignored downstream.
                    if (not _record_key_is_modifier) and keycode == _record_keycode and _open_wins <= 0:
                        _queue_input_event("record_release")

            except Exception as e:
                # Never let a callback exception escape into CoreGraphics.
                try:
                    print(f"[input] tap callback ignored error: {e}")
                except Exception:
                    pass
            return event

        # First attempt: active tap (kCGHIDEventTap + kCGEventTapOptionDefault).
        # This can suppress Caps Lock and requires Accessibility permission.
        # On macOS 15+ the TCC grant is tied to the binary hash; after a fresh
        # PyInstaller build the hash changes and the grant may not match even if
        # the user just re-added the app in System Settings.
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGHIDEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,
            KEY_MASK,
            _cb,
            None,
        )
        tap_mode = "active"

        if not tap:
            # Fallback: listen-only tap (kCGAnnotatedSessionEventTap +
            # kCGEventTapOptionListenOnly).  Only needs Input Monitoring, not
            # Accessibility.  Cannot suppress Caps Lock, but detects all key and
            # modifier events — sufficient for recording start/stop hotkeys.
            tap = Quartz.CGEventTapCreate(
                Quartz.kCGAnnotatedSessionEventTap,
                Quartz.kCGHeadInsertEventTap,
                Quartz.kCGEventTapOptionListenOnly,
                KEY_MASK,
                _cb,
                None,
            )
            tap_mode = "listen-only"

        if tap:
            tap_holder[0] = tap
            src = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
            Quartz.CFRunLoopAddSource(
                Quartz.CFRunLoopGetCurrent(), src, Quartz.kCFRunLoopCommonModes
            )
            Quartz.CGEventTapEnable(tap, True)
            log_event("input", f"HID key-detection tap active ({tap_mode})")
        else:
            log_event("input", "HID tap failed — keyboard shortcuts unavailable")

    except Exception as e:
        log_event("input", f"Quartz tap error: {e}")

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
    root.after(600, _drain_input_events)
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