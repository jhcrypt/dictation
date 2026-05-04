#!/usr/bin/env python
"""
Local Whisper Dictation - Stable Build
Fixed Menu Bar + Local CTranslate2 Engine
"""

import threading, tempfile, os, sys, time, wave, subprocess, json, re
import urllib.request as _urllib

# FOR STABILITY: Prevents library conflicts and forces standard instructions
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["CT2_USE_EXPERIMENTAL_PACKED_GEMM"] = "0"
os.environ["OMP_NUM_THREADS"] = "1"

try:
    import sounddevice as sd
    import numpy as np
    from pynput import keyboard
    from pynput.keyboard import Controller, Key
    from faster_whisper import WhisperModel
except ImportError as e:
    print(f"\nMissing dependency: {e}"); sys.exit(1)

import tkinter as tk
from tkinter import ttk

# --- SETTINGS ---
SETTINGS_FILE = os.path.expanduser("~/.dictation_settings.json")
DEFAULT_SETTINGS = {
    "model": "small.en", 
    "mic_device": 2, 
    "sample_rate": 48000, 
    "hotkey_label": "Right Option", 
    "show_hud": True, 
    "toggle_mode": True,
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

settings = load_settings()
HOTKEY_OPTIONS = {"Right Command": Key.cmd_r, "Right Option": Key.alt_r, "Right Control": Key.ctrl_r, "F13": Key.f13, "F14": Key.f14, "F15": Key.f15}

# --- GLOBALS ---
recording, audio_frames, last_text, typer, whisper, app, current_keys = False, [], "", Controller(), None, None, set()

# --- MENU BAR LOGIC (FIXED VERSION) ---
class MenuBarApp:
    def __init__(self):
        self._available = False
        try:
            from AppKit import NSStatusBar, NSVariableStatusItemLength, NSMenu, NSMenuItem, NSImage
            from Foundation import NSObject
            import objc

            class MenuDelegate(NSObject):
                def quitApp_(self, sender): os._exit(0)
                def toggleHUD_(self, sender):
                    settings["show_hud"] = not settings.get("show_hud", True)
                    if app: app.root.after(0, app.root.deiconify if settings["show_hud"] else app.root.withdraw)

            self._delegate = MenuDelegate.alloc().init()
            bar = NSStatusBar.systemStatusBar()
            self._item = bar.statusItemWithLength_(NSVariableStatusItemLength)
            self._item.button().setTitle_("🎙️")
            
            self._menu = NSMenu.alloc().init()
            # FIXED: Proper status item initialization
            self._status_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Status: Idle", None, "")
            self._menu.addItem_(self._status_item)
            self._menu.addItem_(NSMenuItem.separatorItem())
            
            quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit", "quitApp:", "")
            quit_item.setTarget_(self._delegate)
            self._menu.addItem_(quit_item)
            self._item.setMenu_(self._menu)
            self._available = True
        except Exception: self._available = False

    def set_state(self, state):
        if not self._available: return
        # FIXED: Clean label mapping instead of raw dictionary code
        labels = {'idle': 'Idle', 'recording': 'Recording...', 'transcribing': 'Thinking...'}
        new_title = f"Status: {labels.get(state, 'Idle')}"
        
        # UI SAFETY: Update on Main Thread to prevent Intel crashes
        if app and app.root:
            app.root.after(0, lambda: self._status_item.setTitle_(new_title))

# --- APP UI ---
class DictationApp:
    def __init__(self, root):
        self.root = root
        self.W, self.H = 420, 52
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
        
        # HUD RECOVERY: Snap to top-left of primary monitor to avoid Ultrawide "void"
        self.root.geometry(f"{self.W}x{self.H}+150+150")
        
        self.canvas = tk.Canvas(self.root, width=self.W, height=self.H, bg="#1c1c1c", highlightthickness=0)
        self.canvas.pack()
        self.dot = self.canvas.create_oval(20, 20, 32, 32, fill="#4a4a4a")
        self.label = self.canvas.create_text(50, 26, text="Local V2 Ready", fill="#ffffff", anchor="w")

    def set_state(self, state):
        self.root.after(0, self._apply_state, state)
        if menubar: menubar.set_state(state)

    def _apply_state(self, state):
        colors = {"idle": "#4a4a4a", "recording": "#ff3b30", "transcribing": "#0a84ff"}
        self.canvas.itemconfig(self.dot, fill=colors.get(state, "#4a4a4a"))
        self.canvas.itemconfig(self.label, text=state.capitalize())

# --- CORE PROCESSING ---
def audio_callback(indata, frames, time_info, status):
    if recording: audio_frames.append(indata.copy())

def _process(frames):
    global last_text
    app.set_state("transcribing")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f: wav_path = f.name
    
    audio = np.concatenate(frames, axis=0)
    # Resample math for local engine
    target_len = int(len(audio) * 16000 / 48000)
    resampled = np.interp(np.linspace(0, len(audio)-1, target_len), np.arange(len(audio)), audio[:, 0]).astype(np.float32)
    
    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
        wf.writeframes((resampled * 32767).astype(np.int16).tobytes())
    
    segments, _ = whisper.transcribe(wav_path, beam_size=5)
    raw_text = " ".join(seg.text for seg in segments).strip()
    
    if raw_text:
        typer.type(raw_text + " ")
        last_text = raw_text
    
    os.unlink(wav_path)
    app.set_state("idle")

def on_press(key):
    global recording, audio_frames
    record_key = HOTKEY_OPTIONS.get(settings.get("hotkey_label", "Right Option"), Key.alt_r)
    if key == record_key and not recording:
        recording, audio_frames = True, []
        app.set_state("recording")

def on_release(key):
    global recording
    record_key = HOTKEY_OPTIONS.get(settings.get("hotkey_label", "Right Option"), Key.alt_r)
    if key == record_key and recording:
        recording = False
        frames = list(audio_frames)
        threading.Thread(target=_process, args=(frames,), daemon=True).start()

def main():
    global app, menubar, whisper
    # Standard WhisperModel loading that worked before
    whisper = WhisperModel(settings["model"], device="cpu", compute_type="int8")
    
    root = tk.Tk()
    app = DictationApp(root)
    menubar = MenuBarApp()
    
    with sd.InputStream(samplerate=48000, channels=1, callback=audio_callback):
        with keyboard.Listener(on_press=on_press, on_release=on_release):
            root.mainloop()

if __name__ == "__main__":
    main()