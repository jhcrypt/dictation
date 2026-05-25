# Jarvis Tauri — Bug Fix Handoff

Last updated: 2026-05-25  
Session engineer: Claude (Anthropic)

---

## 🚀 Current Build Status

| Item | Detail |
|---|---|
| **Branch** | `master` |
| **Latest commit** | `b0ec4d0` — Remove unused spawn_sidecar import |
| **GitHub** | Pushed — `https://github.com/jhcrypt/dictation` |
| **Release build** | ✅ Clean (`npm run tauri build -- --no-bundle`, 2026-05-25) |
| **Packaged QA** | ✅ All 9 items passed from clean ZIP unzip (2026-05-25) |
| **Distribution ZIP** | `~/Desktop/Jarvis-Dictation-Tauri-v2.zip` — 97MB, self-contained |
| **Transcription default** | Local Whisper (`transcription_engine = "local"`) |
| **Cloud Phase 1** | ✅ Merged — OpenAI Whisper API via Keychain key |
| **Inline punctuation** | ⚠️ Deferred — built but disabled in pipeline |
| **App bundle** | `src-tauri/target/release/bundle/macos/Jarvis Dictation Tauri.app` |

### ⚠️ Critical build rule — NEVER use `cargo build --release` for distribution
Running `cargo build --release` directly sets `cargo:rustc-cfg=dev` via Tauri's build system.
This makes the webview load from `devUrl = "http://localhost:5173"` at runtime — blank window.
Always use: **`npm run tauri build -- --no-bundle`** for release binaries.

### Packaged-app QA items confirmed passing (2026-05-25, from clean ZIP unzip)
- ✅ App window opens (full UI, not blank)
- ✅ App icon appears in Dock
- ✅ Engine Status — sidecar connects
- ✅ Local dictation
- ✅ Clipboard preservation
- ✅ Wake word
- ✅ Custom commands page
- ✅ Cloud (AI Cleanup) page
- ✅ App quits cleanly

### Sidecar packaging
- Frozen PyInstaller binary (`jarvis-sidecar/jarvis-sidecar` + `_internal/`) bundled inside .app
- No Python or conda required on tester machines
- Whisper model weights still download on first dictation (~74MB tiny / ~464MB small.en)
- Rebuild sidecar: `cd sidecar && pyinstaller jarvis_sidecar.spec` then copy `dist/jarvis-sidecar/` into bundle

---

## ✅ Manual QA Results — Confirmed Fixed

| Blocker | Status | Confirmed |
|---|---|---|
| R1 — Jarvis long dictation cut-off | **FIXED** | ✅ Manual QA passed 2026-05-25 |
| R2 — Clipboard paste/preservation | **FIXED** | ✅ Manual QA passed 2026-05-25 |
| R3 — Custom commands | **FIXED** | ✅ Manual QA passed 2026-05-25 |
| R4 — Email body in To field | **FIXED** | ✅ Manual QA passed 2026-05-25 |
| R5 — Cleanup inventing words/commentary | **FIXED** | ✅ Manual QA passed 2026-05-25 |
| R8 — Inline punctuation | **DEFERRED** | ❌ Function built, disabled in pipeline |

---

## ⚠️ Explicit Product Decisions — Do NOT revert to Python reference

The Python reference (`/Users/user1/dictation/src/jarvis_dictation.py`) is the default source of truth,
**except** where an explicit Quill product decision overrides it. These override points are:

| Behavior | Python reference | Quill product decision |
|---|---|---|
| **Clipboard after paste** | Leaves dictated text on clipboard (`_should_restore = False`) | **Restores previous clipboard** after paste — user's clipboard is preserved |

**Clipboard restore rule (never revert):**
```
pbcopy(dictated_text) → Cmd+V → sleep(600 ms) → pbcopy(prev_clipboard)
```
The 600 ms wait is mandatory — slow apps (Notion, Slack, Electron, browsers) read the clipboard
asynchronously. Without the wait, the old clipboard overwrites the dictated text before the app reads it,
causing the old clipboard text to appear after (or instead of) the dictation.

---

## Architecture Quick Reference

| Layer | File | Notes |
|---|---|---|
| Rust backend | `src-tauri/src/commands.rs` | Tauri commands; serializes all sidecar calls through `Arc<Mutex<Option<SidecarProcess>>>` |
| Wake-word poll | `src-tauri/src/wake.rs` | Background thread; polls sidecar `get_wake_status` every 300 ms |
| Python sidecar | `sidecar/jarvis_sidecar.py` | Single-threaded stdin/stdout protocol; all recording, VAD, transcription, AI cleanup |
| React controller | `src/hooks/useGlobalHotkey.ts` | **ONE recording controller** — all triggers route through here; owns state machine |
| HUD window | `src/HudApp.tsx` | Separate Tauri webview (label="hud"); does NOT run `useGlobalHotkey` |

**Critical rule:** Nothing outside `useGlobalHotkey.ts` may call `sidecar_start_recording`, `sidecar_stop_recording`, `sidecar_cancel_recording`, or `sidecar_transcribe_last`.

---

## Issue 1 — Broken Pipe (os error 32) / Sidecar Crash

### Symptom
Dictation stopped entirely. Console showed `Broken pipe (os error 32)` from Rust trying to write to a dead sidecar process's stdin.

### Root Cause
The Python sidecar process exited (crash, OOM, etc.). Rust continued polling and writing to the now-closed stdin pipe.

### Fix
**`src-tauri/src/commands.rs`** — Added `try_restart_on_broken_pipe()` helper. Every sidecar command (`sidecar_start_recording`, `sidecar_stop_recording`, `sidecar_cancel_recording`, `sidecar_get_status`, `sidecar_transcribe_last`) now detects broken-pipe error codes and automatically kills the dead process, spawns a fresh sidecar, and returns the error so the caller can retry.

```rust
fn try_restart_on_broken_pipe(guard: &mut Option<SidecarProcess>, err_msg: &str) -> bool {
    let is_dead = err_msg.contains("Broken pipe")
        || err_msg.contains("os error 32")
        || err_msg.contains("os error 9")
        || err_msg.contains("failed to fill whole buffer");
    if !is_dead { return false; }
    if let Some(mut p) = guard.take() { p.kill(); }
    match crate::sidecar::start_sidecar_process() {
        Ok(new_proc) => { *guard = Some(new_proc); }
        Err(e) => { eprintln!("[sidecar] auto-restart FAILED: {}", e); }
    }
    true
}
```

**`src-tauri/src/wake.rs`** — Wake-poll thread does the same: on broken pipe, kills dead sidecar, spawns fresh one, waits 2.5 s for import phase, then sends `start_wake_listen` to restore wake detection.

**`sidecar/jarvis_sidecar.py` — `main()`** — Wrapped `sys.stdout.write` in try/except BrokenPipeError so the sidecar exits cleanly rather than crashing with a traceback when Rust closes the read end.

### Key Borrow-Checker Note (Rust)
You cannot call `try_restart_on_broken_pipe(&mut guard, &msg)` inside a closure that also holds a borrow of `guard.as_mut()`. Always use the explicit two-match pattern:

```rust
let proc_result = match guard.as_mut() {
    None       => return Err("Sidecar not running".to_string()),
    Some(proc) => proc.send("command").map_err(|e| e.to_string()),
};
// proc borrow ends here — safe to mutate guard
match proc_result {
    Err(msg) => { try_restart_on_broken_pipe(&mut guard, &msg); Err(msg) }
    Ok(v)    => Ok(v.to_string()),
}
```

---

## Issue 2 — VAD Cutting Off Speech After ~5 Seconds

### Symptom
While still talking continuously, Jarvis would stop recording at approximately the 5-second mark as if it detected silence.

### Root Cause
Voice Activity Detection uses: `voice_active = rms > max(_noise_floor * 2.5, 0.012)`

The noise floor has bidirectional adaptation:
- When silent: `_noise_floor = _noise_floor * 0.98 + rms * 0.02` (adapts down)
- When speaking: `_noise_floor = _noise_floor * 0.995 + rms * 0.005` (was adapting up, capped at `rms * 0.8`)

The `rms * 0.8` cap was the bug. With speech RMS ≈ 0.06:
- Cap = 0.048 → noise floor could drift to 0.048
- Threshold = 0.048 × 2.5 = **0.12**
- User's own voice (0.06) < 0.12 → flagged as silence

After ~5 seconds of continuous talking, the floor drifted high enough to make the threshold exceed the user's voice level.

### Fix
**`sidecar/jarvis_sidecar.py`** — Changed the upward adaptation cap from `rms * 0.8` to a hard ceiling of `0.016`:

```python
elif _noise_floor < 0.016:
    # Hard cap: threshold max = 0.016 × 2.5 = 0.040
    # Typical speech RMS is 0.04–0.10, so threshold stays well below speech.
    _noise_floor = _noise_floor * 0.995 + rms * 0.005
```

`0.016 × 2.5 = 0.040` threshold — safely below typical speech (0.04–0.10 RMS). The floor can no longer rise into speech territory during continuous talking.

---

## Issue 3 — "Skipped: auto_short (8 words < 10)" HUD Notification

### Symptom
After short dictations, a "✓ Skipped: auto_short (8 words < 10)" notification appeared in the HUD. Confusing and noisy — exposed internal Python state strings to the user.

### Root Cause
`useGlobalHotkey.ts` had a block that emitted a "skipped" HUD state when `result.skipped_cleanup && result.skip_reason`. The `_skippedLabel()` formatter had a fallback `return \`Skipped: ${reason}\`` which passed raw Python enum names through verbatim.

### Fix
**`src/hooks/useGlobalHotkey.ts`** — Removed the entire "skipped" HUD notification block. A skipped cleanup means the text was still pasted correctly — the user doesn't need to know cleanup was bypassed. No user-visible notification for skipped states.

---

## Issue 4 — RMS Poller Handler Accumulation

### Symptom
(Discovered during debugging) RMS level meter could lag or misbehave; potential for stacked async handlers.

### Root Cause
The RMS poller `setInterval` had a 1000 ms JS `setTimeout` wrapping the `invoke` call. If a handler took longer than 30 ms (the poll interval), multiple handlers would be in-flight simultaneously.

### Fix
**`src/hooks/useGlobalHotkey.ts`** — Removed the JS timeout wrapper. Added `rmsGuard` boolean flag (not a ref — intentionally module-scoped so it survives re-renders) that returns early if a previous handler is still running:

```js
if (rmsGuard) return;
rmsGuard = true;
try { /* invoke sidecar_get_status */ }
finally { rmsGuard = false; }
```

---

## Issue 5 — Duplicate `_resume_wake_stream` Threads / Multiple Stop Commands

### Symptom
Sending multiple `stop_recording` or `cancel_recording` commands in quick succession caused 6 concurrent `_resume_wake_stream` threads, all trying to open a new PortAudio InputStream. This produced a PortAudio crash and a broken-pipe cascade.

### Root Cause
`cmd_stop_recording` and `cmd_cancel_recording` both unconditionally spawned a `_resume_wake_stream` thread whenever `_wake_listening` was True, even if `_stream` was already None (i.e., already stopped). Six stop commands → 6 threads → 6 simultaneous `sounddevice.InputStream()` calls → crash.

### Fix
**`sidecar/jarvis_sidecar.py`**

1. `cmd_stop_recording` and `cmd_cancel_recording`: capture `stream_was_open = _stream is not None` before teardown; only spawn resume thread if `stream_was_open`.

2. `_resume_wake_stream`: added early-return guard at the top:
```python
if _wake_stream is not None:
    return  # Another thread already reopened the stream
```

---

## Issue 6 — Duplicate Dictations (Every Dictation Pasted Twice or More)

### Symptom
Every dictation appeared twice (or three times). Example:
```
Why is my dictation coming out like this? Why is my dictation coming out like this?
path = Path('/mnt/data/...') path = Path('/mnt/data/...')
```

### Root Cause — Two Contributing Factors

**A) Whisper 2× hallucination not caught by dedup**  
`_deduplicate_whisper()` Pass 1 (word-window) required `repeats >= 3` for all window sizes. Whisper's typical repetition hallucination is exactly 2×. For multi-word chunks the dedup never fired.

**B) JS-level double trigger / second paste not blocked**  
No guard existed in `useGlobalHotkey.ts` to prevent the same text from being pasted twice in rapid succession from any source (double wake event, two apps running simultaneously, etc.).

### Fix

**`sidecar/jarvis_sidecar.py` — `_deduplicate_whisper()`**: Changed threshold to require only 2 repeats for windows of 3+ words:

```python
threshold = 3 if window < 3 else 2
if repeats >= threshold:
    _log(f"[dedup] hallucination collapsed: {len(words)} words → {window} (threshold={threshold})")
    return " ".join(chunk)
```

Single/double-word windows still require 3 repeats (avoids collapsing short legitimately repeated words like "testing testing testing").

**`src/hooks/useGlobalHotkey.ts` — `lastPasteRef` guard**: Added before every `paste_text` call:

```ts
const lastPasteRef = useRef<{ text: string; time: number } | null>(null);

// Before paste:
const prev = lastPasteRef.current;
if (prev && prev.text === textToPaste && Date.now() - prev.time < 5_000) {
    console.warn("[paste] duplicate suppressed — same text within 5 s");
    stateRef.current = "idle";
    hudEmit({ state: "idle" });
    return;
}
lastPasteRef.current = { text: textToPaste, time: Date.now() };
```

5-second window: wide enough to catch back-to-back duplicates, short enough not to block legitimate repetition (e.g., dictating the same word again minutes later).

---

## Issue 7 — AI Cleanup Adding Commentary to Dictation Output

### Symptom
After dictation, extra text appeared: "(No correction needed as it is grammatically correct but illogical.)"

### Root Cause
The Ollama system prompt said "Return only the corrected dictation text" but was not explicit enough to prevent the LLM from appending explanatory annotations.

### Fix
**`sidecar/jarvis_sidecar.py` — `_OLLAMA_SYSTEM_PROMPT`**: Strengthened the instruction:

```python
"Return ONLY the corrected dictation text with no commentary, "
"no explanations, no annotations, no parenthetical remarks, "
"and no evaluation of whether changes were needed."
```

---

## Issue 8 — Inline Punctuation Commands ⚠️ UNRESOLVED / DEFERRED

### Status
**Inline punctuation is disabled in the live pipeline.** The call to `apply_inline_punctuation()` is commented out in `sidecar/jarvis_sidecar.py`. Standalone punct commands ("period" alone → ".") continue to work via `_cmd_detect` exact-match, which was never touched.

### What Was Built (Retained for Future Use)
`apply_inline_punctuation()` exists in `jarvis_sidecar.py` with a deterministic phrase-scan regex and is fully unit-tested (138 tests pass). It is NOT called from the pipeline.

### Why Deferred
Inline substitution is unreliable against real Whisper output. Whisper's punctuation insertion around command words (commas and periods before/after the phrase) varies by utterance, speed, and surrounding words. Each regex patch fixed one failure mode while surfacing another. Unit tests pass on controlled strings but cannot guarantee correct behavior on real dictation.

### Python Reference Audit Result
`PUNCT_COMMANDS` in `jarvis_dictation.py` is **exact-match standalone only** — `if lower in PUNCT_COMMANDS`. The Python app has **zero inline punctuation substitution code**. "Hello, period." in Python falls through to Ollama, which may implicitly convert it. Inline substitution was never a proven Python-reference feature.

### Resumption Path
When revisiting, options in priority order:
1. Port a proven Python behavior if one is found (e.g. a later Python version that adds explicit inline handling)
2. Implement a full tokenizer-based pass (split on whitespace+punct, scan phrase spans, rebuild) rather than regex
3. Let Ollama handle it — it already instructs `"Fix obvious speech-to-text errors, punctuation"` and may convert spoken punct words naturally

### Protected Invariants
- Do NOT re-enable the pipeline call without a robust solution that survives real Whisper output
- Do NOT remove `apply_inline_punctuation()` from the file — it is tested and ready for future wiring
- Standalone punct commands work via `_cmd_detect` and are unaffected by this deferral

---

## Cloud Phase 1 — `feature/cloud-transcription` (2026-05-25)

### Status
✅ **Merged into master and released.** All QA items passed. Smoke test confirmed 2026-05-25.

### QA checklist — all passed
- [x] Local mode — normal dictation works, timing card shows `· local`
- [x] Cloud mode — valid OpenAI key → timing shows `· cloud`, transcription correct
- [x] Bad key fallback — HUD warning appears, timing shows `· local (fallback)`, paste still works
- [x] Safe Mode — cloud configured but forced to local; timing shows `· local`
- [x] Settings file — `~/.dictation_settings.json` contains no `openai_key` field after saving
- [x] Regression — Wake word, clipboard preserve, Ollama cleanup, custom commands all still work

### API key migration behavior (intentional — document for future sessions)

**Old `openai_key` plaintext values are dropped, not auto-migrated to Keychain.**

| Event | Behavior |
|---|---|
| Settings load (Rust) | Old `openai_key` deserialized as `Option<String>`, held in memory only |
| Sidecar transcription | Reads key from macOS Keychain via `/usr/bin/security`; never reads settings field |
| Next settings save | `#[serde(skip_serializing_if = "Option::is_none")]` silently drops `openai_key` from JSON |
| After first save | `openai_key` is permanently absent from `~/.dictation_settings.json` |

**User action required:** Re-enter the API key once in Settings → Cloud → Save Key. This writes it to macOS Keychain (`JarvisDictation-OpenAI` / `openai_key`). Never written to disk again.

**Why no auto-migration:** Auto-migration would call `/usr/bin/security add-generic-password` during startup before the user consents — risking an unexpected Keychain permission dialog on first launch. Deliberate re-entry is a one-time action and is safer.

### Keychain details
- Service: `JarvisDictation-OpenAI`
- Account: `openai_key`
- Written via: `security add-generic-password -s … -a … -w <key> -U`
- Read via: `security find-generic-password -s … -a … -w` (sidecar subprocess at transcription time)
- Deleted via: `security delete-generic-password -s … -a …`

### Protected invariants for this branch
- Do NOT add more cloud providers (Deepgram, Groq, ElevenLabs, Claude, Gemini) until Phase 2 is scoped
- Do NOT store the API key anywhere except macOS Keychain
- Do NOT auto-migrate old plaintext keys without explicit user consent flow

---

## Files Changed This Session

| File | What Changed |
|---|---|
| `src-tauri/src/commands.rs` | `try_restart_on_broken_pipe()` added; all 5 sidecar commands use it; clipboard wait 150→600 ms |
| `src-tauri/src/wake.rs` | Wake-poll thread auto-restarts sidecar + restores wake listening on broken pipe |
| `sidecar/jarvis_sidecar.py` | VAD hard cap (Issue 2); duplicate wake-resume guard (Issue 5); `_deduplicate_whisper` threshold (Issue 6); Ollama prompt (Issue 7); main() BrokenPipeError handler (Issue 1); `apply_inline_punctuation()` built but **disabled/deferred** (Issue 8); custom command trigger normalization fix (Issue 9) |
| `src/hooks/useGlobalHotkey.ts` | Removed skipped HUD (Issue 3); rmsGuard (Issue 4); `lastPasteRef` duplicate guard (Issue 6); wake monitor rewrite to raw-RMS/100ms poll |
| `sidecar/test_sidecar_cmds.py` | **196 tests total**: `TestApplyInlinePunctuation` (40 — function tested but not in pipeline), `TestDeduplicateWhisper` (13), `TestCustomCommandPriority` (+7 new), `TestAlreadyWellFormed` (10), `TestIsRepetitive` (7), `TestOllamaSafetyFilter` (10), `TestStripOllamaPreamble` (8), `TestLooksLikeAssistantAnswer` (15), others |
| `ARCHITECTURE_AUDIT.md` | New — read-only architecture map, duplication inventory, release blockers |
| `HANDOFF.md` | New — this file |
| `BUG_FIX_TEMPLATE.md` | New — task template for future sessions |

---

## Issue 9 — Custom Command Trigger Normalization Mismatch

### Symptom
UI-created custom commands with apostrophes in the trigger (e.g. `"let's play chess"`) never matched in the Python sidecar, falling through to Ollama cleanup and then relying on the TypeScript fallback path to catch the command. Commands with clean triggers worked; commands typed naturally with contractions did not.

### Root Cause
`_cmd_detect` normalized raw Whisper speech with `re.sub(r'[^a-z0-9 ]', '', raw_text.lower())` — stripping all non-alphanumeric — but compared it against the stored trigger using only `.lower().strip()`, which preserved apostrophes, hyphens, and other special chars. So `"lets play chess"` (speech) never equalled `"let's play chess"` (stored trigger).

### Fix
**`sidecar/jarvis_sidecar.py`** — Apply the same `re.sub` to the stored trigger before comparing:
```python
_cc_trigger = re.sub(r'[^a-z0-9 ]', '', str(_cc.get("trigger", "")).lower()).strip()
```

### Tests Added (7 new, in `TestCustomCommandPriority`)
- `test_apostrophe_in_stored_trigger_matches_speech`
- `test_leading_whisper_comma_does_not_block_custom_match`
- `test_open_url_result_has_url_field`
- `test_open_app_result_has_app_name_field`
- `test_type_text_result_action_is_paste_text`
- `test_custom_command_result_has_hud_field`
- `test_missing_custom_commands_file_returns_no_match`

---

## Recurring Failure Patterns — Do Not Reintroduce

| Pattern | Why it breaks |
|---|---|
| Call `try_restart_on_broken_pipe` inside a closure that borrows `guard.as_mut()` | Rust borrow checker: proc borrow (from `as_mut()`) must be fully dropped before `&mut guard` can be taken again. Always use two separate `match` blocks. |
| Upward VAD adaptation cap as `rms * 0.8` | Lets noise floor rise into speech territory during continuous talking; threshold exceeds user's voice RMS after ~5 s |
| Spawning `_resume_wake_stream` without checking if stream was open | Multiple concurrent PortAudio opens crash the sidecar |
| Allowing multiple `stop_recording` commands to each spawn resume threads | Same as above — any path that triggers resume must guard on `stream_was_open` |
| Word-window dedup requiring `>= 3` for all window sizes | Misses Whisper's standard 2× repetition hallucination |
| Emitting raw Python internal strings to the HUD | Users see enum names like `auto_short`; always map to human-readable strings or suppress |
| AI cleanup prompt without explicit anti-annotation instruction | LLMs will add "(No correction needed…)" style comments; must forbid commentary explicitly |
| Inline punct regex trailing `\b` without consuming Whisper punctuation | Whisper's trailing comma/period not consumed; leaves `,?` or `,.` garbage in output |
| Comma-before-punct cleanup only matching `,` without `\s*` | After phrase sub, space exists between comma and symbol: "Hello, ." won't match `,([.!?])` |
| No double-comma collapse | Whisper comma + "comma" command → `,,` in output |
| Normalizing raw speech but not stored custom trigger | `re.sub` on speech text but only `.lower()` on stored trigger → apostrophes/hyphens in triggers never match |

---

## Protected Files — Never Modify

- `/Applications/Quill.app` — production stable app
- `/Applications/Jarvis Dictation.app` — production stable app  
- `/Users/user1/dictation/src/jarvis_dictation.py` — reference implementation (read-only)

Do NOT install the Tauri app to `/Applications`. The Tauri app lives in:  
`/Users/user1/jarvis-tauri/src-tauri/target/release/bundle/macos/Jarvis Dictation Tauri.app`

---

## Rebuild Procedure

After changing Python sidecar only:
> Quit and reopen Jarvis — sidecar is reloaded from disk automatically on next start.

After changing TypeScript/React:
```bash
cd /Users/user1/jarvis-tauri
npm run build
cargo build --release --manifest-path src-tauri/Cargo.toml
cp src-tauri/target/release/jarvis-dictation \
   "src-tauri/target/release/bundle/macos/Jarvis Dictation Tauri.app/Contents/MacOS/jarvis-dictation"
```
Then quit and reopen the `.app`.

After changing Rust only:
```bash
cargo build --release --manifest-path src-tauri/Cargo.toml
cp src-tauri/target/release/jarvis-dictation \
   "src-tauri/target/release/bundle/macos/Jarvis Dictation Tauri.app/Contents/MacOS/jarvis-dictation"
```
