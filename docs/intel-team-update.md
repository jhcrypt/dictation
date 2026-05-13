# Intel Team Update — v6.1.24 through v6.1.26

**Prepared for:** Intel (x86_64) build team  
**Source of truth:** `main` branch, commits covering v6.1.24–v6.1.26  
**Prior Intel stable:** v6.1.23  
**Reference docs:** `docs/intel-crash-analysis.md`, `docs/symspell-fix.md`

This document lists every change made to the M1 build since v6.1.23 and provides exact code and instructions to apply each change to the Intel branch.

---

## Summary of Changes

| Version | Change | Risk |
|---------|--------|------|
| v6.1.24 | **Critical crash fix** — `_run_on_main()` trampoline for all pynput TSM calls | Crash fix — high priority |
| v6.1.24 | **SymSpell path fix** — spell correction was silently disabled in packaged app | Silent bug fix — apply immediately |
| v6.1.24 | **App icon** — `.icns` file added to spec and assets | Cosmetic |
| v6.1.25 | **Custom Commands** — new user-configurable voice commands stored in JSON | New feature |
| v6.1.25 | **Spotify/URI prefix fix** — `spotify:` URIs were incorrectly prepended with `https://` | Bug fix in new feature |
| v6.1.26 | **Settings window height** — increased from 620 to 680 px | UI fix (Save button clipped) |
| v6.1.26 | **Snippets window explanations** — UI copy updated to match Custom Commands clarity | Cosmetic |

---

## Change 1 — `_run_on_main()` Trampoline (CRITICAL)

**Why:** pynput's darwin `Controller` calls `TSMGetInputSourceProperty` (macOS Text Services Manager) whenever it resolves a character string to a key code — e.g. `press('v')` or `type(text)`. TSM requires the **main thread**. In the packaged `.app`, calling it from a background transcription thread raises `dispatch_assert_queue_fail` and crashes the app. This explains why v6.1.23 crashes after opening and closing a settings window — the window interaction changes thread timing, making the race reliable. See `docs/intel-crash-analysis.md` for the full analysis.

**Note for Intel:** The crash is more severe on Intel because `dispatch_assert_queue` enforcement is stricter in sandboxed processes on certain Intel macOS versions. Apply this fix first.

### Add the helper function

In `src/jarvis_dictation.py`, find `_safe_print()` (around line 490) and add the following immediately after it:

```python
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
```

### Wrap pynput calls in `paste_text()`

Find the primary pynput Cmd+V block in `paste_text()`:

**Before:**
```python
from pynput.keyboard import Controller as _KbdCtrl, Key as _Key
_kbd = _KbdCtrl()
with _kbd.pressed(_Key.cmd):
    _kbd.press('v')
    _kbd.release('v')
```

**After:**
```python
from pynput.keyboard import Controller as _KbdCtrl, Key as _Key
def _pynput_cmd_v():
    _kbd = _KbdCtrl()
    with _kbd.pressed(_Key.cmd):
        _kbd.press('v')
        _kbd.release('v')
_run_on_main(_pynput_cmd_v)
```

Find the direct-type fallback in `paste_text()` (used when Cmd+V fails):

**Before:**
```python
typer.type(text + " ")
```

**After:**
```python
_run_on_main(lambda: typer.type(text + " "))
```

### Wrap pynput calls in `transcribe_and_type()`

Find each of the following blocks and apply the wraps:

**Punctuation commands — Before:**
```python
typer.type(PUNCT_COMMANDS[lower])
```
**After:**
```python
_run_on_main(lambda cmd=PUNCT_COMMANDS[lower]: typer.type(cmd))
```

**"select all" — Before:**
```python
with typer.pressed(Key.cmd):
    typer.press("a"); typer.release("a")
```
**After:**
```python
def _select_all():
    with typer.pressed(Key.cmd):
        typer.press("a"); typer.release("a")
_run_on_main(_select_all)
```

**"copy all" — Before:**
```python
with typer.pressed(Key.cmd):
    typer.press("a"); typer.release("a")
time.sleep(0.05)
with typer.pressed(Key.cmd):
    typer.press("c"); typer.release("c")
```
**After:**
```python
def _copy_all():
    with typer.pressed(Key.cmd):
        typer.press("a"); typer.release("a")
    time.sleep(0.05)
    with typer.pressed(Key.cmd):
        typer.press("c"); typer.release("c")
_run_on_main(_copy_all)
```

**"paste" / "paste that" — Before:**
```python
with typer.pressed(Key.cmd):
    typer.press("v"); typer.release("v")
```
**After:**
```python
def _paste_cmd():
    with typer.pressed(Key.cmd):
        typer.press("v"); typer.release("v")
_run_on_main(_paste_cmd)
```

**What NOT to wrap:** `Key.*` enum values (`Key.backspace`, `Key.enter`, `Key.tab`, `Key.shift`, `Key.cmd`) use hardcoded key codes and never go through TSM. Those calls are thread-safe and must not be changed.

---

## Change 2 — SymSpell Dictionary Path Fix

**Why:** The dictionary path was hardcoded to the developer's local conda env. On any other machine — including the Intel build machine — `os.path.exists()` returns `False`, `USE_SYMSPELL` stays `False`, and spell correction is silently disabled in every packaged build. See `docs/symspell-fix.md` for full details.

Find the SymSpell initialization block in `src/jarvis_dictation.py` (search for `USE_SYMSPELL`):

**Before:**
```python
try:
    from symspellpy import SymSpell, Verbosity
    _sym = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
    _DICT = os.path.expanduser(
        "~/miniconda3/lib/python3.11/site-packages/symspellpy/frequency_dictionary_en_82_765.txt"
    )
    USE_SYMSPELL = os.path.exists(_DICT) and _sym.load_dictionary(_DICT, term_index=0, count_index=1)
except ImportError:
    USE_SYMSPELL = False
```

**After:**
```python
try:
    from symspellpy import SymSpell, Verbosity
    import symspellpy as _symspellpy_pkg
    _sym = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
    _DICT = os.path.join(
        os.path.dirname(_symspellpy_pkg.__file__),
        "frequency_dictionary_en_82_765.txt"
    )
    USE_SYMSPELL = os.path.exists(_DICT) and _sym.load_dictionary(_DICT, term_index=0, count_index=1)
except ImportError:
    USE_SYMSPELL = False
```

**Verify before rebuilding:**
```bash
conda activate dictation   # your Intel conda env
python - <<'EOF'
import os, symspellpy as p
d = os.path.join(os.path.dirname(p.__file__), "frequency_dictionary_en_82_765.txt")
print("EXISTS:", os.path.exists(d))
print("PATH  :", d)
EOF
```
Both lines must print `True` and a valid path. If symspellpy is not installed: `pip install symspellpy`.

---

## Change 3 — App Icon

**Why:** The `.app` was shipping without an icon. The M1 build now includes a custom `.icns` file.

### Step 1 — Copy the icon asset

The icon file is at `packaging/mac/assets/jarvis_dictation.icns`. If the Intel repo does not have this file, copy it from the M1 repo or download it from the `main` branch. Place it at the same path.

### Step 2 — Update the spec

In `packaging/mac/JarvisDictation.spec`, find the `BUNDLE` block and update the `icon=` line:

**Before:**
```python
app = BUNDLE(
    coll,
    name='Jarvis Dictation.app',
    icon=None,
    ...
)
```

**After:**
```python
app = BUNDLE(
    coll,
    name='Jarvis Dictation.app',
    icon=os.path.join(spec_dir, 'assets', 'jarvis_dictation.icns'),
    ...
)
```

---

## Change 4 — Custom Commands Feature

**Why:** Users requested the ability to create their own voice commands without editing source code. Custom commands are stored in `~/.dictation_custom_commands.json` and checked before all built-in Jarvis commands. Supported actions: `open_url`, `open_app`, `type_text`.

### Step 1 — Add constants and load/save helpers

Near `SNIPPETS_FILE` (search for that name), add:

```python
CUSTOM_COMMANDS_FILE = os.path.expanduser("~/.dictation_custom_commands.json")

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
```

### Step 2 — Check custom commands first in `_fast_jarvis_match()`

At the very top of `_fast_jarvis_match()`, before the built-in command checks, add:

```python
def _fast_jarvis_match(lower):
    import re
    # ── Custom user commands — checked before all built-ins ───────────────
    for _cmd in load_custom_commands():
        _trigger = _cmd.get("trigger", "").lower().strip()
        if not _trigger or len(_trigger.split()) < 2:
            continue
        if lower == _trigger:
            return ("custom_command", _cmd)
    # ── Built-in commands ──────────────────────────────────────────────────
    # ... rest of existing function unchanged
```

### Step 3 — Handle `custom_command` action in `execute_jarvis_command()`

In `execute_jarvis_command()`, after the `close_app` block and before the `play_media` block, add:

```python
elif action == "custom_command":
    cmd_action = params.get("action", "")
    target     = params.get("target", "").strip()
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
```

### Step 4 — Add Custom Commands to the Settings nav

In `_open_settings()`, find the `nav_items` list and add `"Custom Commands"`:

```python
nav_items = [
    "Setup",
    "Dictation",
    "Audio",
    "AI Cleanup",
    "Writing Profiles",
    "Jarvis",
    "Custom Commands",    # ← add this
    "Vocabulary",
    "Cloud",
    "Help",
]
```

### Step 5 — Add the Custom Commands settings page

This is the largest addition. The page renders a list of existing commands (trigger phrase, action type, target), an Add button, a Delete button, and an explanatory footer. The full implementation is in `_open_settings()` inside the `show_page()` dispatch block, keyed on `"Custom Commands"`. Copy the entire `elif page == "Custom Commands":` block from `src/jarvis_dictation.py` around line 4075–4210.

The key patterns used:
- `load_custom_commands()` to populate the list on page load
- `save_custom_commands(cmds)` called immediately on add/delete (auto-save, no Save button needed)
- Action dropdown: `["open_url", "open_app", "type_text"]`
- Trigger phrases require at least 2 words (enforced at match time)

---

## Change 5 — Spotify/URI Auto-Prefix Fix

**Why:** The Custom Commands UI automatically prepended `https://` to any URL that didn't start with `http://` or `https://`. This corrupted `spotify:playlist:...` URIs, converting them to `https://spotify:playlist:...` which macOS cannot open.

In `_add_command()` (inside the Custom Commands settings page), find:

**Before:**
```python
if action == "open_url" and not target.startswith(("http://", "https://")):
    target = "https://" + target
```

**After:**
```python
if action == "open_url" and not target.startswith(("http://", "https://", "spotify:", "music:", "mailto:")):
    target = "https://" + target
```

This preserves correct behavior for plain domains (`mysite.com` → `https://mysite.com`) while leaving Spotify URIs, Apple Music URIs, and mailto links untouched.

---

## Change 6 — Settings Window Height

**Why:** The Save button was clipped on the first page of Settings on some screen configurations.

In `_open_settings()`, find:

**Before:**
```python
W, H = 700, 620
```

**After:**
```python
W, H = 700, 680
```

---

## Intel Build Instructions

After applying all patches above:

```bash
# 1. Activate the Intel conda env (x86_64 Python 3.11)
conda activate dictation

# 2. Confirm environment
python -c "import platform; print(platform.machine())"
# must print: x86_64

# 3. Verify symspellpy fix
python - <<'EOF'
import os, symspellpy as p
d = os.path.join(os.path.dirname(p.__file__), "frequency_dictionary_en_82_765.txt")
print("SymSpell dict exists:", os.path.exists(d))
EOF

# 4. Clean any previous build artifacts
rm -rf packaging/mac/dist packaging/mac/build

# 5. Build
cd packaging/mac
pyinstaller --clean JarvisDictation.spec

# 6. Package for distribution (use ditto, NOT zip — preserves .app metadata)
cd dist
ditto -c -k --sequesterRsrc --keepParent "Jarvis Dictation.app" "JarvisDictation-intel.zip"
```

---

## Verification Checklist

After installing the new Intel build:

- [ ] Open Settings from the status bar icon
- [ ] Close Settings
- [ ] Dictate something — app must NOT crash (this was the v6.1.23 regression)
- [ ] Dictate "recieve" — SymSpell should correct it to "receive"
- [ ] Open Settings → Custom Commands page — must render without error
- [ ] Add a command: trigger "open my website", action open_url, target "https://example.com"
- [ ] Close Settings, say "open my website" — browser must open example.com
- [ ] Add a command with a `spotify:playlist:...` target — verify it saves without `https://` prepended
- [ ] Open Settings → confirm window is tall enough to show Save buttons without clipping

---

## If Crashes Continue After These Fixes

Intel-specific crash types and their causes:

| Signal | Cause | Where to look |
|--------|-------|---------------|
| `SIGABRT` / `dispatch_assert_queue_fail` | TSM called from background thread | `_run_on_main()` not applied to a pynput call |
| `SIGILL` | Intel MKL thread pool conflicts with Python GIL | Check `OMP_NUM_THREADS=1` is set before imports; check ONNX `inter_op_num_threads=1` |
| `EXC_BAD_ACCESS` | Memory corruption | Different root cause — check crash log |

Crash logs: `~/Library/Logs/DiagnosticReports/JarvisDictation-*.ips`

The existing Intel mitigations in the code (Caps Lock guard, single-threaded ONNX, `OMP_NUM_THREADS=1`) are still in place and must not be removed.
