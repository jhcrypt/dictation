# Wake Word Bug Handoff — Cryptic Dictation App

## Status
Wake word ("Hey Jarvis") works perfectly from terminal but fails silently inside the built `.app` bundle.

## What Works
- Dictation (hold Right Command) ✅
- HUD display and app icons ✅
- Menu bar icon ✅
- Jarvis voice commands (open app, search, volume, etc.) ✅
- Wake word from terminal: score 0.96, triggers reliably ✅

## What Fails
- Wake word inside the built `.app` — no trigger, no error, just silence

## Root Cause Investigation

### Confirmed Facts
1. **Model file exists in bundle** at:
   `Dictation.app/Contents/Resources/openwakeword/resources/models/hey_jarvis_v0.1.onnx`

2. **`_MEIPASS` points to** `Contents/Frameworks` (not Resources)

3. **Original bug (fixed):** Model was loaded as `"hey_jarvis"` but the actual key and filename is `"hey_jarvis_v0.1"`. This was causing zero scores.

4. **Second bug (fixed):** Wake loop was opening a second `sd.InputStream` on device 2 while the main recording stream was already open on the same device at 48kHz. macOS silently returns garbage/zero audio when two streams share a device at the same sample rate. Fixed by reading from shared `wake_frames` buffer that `audio_callback` fills.

5. **Resampling tested:** `np.interp` from 48kHz→16kHz produces near-zero scores (0.007 max). `scipy.signal.resample_poly` also near-zero. Recording directly at 16kHz in isolation works (scores up to 0.99).

6. **Two-stream test:** Opening main stream at 48kHz + wake stream at 16kHz simultaneously also returned zero scores, even though macOS technically allows different sample rates on the same device.

7. **Current implementation:** Wake loop reads from `wake_frames` buffer (filled by `audio_callback` at 48kHz), resamples to 16kHz, feeds to openwakeword. Works in terminal, fails in bundle.

## Current Code State (`dictate_v2.py`)

### `audio_callback` (correct, unchanged):
```python
def audio_callback(indata, frames, time_info, status):
    if recording:
        audio_frames.append(indata.copy())
    elif WAKE_ENABLED and not recording and not cancelled:
        with wake_lock:
            wake_frames.append(indata.copy())
```

### `_wake_word_loop` (current version):
- Loads model using multi-candidate path resolution (tries `_MEIPASS/../Resources/...`, `_MEIPASS/openwakeword/...`, `sys.executable/../Resources/...`)
- Drains `wake_frames` buffer every 20ms
- Resamples 48kHz→16kHz via `np.interp`
- Feeds 1280-sample int16 chunks to `oww.predict()`
- Looks for key containing `"hey_jarvis"` in predictions
- Threshold: 0.75

### Model path resolution code:
```python
candidates = [
    os.path.normpath(os.path.join(bundle_dir, '..', 'Resources',
        'openwakeword', 'resources', 'models', 'hey_jarvis_v0.1.onnx')),
    os.path.normpath(os.path.join(bundle_dir,
        'openwakeword', 'resources', 'models', 'hey_jarvis_v0.1.onnx')),
    os.path.normpath(os.path.join(os.path.dirname(sys.executable),
        '..', 'Resources', 'openwakeword', 'resources', 'models', 'hey_jarvis_v0.1.onnx')),
]
model_path = next((p for p in candidates if os.path.exists(p)), "hey_jarvis_v0.1")
print(f"[wake] model path: {model_path} (exists={os.path.exists(model_path)})")
```

## Hypotheses Not Yet Confirmed

1. **Path resolves correctly but bundle hasn't been rebuilt yet with latest code** — the `exists=True/False` log line has not been seen in bundle output yet. Confirm by checking `~/dictation_crash.log` or redirecting app output.

2. **onnxruntime inside bundle is a different version** than conda env and doesn't support the embedding model. The exit error shows: `GetElementType is not implemented` in `ReorderOutput node` — this is an onnxruntime compatibility issue with the ONNX model format. This may silently cause zero scores without raising an exception during normal operation.

3. **openwakeword inside bundle fails to initialise the mel spectrogram preprocessor** because it can't find `melspectrogram.onnx` or `embedding_model.onnx` at runtime (these are also in Resources, not Frameworks).

## Most Likely Fix

The onnxruntime version bundled by PyInstaller may be incompatible with the openwakeword ONNX models. The error at exit:
```
[E:onnxruntime] Non-zero status code returned while running ReorderOutput node.
GetElementType is not implemented
```
suggests the bundled onnxruntime can't run the embedding model that openwakeword uses for feature extraction — meaning every `oww.predict()` call silently returns zero scores.

**Suggested next steps:**
1. Add a try/except around `oww.predict()` in the bundle with explicit logging of any exception
2. Check if `melspectrogram.onnx` and `embedding_model.onnx` are accessible at the path openwakeword expects inside the bundle
3. Pin onnxruntime to a specific version compatible with openwakeword's models: `pip install onnxruntime==1.16.3`
4. Consider using openwakeword's `tflite` backend instead of `onnx` — the `.tflite` model file is also bundled and may not have the same onnxruntime dependency

## Environment
- Machine: Intel Mac (x86_64), macOS 15.7.5
- Python: 3.11.14 (conda env: `dictation`)
- PyInstaller: 6.20.0
- Run from source: `conda activate dictation && python dictate_v2.py`
- Build: `pyinstaller --clean Dictation.spec`
- Project: `~/Desktop/dictation/`

## Key Files
- `~/Desktop/dictation/dictate_v2.py` — main app
- `~/Desktop/dictation/Dictation.spec` — PyInstaller build spec
- `~/Desktop/dictation/entitlements.plist` — macOS entitlements
- `~/dictation_crash.log` — crash log written on unhandled exception
- `~/.dictation_settings.json` — user settings
- `~/.cache/huggingface/hub/` — Whisper model cache
