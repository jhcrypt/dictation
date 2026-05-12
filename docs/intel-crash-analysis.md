# Intel Mac Crash Analysis — Packaged App vs Terminal

**Affected versions:** All builds prior to v6.1.24-stable  
**Fixed in:** v6.1.24-stable (commit `9da30df`)  
**Platforms:** Intel (x86_64) Mac — does not affect Apple Silicon (arm64)

---

## Symptom

The app crashes on Intel when:
1. A window is opened from the status bar (settings, history, snippets)
2. The window is closed
3. Dictation is attempted

**Key observation:** The crash does not occur when the app is launched from the terminal. It only occurs in the packaged `.app`. This rules out a logic bug and points directly to a packaging / thread-enforcement difference.

---

## Why Terminal Launch Works but the Packaged App Does Not

When launched from the terminal, the process inherits the shell's environment including an established macOS UI session. macOS is permissive about which thread calls certain system APIs in this context.

When launched as a packaged `.app` by double-click, the process starts with a clean environment and must acquire its own UI session. macOS strictly enforces thread ownership rules for UI and input-related APIs in this context — calls that silently succeed in the terminal will raise `dispatch_assert_queue_fail` and crash the app.

---

## Root Cause

### The Crash: `TSMGetInputSourceProperty` on a Background Thread

pynput's darwin `Controller` calls `TSMGetInputSourceProperty` (macOS Text Services Manager) internally whenever it resolves a character string to a key code — for example `typer.press("v")` or `typer.type(text)`.

TSM requires the **main thread** (main dispatch queue). In the packaged `.app`, calling it from a worker thread raises:

```
dispatch_assert_queue_fail
  islGetInputSourceListWithAdditions
  isValidateInputSourceRef
  TSMGetInputSourceProperty       ← must be on main thread
  ffi_call / _ctypes_callproc     ← pynput via ctypes
  thread_run                      ← called from background thread
```

### Why the Window Open/Close Triggers It

The dictation pipeline always ran pynput calls from a background thread — the crash was always latent. The window open/close sequence makes it reliably reproducible because:

- `_toplevel_opened()` calls `_stop_kb_listener()`, modifying shared thread state
- `_toplevel_closed()` schedules `_schedule_listener_restart()` via `root.after(800, ...)`
- The 800 ms delay and the Tkinter event loop flush change the timing of the background transcription thread relative to the main thread

On Apple Silicon the macOS scheduler is more forgiving of this race. On Intel, the stricter `dispatch_assert_queue` enforcement catches it every time.

---

## Why Intel Has More Issues Than Apple Silicon

### 1. Intel MKL Thread Interference
NumPy, SciPy, and ctranslate2 on Intel use Intel's Math Kernel Library (MKL), which spawns its own C++ worker threads. These threads interact badly with Python's GIL and Tkinter's Cocoa event loop, producing `SIGILL` (illegal hardware instruction) crashes — particularly when pynput's keyboard listener is started or restarted while Tkinter is running. Apple Silicon uses Apple's Accelerate framework instead, which does not have this conflict.

This is why the code already contains:
```python
# INTEL STABILITY: Caps Lock is the specific trigger for the Intel MKL /
# Tkinter register conflict ("illegal hardware instruction").
if key == Key.caps_lock:
    return
```
And:
```python
# Force ONNX Runtime to use a single thread with no internal thread pool.
_sess_opts.inter_op_num_threads = 1
_sess_opts.intra_op_num_threads = 1
```

### 2. Stricter `dispatch_assert_queue` Enforcement
On Intel Macs, certain macOS versions enforce main-thread requirements for TSM and related Carbon/HIToolbox APIs more aggressively in sandboxed or self-contained processes (like a packaged `.app`) than in terminal-launched processes.

### 3. PyInstaller x86_64 Bootloader
The Intel PyInstaller bootloader bundles `x86_64` dylibs that carry stricter Mach-O load constraints in some macOS versions. Mixed-architecture or Rosetta scenarios add further unpredictability.

### 4. Unified Memory vs Shared Bus
Apple Silicon's unified memory architecture reduces contention between threads accessing shared resources. On Intel, separate CPU and GPU memory with a shared bus creates more opportunity for thread timing conflicts to manifest as crashes.

---

## The Fix (Already in v6.1.24)

A `_run_on_main()` trampoline was added at `src/jarvis_dictation.py` ~line 495. It detects whether the caller is on the main thread; if not, it schedules the work via `app.root.after(0, ...)` and blocks until complete.

```python
def _run_on_main(fn):
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
```

All pynput `Controller` calls that use character-string arguments (which trigger TSM lookups) were wrapped with this trampoline:

| Location | Call | Fix |
|---|---|---|
| `paste_text()` | `_KbdCtrl().press('v')` | `_run_on_main(_pynput_cmd_v)` |
| `paste_text()` | `typer.type(text + " ")` (fallback) | `_run_on_main(lambda: typer.type(...))` |
| `transcribe_and_type()` | `typer.type(PUNCT_COMMANDS[lower])` | `_run_on_main(lambda: typer.type(...))` |
| `transcribe_and_type()` | `typer.press("a")` in "select all" | `_run_on_main(_select_all)` |
| `transcribe_and_type()` | `typer.press("a/c")` in "copy all" | `_run_on_main(_copy_all)` |
| `transcribe_and_type()` | `typer.press("v")` in "paste" | `_run_on_main(_paste_cmd)` |

`Key.*` enum values (e.g. `Key.backspace`, `Key.enter`, `Key.tab`) use hardcoded key codes and do not go through TSM — those calls are safe from any thread and were not changed.

---

## Building the Fix on Intel

The fix is in `main` (v6.1.24). Pull and rebuild:

```bash
cd /path/to/dictation
git pull origin main

conda activate dictation      # Intel conda env with x86_64 Python 3.11
cd packaging/mac
bash build_mac_app.sh
```

After installing the new build, the window open → close → dictate crash will not occur.

---

## If Crashes Continue After v6.1.24 on Intel

If new crashes appear, they are likely MKL-related rather than TSM-related. Things to check:

1. **Confirm single-threaded ONNX** — search for `inter_op_num_threads` in `src/jarvis_dictation.py` and verify it is set to `1` before the Whisper model loads.
2. **Check for Caps Lock involvement** — if the crash correlates with the Caps Lock key, the MKL/Tkinter SIGILL is the cause. The `on_press` guard (`if key == Key.caps_lock: return`) must be present.
3. **Check crash type** — `SIGILL` = MKL conflict. `SIGABRT` / `dispatch_assert_queue_fail` = TSM thread issue (should be fixed by v6.1.24). `EXC_BAD_ACCESS` = memory issue, different cause.
4. **Crash logs** — Intel crash reports are at `~/Library/Logs/DiagnosticReports/JarvisDictation-*.ips`.
