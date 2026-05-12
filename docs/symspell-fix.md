# SymSpell Spell Correction — Bug Report & Fix

**Affected versions:** All builds prior to v6.1.24-stable  
**Fixed in:** v6.1.24-stable (commit `9da30df`)  
**File changed:** `src/jarvis_dictation.py`

---

## What SymSpell Does

SymSpell runs on Whisper's raw transcription output **before** the text is pasted into the active app. It is not real-time keyboard correction — it only applies to dictated speech. The pipeline is:

```
Whisper output → symspell_correct() → apply_snippets() → smart_punctuate() → paste_text()
```

It corrects single-word errors up to edit distance 2 (e.g. "recieve" → "receive", "tommorow" → "tomorrow"). It preserves capitalisation and trailing punctuation.

---

## The Bug

### Symptom
SymSpell was silently disabled in every packaged `.app` build. The `USE_SYMSPELL` flag was always `False` at runtime, so `symspell_correct()` returned text unchanged — no error, no log message.

### Root Cause
The dictionary path was hardcoded to the developer's local conda environment:

```python
# BROKEN — line ~997 in src/jarvis_dictation.py (pre-fix)
_DICT = os.path.expanduser(
    "~/miniconda3/lib/python3.11/site-packages/symspellpy/frequency_dictionary_en_82_765.txt"
)
```

This path only exists on the build machine. In the packaged `.app`, PyInstaller bundles the symspellpy data files at:

```
Jarvis Dictation.app/Contents/Resources/symspellpy/frequency_dictionary_en_82_765.txt
```

`os.path.exists()` returned `False` for the hardcoded path, so `load_dictionary()` was never called and `USE_SYMSPELL` remained `False`.

### How to Confirm the Bug in Any Build
Run this inside the `.app`'s Python or check at startup:

```bash
# Check whether the dict file exists at the hardcoded path
ls ~/miniconda3/lib/python3.11/site-packages/symspellpy/frequency_dictionary_en_82_765.txt

# Check where it actually lives in the bundle
find "/Applications/Jarvis Dictation.app" -name "frequency_dictionary*"
```

On any machine that is not the original build machine, the first command returns nothing. The second shows the correct bundled location.

---

## The Fix

Replace the hardcoded path with one derived from `symspellpy.__file__`. PyInstaller sets `__file__` correctly for all bundled packages, so this works in both the conda dev environment and the packaged `.app` without any changes.

### Before (broken)

```python
# src/jarvis_dictation.py  ~line 993
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

### After (fixed)

```python
# src/jarvis_dictation.py  ~line 993
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

**Why this works:** `os.path.dirname(symspellpy.__file__)` resolves to the directory containing the installed package — whether that is the conda env's site-packages or PyInstaller's `sys._MEIPASS`-rooted bundle. The dictionary file ships inside the symspellpy package, so it is always in the same directory as `__file__`.

---

## Applying This Fix to an Intel Build

The fix is identical for x86_64. Steps:

1. Open `src/jarvis_dictation.py` in the Intel repo checkout.
2. Find the SymSpell block (search for `USE_SYMSPELL`).
3. Apply the diff above — add the `import symspellpy as _symspellpy_pkg` line and replace the `_DICT = ...` line.
4. Verify the Intel conda env has symspellpy installed:
   ```bash
   conda activate dictation   # or whatever the Intel env is named
   pip show symspellpy
   ```
5. Quick sanity test before rebuilding:
   ```bash
   python - <<'EOF'
   import os, symspellpy as p
   d = os.path.join(os.path.dirname(p.__file__), "frequency_dictionary_en_82_765.txt")
   print("EXISTS:", os.path.exists(d))
   print("PATH  :", d)
   EOF
   ```
   Both lines should show `True` and a valid path.
6. Rebuild with `packaging/mac/build_mac_app.sh` (or the Intel equivalent build script).

---

## `symspell_correct()` — How It Works

Located at `src/jarvis_dictation.py` ~line 1030.

```python
def symspell_correct(text):
    if not USE_SYMSPELL: return text          # silently skipped if dict failed to load
    words = text.split()
    corrected = []
    for word in words:
        # Split trailing punctuation off before lookup
        m = re.match(r"([a-zA-Z']+)([.,!?;:]*)$", word)
        if m:
            core, punct = m.group(1), m.group(2)
            suggestions = _sym.lookup(core.lower(), Verbosity.CLOSEST, max_edit_distance=2)
            if suggestions:
                s = suggestions[0].term
                if core[0].isupper(): s = s.capitalize()  # preserve capitalisation
                corrected.append(s + punct)
            else:
                corrected.append(word)        # no suggestion — keep original
        else:
            corrected.append(word)            # numbers, symbols etc — keep original
    return " ".join(corrected)
```

**Key behaviours:**
- Max edit distance 2: catches most single-word transcription errors
- Does not correct proper nouns or words not in the English frequency dictionary
- Words that are already valid English words will not be changed even if a closer match exists (e.g. "meting" stays "meting" because it is a real word)
- Numbers, symbols, and mixed alphanumeric tokens are passed through unchanged
- Called at two points in the pipeline: `transcribe_and_type()` (~line 1798) and the wake-word transcription path (~line 1970)

---

## Where SymSpell Fits in the Full Pipeline

```
transcribe_and_type(wav_path, raw_frames)
    │
    ├─ whisper.transcribe()        → raw_text (Whisper output)
    ├─ ollama_query()              → optional LLM refinement
    ├─ symspell_correct(raw_text)  → fixes transcription typos   ← THIS LAYER
    ├─ apply_snippets()            → expands voice shortcuts
    ├─ smart_punctuate()           → capitalisation / punctuation cleanup
    └─ paste_text()                → writes to active app
```

---

## Related Fix in the Same Commit

The same commit (`9da30df`) also fixed a crash where pynput's `Controller` called `TSMGetInputSourceProperty` (a macOS Text Services Manager API requiring the main thread) from a background worker thread. This caused the app to crash on transcription when launched by double-click but not from the terminal. See the `_run_on_main()` helper added at `src/jarvis_dictation.py` ~line 495 for details.
