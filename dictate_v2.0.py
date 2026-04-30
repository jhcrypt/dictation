#!/usr/bin/env python3
"""
Local Whisper Dictation v2 - Intel Mac
Double-tap Right Command to START recording
Double-tap Right Command again to STOP and transcribe
Escape to cancel | Ctrl+Z to scratch | Ctrl+, for settings
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
    import re
    words = text.split()
    corrected = []
    for word in words:
        # Strip trailing punctuation, correct, reattach
        match = re.match(r"([a-zA-Z\']+)([\.,!?;:]*)$", word)
        if match:
            core, punct = match.group(1), match.group(2)
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
    "hotkey_label": "Right Command (⌘)",
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

# ── Hotkey options ────────────────────────────────────────────────────────────
HOTKEY_OPTIONS = {
    "Right Command (⌘)": Key.cmd_r,
    "Right Option (⌥)":  Key.alt_r,
    "Right Control":      Key.ctrl_r,
    "F13":                Key.f13,
    "F14":                Key.f14,
    "F15":                Key.f15,
}

def get_record_key():
    label = settings.get("hotkey_label", "Right Command (⌘)")
    return HOTKEY_OPTIONS.get(label, Key.cmd_r)

# ── Config ────────────────────────────────────────────────────────────────────
MODEL       = settings["model"]
DEVICE      = "cpu"
COMPUTE     = "int8"
SAMPLE_RATE = settings["sample_rate"]
MIC_DEVICE  = settings["mic_device"]
CHANNELS    = 1
DOUBLE_TAP_WINDOW = 0.4   # seconds between taps to count as double-tap

# ── Globals ───────────────────────────────────────────────────────────────────
recording      = False
audio_frames   = []
last_text      = ""
typer          = Controller()
whisper        = None
app            = None
current_keys   = set()
cancelled      = False

# Double-tap tracking
_last_tap_time  = 0.0
_tap_count      = 0
_tap_timer      = None

# Chunk-based streaming
SILENCE_THRESHOLD  = 0.01      # RMS below this = silence
SILENCE_DURATION   = 1.2       # seconds of silence before transcribing chunk
MIN_CHUNK_SECONDS  = 0.5       # ignore chunks shorter than this
_chunk_frames      = []        # frames for current chunk
_silence_frames    = 0         # consecutive silent frames
_chunk_lock        = threading.Lock()
_chunk_thread      = None

# ── Active app ────────────────────────────────────────────────────────────────
def get_active_app_name():
    try:
        script = 'tell application "System Events" to get name of first application process whose frontmost is true'
        return subprocess.check_output(["osascript", "-e", script], timeout=1).decode().strip()
    except Exception:
        return ""

# ── Audio ─────────────────────────────────────────────────────────────────────
def audio_callback(indata, frames, time_info, status):
    global _silence_frames, _chunk_frames

    if not recording:
        return

    audio_frames.append(indata.copy())  # keep full recording for fallback

    rms = float(np.sqrt(np.mean(indata**2)))

    with _chunk_lock:
        if rms >= SILENCE_THRESHOLD:
            # Active speech — add to current chunk
            _chunk_frames.append(indata.copy())
            _silence_frames = 0
        else:
            # Silence
            _chunk_frames.append(indata.copy())  # include trailing silence
            _silence_frames += frames

            silence_secs = _silence_frames / SAMPLE_RATE
            chunk_secs   = len(_chunk_frames) * frames / SAMPLE_RATE / len(_chunk_frames)                            if _chunk_frames else 0
            total_secs   = len(_chunk_frames) / (SAMPLE_RATE / frames) if _chunk_frames else 0

            if silence_secs >= SILENCE_DURATION and total_secs >= MIN_CHUNK_SECONDS:
                # Flush this chunk for transcription
                chunk = list(_chunk_frames)
                _chunk_frames  = []
                _silence_frames = 0
                threading.Thread(target=_transcribe_chunk, args=(chunk,), daemon=True).start()

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

def _transcribe_chunk(frames):
    """Transcribe a chunk of audio and type it immediately — called during recording."""
    global last_text
    if not frames or not recording:
        return
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name
    try:
        save_wav(frames, wav_path)
        segments, _ = whisper.transcribe(
            wav_path,
            beam_size=5,
            language="en",
            initial_prompt="Transcribe spoken English accurately with correct spelling.",
            condition_on_previous_text=False,
        )
        raw_text = " ".join(seg.text for seg in segments).strip()
        if not raw_text:
            return

        lower = raw_text.lower().strip().rstrip(".").rstrip(",")
        if lower in ("scratch that", "undo that", "delete that"):
            _scratch_last()
            return
        elif lower in ("cancel", "never mind", "forget it", "cancel that"):
            app.show_message("Cancelled", "#ff9f0a")
            return
        elif lower in ("new line", "newline", "next line"):
            typer.press(Key.enter); typer.release(Key.enter)
            return
        elif lower in ("new paragraph",):
            typer.press(Key.enter); typer.release(Key.enter)
            typer.press(Key.enter); typer.release(Key.enter)
            return
        elif lower in ("tab", "indent"):
            typer.press(Key.tab); typer.release(Key.tab)
            return

        text = symspell_correct(raw_text)
        print(f"[chunk] {text!r}")
        last_text += text + " "
        app.set_transcript(text)
        typer.type(text + " ")
    finally:
        os.unlink(wav_path)


def transcribe_and_type(wav_path, raw_frames):
    global last_text, cancelled
    if cancelled:
        cancelled = False
        app.set_state("idle")
        return

    # No RMS cutoff — user controls start/stop via double-tap
    # Only skip if truly empty frames
    if not raw_frames:
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

    # Voice commands
    lower = raw_text.lower().strip().rstrip(".").rstrip(",")
    if lower in ("scratch that", "delete that", "undo that"):
        _scratch_last()
        app.set_state("idle")
        return
    elif lower in ("cancel", "never mind", "forget it", "cancel that"):
        app.show_message("Cancelled", "#ff9f0a")
        app.set_state("idle")
        return
    elif lower in ("new line", "newline", "next line"):
        typer.press(Key.enter)
        typer.release(Key.enter)
        app.show_message("New line", "#0a84ff")
        app.set_state("idle")
        return
    elif lower in ("new paragraph",):
        typer.press(Key.enter)
        typer.release(Key.enter)
        typer.press(Key.enter)
        typer.release(Key.enter)
        app.show_message("New paragraph", "#0a84ff")
        app.set_state("idle")
        return
    elif lower in ("tab", "indent"):
        typer.press(Key.tab)
        typer.release(Key.tab)
        app.show_message("Tab", "#0a84ff")
        app.set_state("idle")
        return
    elif lower in ("select all",):
        with typer.pressed(Key.cmd):
            typer.press('a')
            typer.release('a')
        app.show_message("Select all", "#0a84ff")
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
        for _ in range(len(last_text)):
            typer.press(Key.backspace)
            typer.release(Key.backspace)
        last_text = ""
    else:
        app.show_message("Nothing to scratch", "#ff9f0a")

def _process(frames):
    global _chunk_frames, _silence_frames
    # Flush any remaining unprocessed chunk
    with _chunk_lock:
        remaining = list(_chunk_frames)
        _chunk_frames   = []
        _silence_frames = 0

    if remaining:
        remaining_secs = len(remaining) * 512 / SAMPLE_RATE
        if remaining_secs >= MIN_CHUNK_SECONDS:
            _transcribe_chunk(remaining)

    # Final state update
    app.set_state("idle")

# ── Double-tap logic ──────────────────────────────────────────────────────────
def _handle_double_tap():
    """Called on confirmed double-tap of the record key."""
    global recording, audio_frames, cancelled

    if not recording:
        # Start recording
        recording    = True
        audio_frames = []
        cancelled    = False
        app.capture_active_app()
        app.set_state("recording")
        print("[hotkey] double-tap → recording started")
    else:
        # Stop recording
        recording = False
        frames = list(audio_frames)
        print("[hotkey] double-tap → recording stopped")
        if frames:
            threading.Thread(target=_process, args=(frames,), daemon=True).start()
        else:
            app.set_state("idle")

def _on_record_key_press():
    global _last_tap_time, _tap_count, _tap_timer

    now = time.time()

    if now - _last_tap_time < DOUBLE_TAP_WINDOW:
        # Second tap within window — it's a double-tap
        _tap_count = 0
        _last_tap_time = 0
        if _tap_timer:
            _tap_timer.cancel()
            _tap_timer = None
        _handle_double_tap()
    else:
        # First tap — start waiting for second
        _tap_count     = 1
        _last_tap_time = now
        if _tap_timer:
            _tap_timer.cancel()
        # If no second tap arrives, reset silently
        _tap_timer = threading.Timer(DOUBLE_TAP_WINDOW, _reset_tap)
        _tap_timer.start()

def _reset_tap():
    global _tap_count, _last_tap_time
    _tap_count     = 0
    _last_tap_time = 0

# ── Keyboard listener ─────────────────────────────────────────────────────────
def on_press(key):
    global cancelled

    if key in current_keys:
        return
    current_keys.add(key)

    record_key = get_record_key()
    ctrl       = Key.ctrl in current_keys or Key.ctrl_l in current_keys or Key.ctrl_r in current_keys
    is_z       = hasattr(key, 'char') and key.char == 'z'

    # Record key — double-tap to start/stop
    if key == record_key:
        _on_record_key_press()

    # Escape — cancel recording
    elif key == Key.esc and recording:
        cancelled = True
        # Stop capturing but don't process
        globals()['recording'] = False
        app.show_message("Cancelled", "#ff9f0a")
        threading.Timer(1.5, lambda: app.set_state("idle")).start()

    # Ctrl+Z — scratch last
    elif ctrl and is_z and not recording:
        threading.Thread(target=_scratch_last, daemon=True).start()

    # Ctrl+, — settings
    elif ctrl and hasattr(key, 'char') and key.char == ',':
        app.open_settings()

def on_release(key):
    current_keys.discard(key)

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

    def _pill(self, x1, y1, x2, y2, r, **kw):
        c = self.canvas
        c.create_arc(x1,     y1,     x1+2*r, y1+2*r, start=90,  extent=90,  style="pieslice", **kw)
        c.create_arc(x2-2*r, y1,     x2,     y1+2*r, start=0,   extent=90,  style="pieslice", **kw)
        c.create_arc(x1,     y2-2*r, x1+2*r, y2,     start=180, extent=90,  style="pieslice", **kw)
        c.create_arc(x2-2*r, y2-2*r, x2,     y2,     start=270, extent=90,  style="pieslice", **kw)
        c.create_rectangle(x1+r, y1,   x2-r, y2,     **kw)
        c.create_rectangle(x1,   y1+r, x2,   y2-r,   **kw)

    def _build(self):
        W, H = self.W, self.H
        self.canvas = tk.Canvas(self.root, width=W, height=H,
                                bg=self.BG, highlightthickness=0)
        self.canvas.pack()

        self._pill(2, 2, W-2, H-2, 14, fill="#242424", outline="")

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

        hotkey_label = settings.get("hotkey_label", "Right Command (⌘)").split(" ")[0] + \
                       " " + settings.get("hotkey_label", "Right Command (⌘)").split(" ")[1] \
                       if len(settings.get("hotkey_label","").split()) > 1 else \
                       settings.get("hotkey_label", "Right ⌘")

        if state == "idle":
            self.canvas.itemconfig(self.dot,   fill=self.TEXT_DIM)
            self.canvas.itemconfig(self.label,
                                   text=f"Double-tap {settings.get('hotkey_label','Right ⌘')} to dictate",
                                   fill=self.TEXT_DIM)
        elif state == "recording":
            self.canvas.itemconfig(self.dot,   fill=self.RED)
            self.canvas.itemconfig(self.label,
                                   text="Recording  ●  double-tap to stop",
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
        win.geometry("340x300")
        win.configure(bg=self.BG)
        win.resizable(False, False)
        win.attributes("-topmost", True)

        pad = {"padx": 16, "pady": 6}

        def row(label, widget_fn):
            f = tk.Frame(win, bg=self.BG)
            f.pack(fill="x", **pad)
            tk.Label(f, text=label, bg=self.BG, fg=self.TEXT_DIM,
                     font=("Helvetica Neue", 11), width=14, anchor="w").pack(side="left")
            widget_fn(f).pack(side="left", fill="x", expand=True)

        # Model
        model_var = tk.StringVar(value=settings["model"])
        def model_w(f):
            return ttk.Combobox(f, textvariable=model_var,
                                values=["tiny.en","base.en","small.en","medium.en"],
                                state="readonly", width=16)
        row("Model", model_w)

        # Record hotkey
        hotkey_var = tk.StringVar(value=settings.get("hotkey_label", "Right Command (⌘)"))
        def hotkey_w(f):
            return ttk.Combobox(f, textvariable=hotkey_var,
                                values=list(HOTKEY_OPTIONS.keys()),
                                state="readonly", width=20)
        row("Record Key", hotkey_w)

        # Fixed hotkeys
        tk.Label(win, text="Fixed Hotkeys", bg=self.BG, fg=self.TEXT_WHITE,
                 font=("Helvetica Neue", 12, "bold")).pack(anchor="w", padx=16, pady=(12,4))
        for action, key in [("Cancel", "Escape"), ("Scratch", "Ctrl+Z"), ("Settings", "Ctrl+,")]:
            f = tk.Frame(win, bg=self.BG)
            f.pack(fill="x", padx=16, pady=2)
            tk.Label(f, text=action, bg=self.BG, fg=self.TEXT_DIM,
                     font=("Helvetica Neue", 11), width=10, anchor="w").pack(side="left")
            tk.Label(f, text=key, bg="#2a2a2a", fg=self.TEXT_WHITE,
                     font=("Helvetica Neue", 11), padx=8, pady=2).pack(side="left")

        def save_and_close():
            settings["model"]        = model_var.get()
            settings["hotkey_label"] = hotkey_var.get()
            save_settings(settings)
            win.destroy()
            self.show_message("Saved! Restart to apply.", self.GREEN)

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
