#!/usr/bin/env python3
"""
Local Whisper Dictation v2 - Intel Mac
Hotkey controls:
  - Hold Ctrl+S  : record, release to transcribe
  - Escape       : cancel recording in progress
  - Ctrl+Z       : delete last dictation (scratch that)
  - Ctrl+,       : open settings window
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

try:
    import sounddevice as sd
    import numpy as np
    from pynput import keyboard
    from pynput.keyboard import Controller, Key
    from faster_whisper import WhisperModel
except ImportError as e:
    print(f"\nMissing dependency: {e}")
    print("Run:  pip install sounddevice pynput numpy faster-whisper\n")
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
    print("[symspell] not installed, skipping")

def symspell_correct(text):
    if not USE_SYMSPELL:
        return text
    words = text.split()
    corrected = []
    for word in words:
        suggestions = _sym.lookup(word.lower(), Verbosity.CLOSEST, max_edit_distance=2)
        if suggestions:
            s = suggestions[0].term
            if word and word[0].isupper():
                s = s.capitalize()
            corrected.append(s)
        else:
            corrected.append(word)
    return " ".join(corrected)

# ── Settings ──────────────────────────────────────────────────────────────────
SETTINGS_FILE = os.path.expanduser("~/.dictation_settings.json")

DEFAULT_SETTINGS = {
    "model":       "small.en",
    "mic_device":  2,
    "sample_rate": 48000,
    "hotkey":      "ctrl+s",
    "cancel_key":  "escape",
    "scratch_key": "ctrl+z",
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE) as f:
                s = json.load(f)
                # Fill in any missing keys with defaults
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

# ── Config (from settings) ────────────────────────────────────────────────────
MODEL       = settings["model"]
DEVICE      = "cpu"
COMPUTE     = "int8"
SAMPLE_RATE = settings["sample_rate"]
MIC_DEVICE  = settings["mic_device"]
CHANNELS    = 1

# ── Globals ───────────────────────────────────────────────────────────────────
recording      = False
audio_frames   = []
last_text      = ""        # for scratch that
typer          = Controller()
whisper        = None
app            = None
current_keys   = set()
cancelled      = False

# ── Active app ────────────────────────────────────────────────────────────────
def get_active_app_name():
    try:
        script = 'tell application "System Events" to get name of first application process whose frontmost is true'
        return subprocess.check_output(["osascript", "-e", script], timeout=1).decode().strip()
    except Exception:
        return ""

# ── Audio ─────────────────────────────────────────────────────────────────────
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

def transcribe_and_type(wav_path, raw_frames):
    global last_text, cancelled
    if cancelled:
        cancelled = False
        app.set_state("idle")
        return

    audio = np.concatenate(raw_frames, axis=0)
    rms   = np.sqrt(np.mean(audio**2))
    if rms < 0.01:
        app.set_state("idle")
        return

    app.set_state("transcribing")
    segments, _ = whisper.transcribe(
        wav_path,
        beam_size=5,
        language="en",
        initial_prompt="Transcribe spoken English accurately with correct spelling.",
        condition_on_previous_text=False,
    )
    raw_text = " ".join(seg.text for seg in segments).strip()
    if not raw_text:
        app.set_state("idle")
        return

    # Check for voice "scratch that" command
    lower = raw_text.lower().strip().rstrip(".")
    if lower in ("scratch that", "delete that", "never mind", "cancel that"):
        _scratch_last()
        app.set_state("idle")
        return

    text = symspell_correct(raw_text)
    print(f"[raw]       {raw_text!r}")
    if text != raw_text:
        print(f"[corrected] {text!r}")

    last_text = text
    app.set_transcript(text)
    time.sleep(0.15)
    typer.type(text)
    time.sleep(4.0)
    app.set_state("idle")

def _scratch_last():
    global last_text
    if last_text:
        print(f"[scratch] deleting: {last_text!r}")
        app.show_message("Scratched!", "#ff9f0a")
        # Select and delete the last typed text
        for _ in range(len(last_text)):
            typer.press(Key.backspace)
            typer.release(Key.backspace)
        last_text = ""

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

    ctrl = Key.ctrl in current_keys or Key.ctrl_l in current_keys or Key.ctrl_r in current_keys
    is_s = hasattr(key, 'char') and key.char == 's'
    is_z = hasattr(key, 'char') and key.char == 'z'
    is_escape = key == Key.esc

    # Ctrl+S — start recording
    if ctrl and is_s and not recording:
        recording    = True
        audio_frames = []
        cancelled    = False
        app.capture_active_app()
        app.set_state("recording")

    # Escape — cancel recording
    elif is_escape and recording:
        recording = False
        cancelled = True
        app.show_message("Cancelled", "#ff9f0a")
        threading.Timer(1.5, lambda: app.set_state("idle")).start()

    # Ctrl+Z — scratch last dictation
    elif ctrl and is_z and not recording:
        threading.Thread(target=_scratch_last, daemon=True).start()

    # Ctrl+, — open settings
    elif ctrl and hasattr(key, 'char') and key.char == ',':
        app.open_settings()

def on_release(key):
    global recording
    current_keys.discard(key)
    is_s = hasattr(key, 'char') and key.char == 's'
    if is_s and recording:
        recording = False
        frames = list(audio_frames)
        if frames:
            threading.Thread(target=_process, args=(frames,), daemon=True).start()
        else:
            app.set_state("idle")

# ── GUI ───────────────────────────────────────────────────────────────────────
class DictationApp:
    BG         = "#1c1c1c"
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
        self._blink_job = None
        self._blink_on  = True
        self._drag_x    = 0
        self._drag_y    = 0
        self._msg_timer = None

        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
        self.root.configure(bg=self.BG)
        self.root.resizable(False, False)

        sw = self.root.winfo_screenwidth()
        self.root.geometry(f"{self.W}x{self.H}+{sw//2 - self.W//2}+24")

        try:
            import objc
            from AppKit import NSApplication
            self.root.update_idletasks()
            for win in NSApplication.sharedApplication().windows():
                win.setCornerMask_(0b1111)
                win.setOpaque_(False)
        except Exception:
            pass

        self._build()
        self._make_draggable()

    def _build(self):
        W, H = self.W, self.H
        self.canvas = tk.Canvas(self.root, width=W, height=H,
                                bg=self.BG, highlightthickness=0)
        self.canvas.pack()

        self.dot = self.canvas.create_oval(20, H//2-6, 32, H//2+6,
                                           fill=self.TEXT_DIM, outline="")
        self.canvas.create_line(46, 14, 46, H-14, fill="#303030", width=1)
        self.label = self.canvas.create_text(
            58, H//2, text="Loading model...",
            font=("Helvetica Neue", 13),
            fill=self.TEXT_DIM, anchor="w", width=260
        )
        self.appname = self.canvas.create_text(
            W-32, H//2, text="",
            font=("Helvetica Neue", 11),
            fill=self.TEXT_DIM, anchor="e"
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
        self.canvas.bind("<ButtonPress-1>",
                         lambda e: (setattr(self, '_drag_x', e.x_root - self.root.winfo_x()),
                                    setattr(self, '_drag_y', e.y_root - self.root.winfo_y())))
        self.canvas.bind("<B1-Motion>",
                         lambda e: self.root.geometry(
                             f"+{e.x_root-self._drag_x}+{e.y_root-self._drag_y}"))

    def capture_active_app(self):
        threading.Thread(target=lambda: self.root.after(
            0, lambda: self.canvas.itemconfig(self.appname, text=get_active_app_name())
        ), daemon=True).start()

    def set_state(self, state):
        self.root.after(0, self._apply_state, state)

    def _apply_state(self, state):
        if self._blink_job:
            self.root.after_cancel(self._blink_job)
            self._blink_job = None
        if state == "idle":
            self.canvas.itemconfig(self.dot,   fill=self.TEXT_DIM)
            self.canvas.itemconfig(self.label, text="Hold Ctrl+S to dictate",
                                   fill=self.TEXT_DIM)
        elif state == "recording":
            self.canvas.itemconfig(self.dot,   fill=self.RED)
            self.canvas.itemconfig(self.label, text="Recording...  release to stop",
                                   fill=self.TEXT_WHITE)
            self._blink()
        elif state == "transcribing":
            self.canvas.itemconfig(self.dot,   fill=self.BLUE)
            self.canvas.itemconfig(self.label, text="Transcribing...", fill=self.BLUE)

    def set_transcript(self, text):
        self.root.after(0, self._show_transcript, text)

    def _show_transcript(self, text):
        short = text if len(text) <= 48 else text[:45] + "..."
        self.canvas.itemconfig(self.dot,   fill=self.GREEN)
        self.canvas.itemconfig(self.label, text=short, fill=self.TEXT_WHITE)

    def show_message(self, msg, color=None):
        self.root.after(0, self._show_msg, msg, color or self.ORANGE)

    def _show_msg(self, msg, color):
        if self._msg_timer:
            self.root.after_cancel(self._msg_timer)
        self.canvas.itemconfig(self.dot,   fill=color)
        self.canvas.itemconfig(self.label, text=msg, fill=color)
        self._msg_timer = self.root.after(2000, lambda: self._apply_state("idle"))

    def _blink(self):
        self._blink_on = not self._blink_on
        self.canvas.itemconfig(self.dot, fill=self.RED if self._blink_on else "#4a1510")
        self._blink_job = self.root.after(500, self._blink)

    def open_settings(self):
        self.root.after(0, self._show_settings)

    def _show_settings(self):
        win = tk.Toplevel(self.root)
        win.title("Dictation Settings")
        win.geometry("340x280")
        win.configure(bg=self.BG)
        win.resizable(False, False)
        win.attributes("-topmost", True)

        pad = {"padx": 16, "pady": 6}

        def row(label, widget):
            f = tk.Frame(win, bg=self.BG)
            f.pack(fill="x", **pad)
            tk.Label(f, text=label, bg=self.BG, fg=self.TEXT_DIM,
                     font=("Helvetica Neue", 11), width=14, anchor="w").pack(side="left")
            widget(f).pack(side="left", fill="x", expand=True)

        # Model
        model_var = tk.StringVar(value=settings["model"])
        def model_widget(f):
            return ttk.Combobox(f, textvariable=model_var,
                                values=["tiny.en","base.en","small.en","medium.en"],
                                state="readonly", width=16)
        row("Model", model_widget)

        # Hotkey display (read-only for now)
        tk.Label(win, text="Hotkey Controls", bg=self.BG, fg=self.TEXT_WHITE,
                 font=("Helvetica Neue", 12, "bold")).pack(anchor="w", padx=16, pady=(12,4))

        hotkeys = [
            ("Record",    "Hold Ctrl+S"),
            ("Cancel",    "Escape"),
            ("Scratch",   "Ctrl+Z"),
            ("Settings",  "Ctrl+,"),
        ]
        for action, key in hotkeys:
            f = tk.Frame(win, bg=self.BG)
            f.pack(fill="x", padx=16, pady=2)
            tk.Label(f, text=action, bg=self.BG, fg=self.TEXT_DIM,
                     font=("Helvetica Neue", 11), width=10, anchor="w").pack(side="left")
            tk.Label(f, text=key, bg="#2a2a2a", fg=self.TEXT_WHITE,
                     font=("Helvetica Neue", 11), padx=8, pady=2).pack(side="left")

        def save_and_close():
            settings["model"] = model_var.get()
            save_settings(settings)
            win.destroy()
            app.show_message("Settings saved! Restart to apply.", self.GREEN)

        tk.Button(win, text="Save", command=save_and_close,
                  bg=self.BLUE, fg="white", font=("Helvetica Neue", 12),
                  relief="flat", padx=16, pady=6).pack(pady=16)

# ── Backend ───────────────────────────────────────────────────────────────────
def start_backend(stream):
    global whisper
    whisper = WhisperModel(MODEL, device=DEVICE, compute_type=COMPUTE)
    app.set_state("idle")
    with keyboard.Listener(on_press=on_press, on_release=on_release):
        stream.start()
        threading.Event().wait()

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    global app
    root = tk.Tk()
    app  = DictationApp(root)
    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        device=MIC_DEVICE,
        callback=audio_callback,
    )
    threading.Thread(target=start_backend, args=(stream,), daemon=True).start()
    root.mainloop()

if __name__ == "__main__":
    main()
