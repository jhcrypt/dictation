# Jarvis Tauri — Architecture Audit
## Phase 1: Map duplication, do not edit yet

Generated: 2026-05-24
Status: Read-only. No code was changed to produce this document.

---

## 1. Git Status

### Uncommitted changes (4 modified files, 2 untracked)

| File | Status |
|---|---|
| `sidecar/jarvis_sidecar.py` | Modified — +101/-6 lines this session |
| `sidecar/test_sidecar_cmds.py` | Modified — +97 new tests |
| `src-tauri/src/commands.rs` | Modified — +20/-2 (clipboard wait 150→600 ms) |
| `src/hooks/useGlobalHotkey.ts` | Modified — +101/-44 (wake monitor rewrite, duplicate guard) |
| `BUG_FIX_TEMPLATE.md` | Untracked |
| `HANDOFF.md` | Untracked |

### Last 15 commits

```
2b6b37a Restore inline punctuation voice commands
081aade Remove "Skipped: auto_short" HUD notification after successful paste
b87ff79 Fix VAD upward adaptation that cut off speech after ~5 seconds
6663ee7 Fix broken pipe crash: auto-restart sidecar + prevent duplicate wake-resume threads
0148237 Fix waveform reactivity: push RMS from main window via Tauri events
4b45c31 Make waveform react to voice in real-time (eliminate React state from hot path)
1f7c8da Fix short-tap rejection and Whisper hallucination dedup
95bed5c Fix screenshot commands, wake auto-stop, and noisy-room VAD
87ed396 Parallel diagnostics: port 8 missing features from Python reference
51d8578 Fix email body formatting: capitalize, preserve period, auto-generate subject
c65f0bf Fix leading comma in email body + custom commands intercepted by built-ins
fe78624 Fix email body going to To field when no body marker is used
750e997 Fix three active regressions: leading-comma, custom commands, wake auto-stop
05943d1 Fix email recipient parsing and reduce stop-recording delay
31b32f3 Improve email draft body handling
```

---

## 2. Current Active Bugs (Confirmed from Code)

### B1 — Jarvis long dictation cut-off (UNCONFIRMED via manual QA)
- **Code fix in place:** Wake monitor now uses raw RMS vs absolute 0.025 threshold at 100 ms poll
- **Status:** Tests pass. Manual QA not yet confirmed by user.
- **Risk:** If `wake_dictation_silence_rms` setting reads 0 (unset), all RMS > 0 = never silent, so Jarvis never auto-stops. Default is 0.025 — check settings file.

### B2 — Clipboard paste regression (UNCONFIRMED via manual QA)
- **Code fix in place:** 600 ms wait before restoring clipboard (was 150 ms)
- **Status:** Tests pass. Manual QA not yet confirmed by user.

### B3 — Custom commands: dual matching paths may diverge
- **Python sidecar** `_cmd_detect` matches custom commands at transcription time (exact lowercase, multi-word only, skips single-word triggers)
- **TypeScript** `runCustomCommand` matches custom commands at routing time (uses `normalizeTrigger`: strips leading/trailing punct, apostrophes; allows single-word)
- **Both run on every dictation** — if sidecar matches first and returns `action=paste_text`, the TS custom command check is skipped. If sidecar does NOT match (e.g. because trigger is single-word), TS may still match.
- **Divergence risk:** normalization rules differ; a trigger that passes one may not pass the other.

### B4 — Email body in To field (recently fixed but no regression test)
- Email body goes to To field when user doesn't use a body marker ("saying"/"let them know"/etc.)
- The Python reference `_email_contact_split` function extracts body from raw_text; the sidecar port is in `sidecar/jarvis_sidecar.py:1181`.
- No automated test for the "email Val meeting tomorrow" (no body marker) case.

### B5 — Cleanup inventing words (monitored but not hardened)
- `ollama_result_is_safe()` guards against expansion but the "too many new words" check allows up to `max(6, len(orig_words))` new words — that is lenient for short dictations.
- No automated test that verifies the safety check rejects specific known-bad outputs.

### B6 — Inline punctuation (DEFERRED)
- `apply_inline_punctuation()` exists but is commented out of the pipeline.
- Standalone punct commands ("period" → ".") still work via `_cmd_detect` exact-match.

---

## 3. Recording Controller Paths

### Rule: Only `useGlobalHotkey.ts` may call sidecar recording commands.

**Verified callers of sidecar recording commands:**

| Command | Caller | Line | OK? |
|---|---|---|---|
| `sidecar_start_recording` | `useGlobalHotkey.ts` | 397 | ✅ |
| `sidecar_stop_recording` | `useGlobalHotkey.ts` | 637 | ✅ |
| `sidecar_cancel_recording` | `useGlobalHotkey.ts` | 440, 614, 1062, 1093 | ✅ |
| `sidecar_transcribe_last` | `useGlobalHotkey.ts` | 697 | ✅ |
| Rust `lib.rs` | Only registers commands via `invoke_handler` | 170–178 | ✅ |

**No violations found.** `HudApp.tsx` does NOT call any recording commands. The wake poll thread in `wake.rs` only calls `get_wake_status` and `start_wake_listen` — not recording commands.

---

## 4. Recording Start/Stop Paths

### Start path
```
User input (hotkey press / wake word detected)
  → useGlobalHotkey.ts startRecording(source)
    → invoke("sidecar_start_recording")          [Rust commands.rs:188]
      → Python sidecar cmd_start_recording()
    → startRmsPoller()                           [30 ms interval, sidecar_get_status]
    → if source === "wake": start wakeMonitorRef  [100 ms interval, auto-stop]
```

### Stop path (normal — hotkey release / wake auto-stop)
```
useGlobalHotkey.ts stopAndTranscribe()
  → clearWakeMonitor()
  → stopRmsPoller()
  → invoke("sidecar_stop_recording")             [Rust commands.rs:209]
  → invoke("sidecar_transcribe_last")            [Rust commands.rs:222 — runs Whisper]
  → classifyTranscribeResult(result)
  → dispatch: command | text paste | tap_ignored | error
```

### Cancel path (pendingStop / error)
```
useGlobalHotkey.ts (several locations)
  → invoke("sidecar_cancel_recording")           [Rust commands.rs:720]
```

### 90-second safety timeout
```
setTimeout(90_000) in startRecording
  → if still recording → stopAndTranscribe()
```

---

## 5. Wake / Jarvis Start-Stop Flow

### Wake detection (Rust thread)
```
src-tauri/src/wake.rs  start_wake_poll_thread()
  → polls Python sidecar "get_wake_status" every 300 ms
  → on wake detected: emits Tauri event "wake-word-detected"
  → on sidecar broken pipe: auto-restart sidecar + send "start_wake_listen"
```

### Wake detection (TypeScript)
```
useGlobalHotkey.ts
  → listen("wake-word-detected", ...) 
  → if jarvis_enabled && idle → startRecording(source="wake")
  → wakeMonitorRef setInterval(100 ms):
      → sidecar_get_status → rawRms vs silenceRmsThreshold (0.025)
      → after graceMs (3.5s default): track silence
      → after silenceMs (2.5s default) of silence → stopAndTranscribe()
      → after maxMs (45s default) → stopAndTranscribe()
```

### Wake silence detection — Python reference vs Tauri
| | Python `_silence_stop_monitor` | Tauri wake monitor |
|---|---|---|
| Poll interval | 100 ms (`sleep(0.1)`) | 100 ms (`setInterval(100)`) ✅ |
| Silence threshold | `rms < silence_rms` (0.025 absolute) | `rawRms < silenceRmsThreshold` (0.025) ✅ |
| Grace period | `wake_dictation_grace_seconds` | same setting ✅ |
| Max duration | `wake_dictation_max_seconds` | same setting ✅ |
| Silence window | `wake_dictation_silence_seconds` | same setting ✅ |

---

## 6. Paste / Clipboard Flow

### Path (Rust `commands.rs:480` — `paste_text`)
```
1. pbpaste → save prev_clipboard (raw bytes, preserves non-UTF-8)
2. Activate last non-Jarvis app (stored in LastTargetApp)
3. Write sentinel to clipboard, verify it is readable (loop 5×50ms)
4. pbcopy(dictated_text)
5. send_cmd_v() → CGEvent (Quartz) or osascript fallback
6. sleep(600 ms) — Quill product decision: wait for slow apps to read clipboard
7. pbcopy_raw(prev_clipboard) — restore previous clipboard
8. Return PasteTiming struct (substep timing in ms)
```

**Product override (never revert):** Python leaves dictated text on clipboard. Tauri always restores the previous clipboard. The 600 ms wait is mandatory — slow apps (Notion, Slack, Electron) read clipboard asynchronously.

### Duplicate-paste guard (TypeScript)
```
lastPasteRef = { text, time }
Before each paste:
  if same text AND within 5 s → suppress, go idle
  else → update ref, paste
```

---

## 7. Command Routing Flow

### Full pipeline for a transcription result
```
sidecar_transcribe_last returns JSON result
  → classifyTranscribeResult(result)  [commandRouting.ts — pure, tested]
      → "command":     result.action is non-empty string
      → "text":        result.text is non-empty after trim
      → "tap_ignored": ok=false + "no audio recorded", or text="" 
      → "error":       ok=false (other), or ok=true + no text + no action

  → if "command":
      dispatch on act:
        scratch / format_paste → send_backspaces
        paste_text / format_paste + text → paste_text Rust command
        keypress → send_keypress
        key_combo → send_key_combo
        copy_text → copy_to_clipboard_str
        copy_all → cmd+A, cmd+C
        navigate → emit nav-history / nav-vocabulary
        open_app → invoke open_app
        open_url → invoke open_url
        set_volume → set_system_volume
        create_reminder → create_reminder
        take_screenshot → trigger_shottr
        close_app → close_app
        snippet_* → HUD only
      → HUD: result.hud (1800 ms) or idle

  → if "text":
      if jarvis_enabled:
        runCustomCommand(trimmed)     [TS: load_custom_commands via Rust, normalizeTrigger]
        if no match: runCustomCommand(result.whisper_text)  [raw fallback]
        if matched + no pasteText → HUD inserted, idle
      textToPaste = custom.pasteText ?? trimmed
      duplicate-paste guard
      paste_text Rust command
      HUD: inserted (1500 ms)

  → if "tap_ignored":
      HUD: tap_ignored (2500 ms), idle

  → if "error":
      HUD: error (4500 ms), idle
```

### Duplicate custom command matching (⚠️ duplication)
Custom commands are checked in **two independent places**:

| Where | When | Normalization | Single-word triggers |
|---|---|---|---|
| Python `_cmd_detect` | At transcription time (inside sidecar) | `lower().strip()` only | Skipped (len < 2 words) |
| TypeScript `runCustomCommand` | After transcription (in TS hook) | `normalizeTrigger`: strips leading/trailing punct, apostrophes | Allowed |

**The Python path returns `action="paste_text"` / `action="open_url"` / etc. directly from the sidecar — the TS `runCustomCommand` is then never reached for that result because `classifyTranscribeResult` returns `"command"` not `"text"`.** The TS path only fires for results classified as `"text"` — i.e. when the sidecar did NOT match the trigger.

This means for a `type_text` custom command: if the Python sidecar matches (multi-word trigger), it returns `action=paste_text`; the TS detects command, pastes via command path. If only TS matches (e.g. trigger was changed to normalizeTrigger form but not in sidecar), it pastes via the text path — same visible result, different code path. **Divergence is possible but currently low-risk.**

---

## 8. Custom Command Loading / Matching Flow

### Storage
- File: `~/.dictation_custom_commands.json`
- Schema: `[{ trigger, action, target }]`
  - `action`: `"open_url"` | `"open_app"` | `"type_text"`
  - `target`: URL / app name / text to type

### Python sidecar (`_cmd_detect`)
```python
for _cc in _load_custom_commands():
    _cc_trigger = str(_cc.get("trigger", "")).lower().strip()
    if not _cc_trigger or len(_cc_trigger.split()) < 2:
        continue   # skip single-word triggers
    if lower == _cc_trigger:   # exact match (lower = normalized raw_text)
        return {"action": ..., ...}
```

### TypeScript (`runCustomCommand`)
```typescript
const cmds = await invoke("load_custom_commands");  // Rust reads same JSON file
const lower = normalizeTrigger(spokenText);
const match = cmds.find(cmd =>
  normalizeTrigger(cmd.trigger) === lower
);
// normalizeTrigger: trim, lowercase, strip leading/trailing punct, strip apostrophes
```

### Rust (`commands.rs:91` — `load_custom_commands`)
```rust
pub fn load_custom_commands() -> Vec<serde_json::Value> {
    data::load_custom_commands()  // reads ~/.dictation_custom_commands.json
}
```

**All three read the same JSON file. No caching inconsistency.**

---

## 9. Cleanup / Transcription Pipeline Order

### Full pipeline (per `sidecar/jarvis_sidecar.py`)

```
1. Whisper transcription
   - VAD filter (strip leading silence)
   - Strip hallucinated leading punctuation
   - _deduplicate_whisper() — collapse 2× repetition hallucinations (3+ word windows)
   → raw_text

2. Command detection
   - _cmd_detect(lower_cmd, raw_text, jarvis_enabled, active_app)
     → if matched: return command result immediately (skip cleanup)

3. Ollama AI cleanup (if ai_cleanup_mode not "off", not skipped)
   - Skip conditions: safe_mode, unavailable, short phrase (≤3 words), auto_short (≤10 words)
   - ollama_result_is_safe() validates output:
     * no empty result
     * no expansion of short dictations (≤6 words → output ≤ 3× original)
     * question must stay question
     * no assistant-style answer
     * new words ≤ max(6, len(orig_words))
     * output length ≤ max(2.2× original, original+80 chars)
   - If rejected: use raw_text unchanged

4. remove_disfluencies() — um, uh, you know, like
   (always runs regardless of Ollama)

5. Local correction pipeline:
   a. symspell_correct()           — English spell correction
   b. smart_punctuate()            — add trailing . or ?
   c. repair_mojibake()            — fix UTF-8 encoding artifacts
   d. apply_profile_aliases()      — multi-word → abbreviation
   e. _apply_ui_context_fix()      — "I"/"had" → "UI"/"HUD" in Developer profile
   f. _apply_hud_context_fix()
   g. apply_inline_linebreaks()    — "next line" → \n
   h. [apply_inline_punctuation]   — DISABLED/DEFERRED
   i. apply_corrections()          — user vocab corrections
   j. words_to_digits()            — "twenty three" → "23"
   k. format_for_app()             — app-context formatting (if active_app set)

6. Return result JSON
```

### Python reference pipeline (`jarvis_dictation.py`)
```
1. Whisper → raw_text
2. _ollama_result_is_safe → text (or raw_text if rejected)
3. Command detection (lower = re.sub non-alphanumeric, exact-match guards)
4. symspell_correct → apply_snippets → smart_punctuate → repair_mojibake
5. apply_profile_aliases
6. _apply_inline_linebreaks
7. apply_corrections
```

**Tauri additions vs Python reference:**
- `remove_disfluencies()` — in Tauri, not in Python reference (safe addition)
- `words_to_digits()` — in Tauri, not in Python reference (safe addition)
- `format_for_app()` — in Tauri, not in Python reference (safe addition)
- `_apply_ui_context_fix()` / `_apply_hud_context_fix()` — Tauri only (safe additions)

---

## 10. HUD State Path

### Two windows
- **Main window** (`useGlobalHotkey.ts`): runs the state machine, emits `hud-state` events
- **HUD window** (`HudApp.tsx`, label="hud"): listens only, never controls recording

### HUD state machine
```
idle
  → startRecording → "recording" or "wake_recording"
    → sidecar_start_recording OK → "recording" (confirmed)
    → wakeMonitorRef fires:
        silence detected → stopAndTranscribe() → "stopping"
        max duration → stopAndTranscribe() → "stopping"
    → stopAndTranscribe() → "stopping" → "transcribing"
      → result classified:
          command    → "command" (1800ms) → "idle"
          text       → "inserted" (1500ms) → "idle"
          tap_ignored→ "tap_ignored" (2500ms) → "idle"
          error      → "error" (4500ms) → "idle"
    → error in start → "error" (2000ms) → "idle"
```

### RMS / waveform path
```
Main window rmsPollerTimer (30 ms):
  → sidecar_get_status → recording_rms
  → emit("audio-rms", { level })

HudApp WaveformBars:
  → listen("audio-rms", event => { update bars })
```

---

## 11. Settings Read/Write Path

### Storage
- File: `~/.dictation_settings.json`
- Same file shared between Python app and Tauri app

### Read paths
| Layer | How |
|---|---|
| Python sidecar | `load_settings()` — disk read every call (no caching) |
| Rust `commands.rs` | `load_settings()` — disk read, returns `Settings` struct |
| TypeScript | React context `useSettings()` — reads via Rust `load_settings` command; cached in `settingsRef.current` |

### Write paths
| Layer | How |
|---|---|
| Rust `commands.rs` | `save_settings(settings)` |
| TypeScript | Writes via `invoke("save_settings", { settings })` |
| Python sidecar | **Does not write settings** — read-only consumer |

**Risk:** Python sidecar calls `load_settings()` fresh on every `cmd_transcribe_last`. If the user changes a setting mid-dictation (unlikely) the sidecar will pick it up immediately. No staleness issue but also no batching.

---

## 12. Duplicated Logic

### D1 — Custom command matching (HIGH — already noted)
- Checked independently in Python sidecar AND TypeScript
- Different normalization rules
- Same JSON file, same result, but two code paths that can diverge

### D2 — Clipboard timing constant
- `600` ms hardcoded in `src-tauri/src/commands.rs:543` inline in `paste_text()`
- Not extracted as a named constant
- If this needs to change, the value must be found by reading the code

### D3 — `invokeWithTimeout` defined inside `useEffect`
- `invokeWithTimeout` is a closure defined at line 221 inside `useGlobalHotkey`'s useEffect
- It cannot be unit-tested independently
- Every test of `useGlobalHotkey` requires a full React render

### D4 — Wake timing defaults duplicated
- Default values (grace=3.5s, silence=2.5s, max=45s, rms=0.025) appear in:
  - `useGlobalHotkey.ts` lines 474–479 (JS `?? 3.5`, `?? 2.5`, etc.)
  - Python sidecar reads from settings (no hardcoded defaults in Python, relies on settings file)
  - Not extracted as named constants in TS

### D5 — HUD timeout durations hardcoded
- `1800`, `2500`, `1500`, `4500` ms scattered across `useGlobalHotkey.ts`
- Not named constants — can diverge if one is updated but others are missed

### D6 — `cancel_recording` called in 4 places
- Lines 440, 614, 1062, 1093 in `useGlobalHotkey.ts`
- Same invocation pattern `invokeWithTimeout("sidecar_cancel_recording", undefined, 5_000)`
- Could be a `cancelRecording()` helper — but all 4 are valid distinct trigger points

### D7 — Result logging duplicated
- `console.log("[recording] outcome=..."` and `console.log("[cmd] dispatching..."` with similar fields
- Low risk, cosmetic

### D8 — `PasteTiming` type defined twice
- Inline type at line 879–883 in `useGlobalHotkey.ts` (inside the handler)
- Similar structure at lines 105–110 (top of file, for the perf timing emit)
- One is the Rust return type, one is the emitted diagnostic type — same shape, two definitions

---

## 13. What Is Safest to Refactor First (Phase 2)

### SAFE — extract, no behavior change
1. **Wake timing defaults** — extract `GRACE_MS_DEFAULT`, `SILENCE_MS_DEFAULT`, `MAX_MS_DEFAULT`, `SILENCE_RMS_DEFAULT` as top-level constants in `useGlobalHotkey.ts`
2. **HUD timeout durations** — extract `HUD_COMMAND_MS = 1800`, `HUD_TAP_MS = 2500`, `HUD_INSERT_MS = 1500`, `HUD_ERROR_MS = 4500`
3. **Clipboard restore delay** — extract `CLIPBOARD_RESTORE_DELAY_MS = 600` as a Rust constant in `commands.rs`
4. **`PasteTiming` type dedup** — merge the two inline definitions into one at file top

### SAFE — add tests, no code change
5. **Email recipient/body parser** — test `_email_contact_split` with "no body marker" case in Python tests
6. **Ollama safety rejection** — test that known-bad outputs (too long, assistant response) are rejected
7. **Custom command single-word skip** — test that Python sidecar skips single-word triggers

### MODERATE RISK — structural, needs careful review
8. **`invokeWithTimeout` extraction** — move out of `useEffect` closure to module level; requires dependency injection for `invoke`, tests become possible but refactor is non-trivial
9. **Custom command matching unification** — remove either the Python or TS path; Python path is more robust (runs before Ollama cleanup can mangle trigger text), TS path handles edge cases (apostrophes, Whisper leading punct) — see D1

---

## 14. What Should NOT Be Touched Yet

### DO NOT TOUCH
- `src-tauri/src/wake.rs` — wake poll thread; auto-restart logic is fragile (borrow-checker constraints documented in HANDOFF.md)
- `src-tauri/src/commands.rs` `paste_text()` — clipboard restore timing is a product decision, 600 ms is mandatory
- `sidecar/jarvis_sidecar.py` VAD section — `_noise_floor` adaptation cap (0.016) was a hard bug fix; the logic is counter-intuitive and easy to accidentally revert
- `useGlobalHotkey.ts` wake monitor — recently rewritten to use raw RMS; rewriting again before manual QA is confirmed would mask whether the fix worked
- `apply_inline_punctuation` — deferred; do not re-enable until a robust parser replaces the regex approach
- Anything in `/Applications/Quill.app`, `/Applications/Jarvis Dictation.app`, `/Users/user1/dictation/`

### DO NOT MERGE/REMOVE YET
- The dual custom command matching (D1) — removing one path risks regressions; add tests first (Phase 3), then decide which path to keep

---

## 15. Release Blockers (Priority Order)

| # | Blocker | Status | Location |
|---|---|---|---|
| R1 | Jarvis long dictation cut-off | Fix in code, **manual QA needed** | `useGlobalHotkey.ts` wake monitor |
| R2 | Clipboard duplicate/old-clipboard paste | Fix in code, **manual QA needed** | `commands.rs paste_text` |
| R3 | Custom commands must work | Working in both paths, **no regression test** | Sidecar `_cmd_detect` + TS `runCustomCommand` |
| R4 | Email body in To field | Fixed, **no regression test** | Sidecar `_email_contact_split` |
| R5 | Cleanup must not invent words | `ollama_result_is_safe` guards it, **no specific test** | Sidecar `ollama_result_is_safe` |

---

## Appendix — File Sizes and Scope

| File | Lines | Role |
|---|---|---|
| `sidecar/jarvis_sidecar.py` | 2,995 | All Python logic: VAD, Whisper, Ollama, commands, cleanup |
| `src/hooks/useGlobalHotkey.ts` | 1,211 | All recording control, dispatch, HUD, custom cmd matching |
| `src-tauri/src/commands.rs` | 1,275 | Rust bridge: paste, clipboard, app control, sidecar comm |
| `src-tauri/src/wake.rs` | ~80 | Rust wake poll thread |
| `src/hooks/commandRouting.ts` | 132 | Pure: result classification, trigger normalization |
| `src/__tests__/commandRouting.test.ts` | 284 | Tests for commandRouting.ts |
| `sidecar/test_sidecar_cmds.py` | ~1100 | 138 tests for Python sidecar functions |
