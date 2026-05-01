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

import tkinter as tk
from tkinter import ttk

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

# ── Config ────────────────────────────────────────────────────────────────────
MODEL       = settings["model"]
DEVICE      = "cpu"
COMPUTE     = "int8"
SAMPLE_RATE = 48000
CHANNELS    = 1
MIC_DEVICE  = 2

# ── Globals ───────────────────────────────────────────────────────────────────
recording    = False
audio_frames = []
last_text    = ""
typer        = Controller()
whisper      = None
app             = None
current_keys    = set()
cancelled       = False
snippet_state   = None  # None | 'waiting_trigger' | 'waiting_content'
snippet_trigger = ""

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
    except Exception:
        pass

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
        icon = ws.iconForFile_(app.bundleURL().path())
        icon.setSize_((48, 48))
        data = bytes(icon.TIFFRepresentation())
        img  = Image.open(io.BytesIO(data)).convert("RGBA")
        # Crop transparent padding so all icons fill the same space
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
        img = img.resize((32, 32), Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None

# ── Audio ─────────────────────────────────────────────────────────────────────
def play_sound(name):
    sounds = {
        "start": "/System/Library/Sounds/Tink.aiff",
        "stop":  "/System/Library/Sounds/Pop.aiff",
    }
    subprocess.Popen(["afplay", sounds[name]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def get_current_rms():
    if not audio_frames:
        return 0.0
    return float(np.sqrt(np.mean(audio_frames[-1]**2)))

def audio_callback(indata, frames, time_info, status):
    if recording:
        audio_frames.append(indata.copy())

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
    try:
        # Save existing clipboard
        prev = subprocess.check_output(
            ["osascript", "-e", "the clipboard as text"], timeout=2
        ).decode().strip()
    except Exception:
        prev = None
    try:
        clean = text.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(
            ["osascript", "-e", f'set the clipboard to "{clean}"'],
            timeout=2
        )
        time.sleep(0.1)
        typer.press(Key.cmd)
        typer.press("v")
        typer.release("v")
        typer.release(Key.cmd)
        time.sleep(0.15)
    except Exception as e:
        print(f"[paste] error: {e}")
        typer.type(text + " ")
        return
    finally:
        # Restore previous clipboard
        if prev is not None:
            try:
                prev_clean = prev.replace("\\", "\\\\").replace('"', '\\"')
                subprocess.run(
                    ["osascript", "-e", f'set the clipboard to "{prev_clean}"'],
                    timeout=2
                )
            except Exception:
                pass

def transcribe_and_type(wav_path, raw_frames):
    global last_text, cancelled, snippet_state, snippet_trigger

    if cancelled:
        cancelled = False
        app.set_state("idle")
        return

    audio = np.concatenate(raw_frames, axis=0)
    rms = np.sqrt(np.mean(audio**2))
    if rms < 0.005:
        app.set_state("idle")
        return

    app.set_state("transcribing")
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
    if lower in ("scratch that", "undo that", "delete that"):
        _scratch_last()
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

    text = symspell_correct(raw_text)
    text = words_to_digits(text)
    text = apply_snippets(text)

    active_app = get_active_app_name()
    threading.Thread(target=save_history, args=(text, active_app), daemon=True).start()

    last_text = text
    app.set_transcript(text)
    time.sleep(0.3)
    paste_text(text)
    time.sleep(3.0)
    app.set_state("idle")

def _scratch_last():
    global last_text
    if last_text:
        count = len(last_text) + 1
        for _ in range(count):
            typer.press(Key.backspace)
            typer.release(Key.backspace)
        last_text = ""
        app.show_message("Scratched!", "#ff9f0a")
    else:
        app.show_message("Nothing to scratch", "#ff9f0a")

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
        audio_frames = []
        cancelled    = False
        app.capture_active_app()
        app.set_state("recording")
        app.root.after(0, app.start_wave)
        threading.Thread(target=play_sound, args=("start",), daemon=True).start()
    elif key == record_key and recording and settings.get("toggle_mode", False):
        recording = False
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
        app.show_message("Cancelled", "#ff9f0a")
        threading.Timer(1.5, lambda: app.set_state("idle")).start()
    elif ctrl and is_z:
        threading.Thread(target=_scratch_last, daemon=True).start()
    elif ctrl and is_comma:
        app.open_settings()

def on_release(key):
    global recording
    current_keys.discard(key)
    if key == get_record_key() and recording and not settings.get("toggle_mode", False):
        recording = False
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
    ICON_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))

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

                def selectModel_(self, sender):
                    new_model = sender.title()
                    if new_model == settings.get("model"):
                        return
                    settings["model"] = new_model
                    save_settings(settings)
                    threading.Thread(target=reload_model, daemon=True).start()

                def selectHotkey_(self, sender):
                    settings["hotkey_label"] = sender.title()
                    save_settings(settings)

                def quitApp_(self, sender):
                    os._exit(0)

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
            for m in ["tiny.en", "base.en", "small.en", "medium.en"]:
                mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(m, "selectModel:", "")
                mi.setTarget_(self._delegate)
                if m == settings.get("model"):
                    mi.setState_(1)
                model_menu.addItem_(mi)
            model_item.setSubmenu_(model_menu)
            self._menu.addItem_(model_item)

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
        # Use emoji in bundled app, PNG when running from source
        if not getattr(sys, '_MEIPASS', None):
            path = os.path.join(self.ICON_DIR, f"icon_{state}.png")
            if os.path.exists(path):
                img = self._NSImage.alloc().initWithContentsOfFile_(path)
                img.setSize_((18, 18))
                img.setTemplate_(True)
                self._item.button().setImage_(img)
                self._item.button().setTitle_("")
                return
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
        self.root.configure(bg="systemTransparent")
        self.root.resizable(False, False)

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
                                bg="systemTransparent", highlightthickness=0)
        self.canvas.pack()
        self._pill(0, 0, W, H, 8, fill=self.PILL, outline="")
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
            icon = get_active_app_icon()
            def _update():
                if icon:
                    self._app_icon = icon
                    self.canvas.itemconfig(self.appicon, image=icon)
                    self.canvas.itemconfig(self.appname, text="")
                else:
                    name = get_active_app_name()
                    self.canvas.itemconfig(self.appicon, image="")
                    self.canvas.itemconfig(self.appname, text=name)
            self.root.after(0, _update)
        threading.Thread(target=_fetch, daemon=True).start()

    def set_state(self, state):
        self.root.after(0, self._apply_state, state)
        if menubar:
            menubar.set_state(state)

    def _apply_state(self, state):
        if self._blink_job:
            self.root.after_cancel(self._blink_job)
            self._blink_job = None
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
        self._wave_job = self.root.after(30, self._animate_wave)

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
        self._wave_job = self.root.after(30, self._animate_wave)

    def stop_wave(self):
        if hasattr(self, '_wave_job') and self._wave_job:
            self.root.after_cancel(self._wave_job)
            self._wave_job = None
        if hasattr(self, '_bars'):
            for bar in self._bars:
                self.canvas.delete(bar)
            self._bars = []
        self.canvas.itemconfig(self.dot, state="normal")

    def _show_snippets(self, parent=None):
        swin = tk.Toplevel(self.root)
        swin.title("Manage Snippets")
        swin.geometry("520x480")
        swin.configure(bg="#1a1a1a")
        swin.attributes("-topmost", True)

        tk.Label(swin, text="Snippets", bg=self.BG, fg=self.TEXT_WHITE,
                 font=("Helvetica Neue", 14, "bold")).pack(pady=(12,4))
        tk.Label(swin, text="Say the trigger word while dictating to expand",
                 bg=self.BG, fg=self.TEXT_DIM,
                 font=("Helvetica Neue", 10)).pack()

        # Scrollable list
        frame = tk.Frame(swin, bg="#1a1a1a")
        frame.pack(fill="both", expand=True, padx=16, pady=8)

        canvas = tk.Canvas(frame, bg="#1a1a1a", highlightthickness=0)
        scroll = tk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        inner  = tk.Frame(canvas, bg="#1a1a1a")

        inner.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        snippets = load_snippets()
        entries  = {}

        def refresh():
            for w in inner.winfo_children():
                w.destroy()
            entries.clear()
            snips = load_snippets()
            for trigger, content in snips.items():
                row = tk.Frame(inner, bg=self.BG)
                row.pack(fill="x", pady=3)
                tk.Label(row, text=trigger, bg="#2a2a2a", fg=self.BLUE,
                         font=("Helvetica Neue", 11, "bold"),
                         width=16, anchor="w", padx=6).pack(side="left")
                var = tk.StringVar(value=content)
                e   = tk.Entry(row, textvariable=var, bg="#2a2a2a", fg=self.TEXT_WHITE,
                               font=("Helvetica Neue", 11), relief="flat",
                               insertbackground="white", width=26)
                e.pack(side="left", padx=4)
                entries[trigger] = var

                def delete(t=trigger):
                    s = load_snippets()
                    del s[t]
                    with open(SNIPPETS_FILE, "w") as f:
                        json.dump(s, f, indent=2)
                    refresh()

                tk.Button(row, text="✕", command=delete,
                          bg=self.RED, fg="white", font=("Helvetica Neue", 10),
                          relief="flat", padx=6).pack(side="left", padx=2)

        refresh()

        def save_all():
            snips = load_snippets()
            for trigger, var in entries.items():
                snips[trigger] = var.get()
            with open(SNIPPETS_FILE, "w") as f:
                json.dump(snips, f, indent=2)
            self.show_message("Snippets saved!", self.GREEN)
            swin.destroy()

        # Add new snippet
        add_frame = tk.Frame(swin, bg="#1a1a1a")
        add_frame.pack(fill="x", padx=16, pady=(0,4))
        tk.Label(add_frame, text="New trigger:", bg="#1a1a1a", fg=self.TEXT_DIM,
                 font=("Helvetica Neue", 11)).pack(side="left")
        new_trigger_var = tk.StringVar()
        tk.Entry(add_frame, textvariable=new_trigger_var, bg="#2a2a2a", fg=self.TEXT_WHITE,
                 font=("Helvetica Neue", 11), relief="flat",
                 insertbackground="white", width=14).pack(side="left", padx=4)
        tk.Label(add_frame, text="Content:", bg="#1a1a1a", fg=self.TEXT_DIM,
                 font=("Helvetica Neue", 11)).pack(side="left")
        new_content_var = tk.StringVar()
        tk.Entry(add_frame, textvariable=new_content_var, bg="#2a2a2a", fg=self.TEXT_WHITE,
                 font=("Helvetica Neue", 11), relief="flat",
                 insertbackground="white", width=16).pack(side="left", padx=4)

        def add_new():
            t = new_trigger_var.get().strip().lower()
            c = new_content_var.get().strip()
            if t and c:
                s = load_snippets()
                s[t] = c
                with open(SNIPPETS_FILE, "w") as f:
                    json.dump(s, f, indent=2)
                new_trigger_var.set("")
                new_content_var.set("")
                refresh()

        tk.Button(add_frame, text="Add", command=add_new,
                  bg="#0a84ff", fg="white", font=("Helvetica Neue", 11),
                  relief="flat", padx=10, pady=4, cursor="hand2").pack(side="left", padx=4)

        btn_frame = tk.Frame(swin, bg="#1a1a1a")
        btn_frame.pack(pady=8, fill="x", padx=16)
        tk.Button(btn_frame, text="Save Changes", command=save_all,
                  bg="#0a84ff", fg="white", font=("Helvetica Neue", 12, "bold"),
                  relief="flat", padx=20, pady=8, cursor="hand2").pack(side="right", padx=4)
        tk.Button(btn_frame, text="Close", command=swin.destroy,
                  bg="#2a2a2a", fg="#aaaaaa", font=("Helvetica Neue", 12),
                  relief="flat", padx=20, pady=8, cursor="hand2").pack(side="right", padx=4)

    def open_settings(self):
        self.root.after(0, self._show_settings)

    def _show_settings(self):
        win = tk.Toplevel(self.root)
        win.title("Dictation Settings")
        win.geometry("400x500")
        win.configure(bg="#1a1a1a")
        win.resizable(False, False)
        win.attributes("-topmost", True)

        style = ttk.Style(win)
        style.theme_use("clam")
        style.configure("TCombobox",
            fieldbackground="#2a2a2a", background="#2a2a2a",
            foreground="white", arrowcolor="white",
            selectbackground="#0a84ff", selectforeground="white",
            bordercolor="#444444", lightcolor="#2a2a2a", darkcolor="#2a2a2a")
        style.map("TCombobox",
            fieldbackground=[("readonly","#2a2a2a")],
            foreground=[("readonly","white")],
            background=[("readonly","#2a2a2a")])

        def section(text):
            tk.Label(win, text=text, bg="#1a1a1a", fg="#666666",
                     font=("Helvetica Neue", 10, "bold")).pack(
                     anchor="w", padx=20, pady=(16,4))
            tk.Frame(win, bg="#333333", height=1).pack(fill="x", padx=20)

        def row(label, widget_fn):
            f = tk.Frame(win, bg="#1a1a1a")
            f.pack(fill="x", padx=20, pady=5)
            tk.Label(f, text=label, bg="#1a1a1a", fg="#aaaaaa",
                     font=("Helvetica Neue", 12), width=13, anchor="w").pack(side="left")
            widget_fn(f).pack(side="right")

        def toggle_row(label, var):
            f = tk.Frame(win, bg="#1a1a1a")
            f.pack(fill="x", padx=20, pady=5)
            tk.Label(f, text=label, bg="#1a1a1a", fg="#aaaaaa",
                     font=("Helvetica Neue", 12), anchor="w").pack(side="left")
            # Custom toggle switch look
            cb = tk.Checkbutton(f, variable=var, bg="#1a1a1a",
                               activebackground="#1e1e1e",
                               selectcolor="#0a84ff",
                               relief="flat", cursor="hand2")
            cb.pack(side="right")

        section("TRANSCRIPTION")
        model_var = tk.StringVar(value=settings["model"])
        def model_w(f):
            cb = ttk.Combobox(f, textvariable=model_var,
                values=["tiny.en","base.en","small.en","medium.en"],
                state="readonly", width=14, font=("Helvetica Neue", 12))
            return cb
        row("Model", model_w)

        section("HOTKEYS")
        hotkey_var = tk.StringVar(value=settings.get("hotkey_label", "Right Command"))
        def hotkey_w(f):
            return ttk.Combobox(f, textvariable=hotkey_var,
                values=list(HOTKEY_OPTIONS.keys()),
                state="readonly", width=18, font=("Helvetica Neue", 12))
        row("Record Key", hotkey_w)

        for action, k in [("Cancel", "Escape"), ("Scratch", "Ctrl+Z"), ("Settings", "Ctrl+D")]:
            f = tk.Frame(win, bg="#1a1a1a")
            f.pack(fill="x", padx=20, pady=3)
            tk.Label(f, text=action, bg="#1a1a1a", fg="#aaaaaa",
                     font=("Helvetica Neue", 12), anchor="w").pack(side="left")
            tk.Label(f, text=k, bg="#2a2a2a", fg="#ffffff",
                     font=("Helvetica Neue", 11), padx=10, pady=3,
                     relief="flat").pack(side="right")

        section("DISPLAY")
        hud_var = tk.BooleanVar(value=settings.get("show_hud", True))
        toggle_row("Show HUD", hud_var)
        toggle_var = tk.BooleanVar(value=settings.get("toggle_mode", False))
        toggle_row("Toggle Mode", toggle_var)

        # Bottom buttons
        btn_frame = tk.Frame(win, bg="#1a1a1a")
        btn_frame.pack(fill="x", padx=20, pady=20, side="bottom")

        def save_and_close():
            settings["model"]        = model_var.get()
            settings["hotkey_label"] = hotkey_var.get()
            settings["show_hud"]     = hud_var.get()
            settings["toggle_mode"]  = toggle_var.get()
            save_settings(settings)
            if menubar:
                menubar._update_hud_label()
            win.destroy()
            self.show_message("Saved! Restart to apply.", self.GREEN)

        def styled_btn(parent, text, cmd, primary=False):
            color  = "#0a84ff" if primary else "#323232"
            fcolor = "#ffffff"
            b = tk.Button(parent, text=text, command=cmd,
                          bg=color, fg=fcolor, activebackground=color,
                          activeforeground=fcolor,
                          font=("Helvetica Neue", 12, "bold" if primary else "normal"),
                          relief="flat", bd=0,
                          padx=20, pady=9, cursor="hand2",
                          highlightthickness=0)
            return b

        styled_btn(btn_frame, "Manage Snippets",
                   lambda: self._show_snippets(win)).pack(side="left")
        styled_btn(btn_frame, "  Save  ",
                   save_and_close, primary=True).pack(side="right")

def reload_model():
    global whisper
    app.set_state("loading")
    app.show_message(f"Loading {settings['model']}...", "#0a84ff")
    whisper = WhisperModel(settings["model"], device=DEVICE, compute_type=COMPUTE)
    app.set_state("idle")

# ── Backend ───────────────────────────────────────────────────────────────────
def start_backend(stream):
    global whisper
    time.sleep(1.5)
    whisper = WhisperModel(MODEL, device=DEVICE, compute_type=COMPUTE)
    app._ready = True
    app.set_state("idle")
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
    menubar = MenuBarApp()
    root.mainloop()

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    import traceback
    try:
        main()
    except Exception as e:
        with open(os.path.expanduser("~/dictation_crash.log"), "w") as f:
            f.write(traceback.format_exc())
        raise
