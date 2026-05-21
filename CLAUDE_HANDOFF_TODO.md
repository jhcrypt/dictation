# Quill Tauri Working To-Do / Claude Handoff List

_Last updated from ChatGPT planning session. Place this file in `/Users/user1/jarvis-tauri` for Claude/Codex to read before making changes._

---

## 1. Do-not-touch rules

- Do not touch `/Applications/Quill.app`.
- Do not touch `/Applications/Jarvis Dictation.app`.
- Do not touch `/Users/user1/dictation/src/jarvis_dictation.py` unless explicitly approved.
- Do not install the Tauri app to `/Applications` yet.
- Do not package or replace the stable Python app yet.
- Treat the stable Python app as the **behavioral source of truth**.
- Tauri should match Python behavior first, then improve later.
- Keep `wake_enabled=false` unless specifically testing Jarvis.

---

## 2. Current working wins

- Normal dictation works.
- Dictation button works.
- Global hotkeys work.
- Start/stop sounds work.
- Clipboard stale-paste bug was fixed.
- Dictated text no longer pastes old clipboard content on first dictation.
- Quartz Cmd+V paste is working.
- Terminal confirmed `[paste] cmd_v method=quartz`.
- Speed improved after removing artificial HUD/history delays.
- Settings opens, closes, and reopens.
- HUD notifications for settings/menu changes were added.
- Hotkey options are wired: Right Option, F13, F14, F15.
- Toggle mode is wired.
- Dictation button now uses the central recording controller.
- Add Correction from Last Dictation prefill was added.
- Tauri app shell is very small compared with Python build.

---

## 3. Recent important fixes / commits to verify

- `b605f6b` — Add native macOS start/stop recording sounds.
- `34b7dd1` — Fix dictation latency: paste first, HUD/history/timing async.
- `fa3dbea` — Fix stale clipboard: remove old clipboard restore behavior.
- `6dd7aa4` — Remove 30ms settle after pbcopy.
- Quartz Cmd+V optimization — verify exact commit hash if committed.

Before Claude changes anything, run:

```bash
cd /Users/user1/jarvis-tauri
git status --short
git log --oneline -12
npx tsc --noEmit
cd src-tauri && cargo check
```

---

## 4. Highest-priority bugs / parity issues

### 4.1 Jarvis wake-word parity

- Python Jarvis worked reliably and is heavily used.
- Tauri Jarvis is not yet reliable.
- Current Tauri behavior:
  - Wake Word can be enabled.
  - Jarvis page says “Listening.”
  - Sidecar CPU rises to about 10%.
  - Saying “Hey Jarvis” does not start recording.
  - Wake off drops sidecar CPU to 0%.
- Do not abandon Jarvis.
- Do not invent a new wake system.
- Compare the stable Python Jarvis implementation against the Tauri sidecar and port the proven behavior.

Claude should compare:

```text
/Users/user1/dictation/src/jarvis_dictation.py
/Users/user1/jarvis-tauri/sidecar/jarvis_sidecar.py
```

Focus areas:

- mic stream setup
- sample rate
- block size
- wake frame buffer
- openwakeword input format
- wake threshold
- detection flag
- wake loop sleep/backoff
- CPU behavior
- pause/resume during recording
- get_wake_status behavior
- Rust polling bridge
- React wake-detected listener

Do not add Jarvis commands until wake-word parity works.

---

### 4.2 Jarvis CPU optimization

Current measurement:

```text
wake_enabled=false → sidecar CPU 0.0%
wake_enabled=true  → sidecar CPU about 10%
```

Goal:

```text
Excellent: 1–3% CPU idle
Acceptable: 3–5% CPU idle
Current: too high
```

Possible causes:

- wake loop busy-spins
- openwakeword called too frequently
- audio chunks too small
- wake_frames queue unbounded
- wake listener running during transcription
- sidecar mutex/polling contention

Fix detection first, then optimize CPU.

---

### 4.3 Clipboard preservation regression

Current Tauri behavior:

- User copies text.
- User dictates.
- After dictation, Cmd+V pastes dictated text.

Expected Python behavior:

- User copies text.
- User dictates.
- User can still paste the originally copied text afterward.

This is a real workflow regression.

Claude should:

- Read Python clipboard behavior.
- Port the stable behavior.
- Do not reintroduce the broken delayed restore thread.
- Restore clipboard only after paste is fully complete and safe.

Acceptance test:

```text
1. Copy ORIGINAL COPIED TEXT.
2. Dictate “first dictation test.”
3. Quill pastes “first dictation test.”
4. Press Cmd+V manually.
5. It pastes ORIGINAL COPIED TEXT.
6. First dictation after startup still pastes dictated text, not stale clipboard.
7. Short tap never pastes anything.
```

### Future product/UX option (do not implement in current parity pass)

- **Clipboard preservation setting — design carefully; current Python/Tauri behavior leaves dictated text on clipboard.**
- Feature idea: **Preserve clipboard after dictation**.
  - If enabled: Quill temporarily uses clipboard for dictated paste, then restores previous clipboard after paste safely completes.
  - If disabled: Quill leaves dictated text on clipboard (current behavior).
- Safety constraints:
  - Must not reintroduce stale clipboard / first-dictation wrong-paste bug.
  - Do not use delayed background restore threads.
  - Keep restore flow synchronous and generation-safe when/if designed.

---

### 4.4 Ollama skip-simple-cleanup logic

Problem:

- With Ollama enabled and Developer profile selected, simple clean sentences may still go through Ollama.
- This adds unnecessary delay.

Expected behavior:

```text
ai_cleanup_mode = off
→ always skip cleanup

ai_cleanup_mode = auto
→ skip short/simple/clean sentences
→ run cleanup only when useful

ai_cleanup_mode = on
→ run cleanup unless Python has a safety override
```

Developer profile should not force cleanup for every simple sentence.

Claude should:

- Read Python cleanup skip logic.
- Port it to Tauri sidecar.
- Show `Cleanup: skipped` when skipped.
- Keep simple dictation fast.

Future: port full Python smart-skip cleanup logic after stability checkpoint. Include question-like, already well-formed, repetitive input, command-like text, translation-active, non-English, and worker-busy skip rules. Do not implement all at once; port one rule at a time with tests.

---

### 4.5 Restore local auto-correction parity

User remembers earlier Python behavior where misspelled words were corrected.

This should be separate from Ollama.

Restore:

- personal vocabulary corrections
- local typo correction
- SymSpell/common word correction if Python used it
- correction even when Ollama is off

Important guardrails:

- Personal vocabulary should override SymSpell.
- Do not overcorrect Developer profile terms.
- Do not aggressively correct:
  - acronyms
  - file paths
  - URLs
  - code terms
  - camelCase
  - snake_case
  - product names

Goal:

```text
Whisper → personal corrections → local auto-correction → optional Ollama cleanup → paste
```

Ollama should be for sentence-level cleanup, not basic typo correction.

---

## 5. Privacy / recording storage audit

Current finding:

- Tauri sidecar appears to write a temporary `.wav` file for transcription.
- Python app also appears to write a temporary `.wav` and delete it later.

Need Claude to verify:

- Does Tauri delete temp WAV files after transcription?
- Are temp files ever left behind?
- Does cancellation delete temp audio?
- Can we eventually support true in-memory transcription?

Do not claim:

```text
Audio never touches disk.
```

until verified.

Safe current marketing wording:

```text
Local-first. Audio is processed locally. No account required.
```

Future goal:

```text
Ephemeral Mode — audio processed in memory or temp files securely removed immediately.
```

---

## 6. Packaging / Miniconda requirement

Final users should **not** need to install Miniconda.

Current dev setup uses:

```text
/Users/user1/miniconda3/envs/dictation/bin/python
/Users/user1/jarvis-tauri/sidecar/jarvis_sidecar.py
```

That is fine for development but not final packaging.

Final app should provide:

- packaged Python sidecar/runtime, or
- managed bundled runtime, or
- another non-terminal setup path

Users should not have to:

- install Miniconda
- create conda envs
- pip install packages
- configure Python paths
- run sidecar manually

Final user flow should be:

```text
Download Quill
Open Quill
Grant permissions
Start dictating
Optional: set up Ollama for Local AI Cleanup
```

---

## 7. Ollama improvements

### 7.1 Clarify Ollama requirements

Current confusion:

- Ollama app/server is needed.
- Python `ollama` package may also be needed because the sidecar may import it.

Claude should audit:

- Does `jarvis_sidecar.py` import Python `ollama` package?
- Can we replace Python package use with direct HTTP calls to `localhost:11434/api/chat`?

Final user should only need:

```text
Ollama app/server installed and running
model downloaded
```

They should not manually install Python `ollama`.

---

### 7.2 First-run Ollama / Local AI onboarding pop-up

Add a first-run pop-up explaining:

- Ollama is optional.
- Fast dictation works without Ollama.
- Ollama enables Local AI Cleanup.
- Ollama must be running in the background.
- The recommended model may require disk space.
- Model downloads may take time.
- Cleanup runs locally on the Mac.
- User can turn cleanup off anytime.

Suggested buttons:

- Not Now
- Open AI Cleanup Settings
- Check Ollama
- Install Recommended Model

Add setting:

```text
local_ai_onboarding_seen: true
```

Also add a way to open it again:

```text
AI Cleanup page → Learn about Local AI Cleanup
Help page → Local AI Cleanup
```

---

### 7.3 AI Cleanup page hierarchy

Reorder AI Cleanup page using better information architecture.

Recommended order:

1. Local AI Cleanup main control
   - Auto / On / Off

2. Ollama readiness/status
   - Ollama installed?
   - Ollama running?
   - qwen2.5:3b installed?

3. Setup actions
   - Check Again
   - Open Ollama Download Page
   - Install Recommended Model
   - Test Cleanup

4. Behavior controls
   - Correction Strength
   - Writing profile behavior
   - Auto-skip simple sentences

5. Safety/explanation
   - Short phrases protected
   - Non-English cleanup skipped
   - Developer profile notes

---

### 7.4 Ollama model selector

Add advanced Ollama model selector.

Current likely behavior:

- Whisper transcription models can be changed.
- Ollama cleanup model is fixed at `qwen2.5:3b`.

Desired behavior:

- Default remains `qwen2.5:3b`.
- Advanced users can choose installed Ollama models.
- Quill detects installed models with `ollama list`.
- Add Refresh Models button.
- Add Test Cleanup button.
- Save selected model as:

```text
ollama_model
```

Do not make model selection confusing for normal users. Keep it under Advanced.

---

### 7.5 Start/Open Ollama button

Because closing Ollama app stopped `localhost:11434`, Quill should handle this clearly.

If Ollama is not running:

- show “Ollama not running”
- button: Open Ollama
- possibly advanced: Start Ollama server

User-facing copy:

```text
Ollama must be running in the background for Local AI Cleanup. You do not need to interact with the Ollama app, but the server must be active.
```

---

## 8. Performance standards

No-Ollama dictation should feel fast.

Baseline targets with `tiny.en`, cleanup skipped/off:

| Metric | Excellent | Acceptable | Needs work |
|---|---:|---:|---:|
| Stop processing | <0.10s | <0.20s | >0.30s |
| Short transcription | <0.75s | <1.25s | >1.50s |
| Cleanup | skipped | skipped | unexpected cleanup |
| Paste | <0.20s | <0.50s | >0.60s |
| Total after release | <1.00s | <1.50s | >2.00s |

Benchmark phrases:

Short:

```text
Testing, testing, one two three.
```

Medium:

```text
I will continue to test and look at the meters for improvements.
```

Long:

```text
I am testing a longer dictation to see how the app performs when the recording length increases, and whether the delay comes mostly from transcription or from the paste and user interface pipeline.
```

Future timing improvement:

Split Paste timing into:

- activate target app
- pbcopy
- Cmd+V
- total paste

Reason:

- Quartz Cmd+V logs 0ms.
- Timing card may still show paste around 0.6s.
- Likely includes app activation/focus delay.

---

## 9. Clipboard / paste rules

Do not break these again.

Critical rules:

- `paste_text` must stay on the critical path.
- Do not make paste fire-and-forget.
- Do not paste if transcript is empty.
- Do not paste if transcription failed.
- Do not paste if cycle is stale.
- Do not paste if recording was canceled.
- Do not paste on short tap.
- Do not paste previous clipboard as fallback.

Allowed to be async after paste:

- HUD final update
- history save
- timing event
- target app icon update

Short tap expected behavior:

```text
Tap ignored — hold a little longer
No transcription
No paste
Clipboard untouched
```

---

## 10. Small UI / UX bugs found during testing

### 10.1 Menu bar Wake Word toggle reversed

Current:

- checked/off and unchecked/on behavior appears backwards.

Expected:

- checked = Wake Word ON
- unchecked = Wake Word OFF

Fix tray checkbox state mapping only. Do not change wake backend in this task.

---

### 10.2 Vocabulary page jumps to top while typing

Current:

- Every typed letter in new vocabulary entry makes page jump to top.

Expected:

- input stays focused
- scroll position stays stable
- no jump on each keystroke

Likely file:

```text
src/pages/VocabularyPage.tsx
```

---

### 10.3 Custom Commands text runs off page

Current:

- Long text runs outside the card/page.

Expected:

- text wraps, truncates, or stays inside container.
- no horizontal overflow.

Likely file:

```text
src/pages/CustomCommandsPage.tsx
```

---

### 10.4 Manual Vocabulary font/readability

Review font used in manual vocabulary inputs/list.

Questions:

- Should “Whisper hears” and “Should be” use a clearer text-entry font?
- Should code-like entries use mono?
- Avoid global font changes unless approved.

---

### 10.5 Workflow tab needs more information

Improve content.

Explain:

- what workflows are
- example workflows
- whether feature is active or coming soon
- how workflows relate to Jarvis/custom commands

This is a UX/content task, not backend.

---

## 11. App identity / naming cleanup

Current issue:

- Tauri dev binary may show as `jarvis-dictation`.
- UI says Quill / Quill Tauri Preview.
- This causes permission confusion.

Later investigate:

- Cargo package/bin name
- `tauri.conf.json` productName
- bundle identifier
- window title
- tray labels
- About labels

Goal:

```text
Quill Tauri Preview
```

Do not rename while behavior is unstable.

---

## 12. App size / packaging notes

Measured sizes:

```text
/Users/user1/jarvis-tauri                     6.0 GB
node_modules                                  139 MB
src-tauri/target                              5.8 GB
Tauri release .app                            5.9 MB
/Applications/Quill.app Python stable         888 MB
Python packaging dist Quill.app               888 MB
```

Conclusion:

- Tauri dev folder is huge because of Rust build cache.
- Final Tauri shell is tiny.
- Old Python app is large because of Python/PyInstaller/runtime dependencies.

Estimated final app without LLM models:

```text
Best case: 80–150 MB
Realistic: 150–300 MB
Worst case: 300–500 MB
```

Packaging strategy:

- main app small
- optimized Python sidecar
- Whisper runtime packaged carefully
- Ollama/Qwen models downloaded optionally
- do not bundle Qwen/Ollama model into main app yet

---

## 13. Product strategy notes

Positioning:

```text
Quill = private, local-first, fast Mac dictation for power users, with optional local AI cleanup and eventually hands-free Jarvis workflows.
```

Near-term product focus:

- fast local dictation
- beautiful Tauri UI
- reliable HUD
- snippets
- vocabulary corrections
- history
- developer profile basics
- optional Ollama cleanup

Later differentiators:

- stable low-CPU Jarvis wake word
- Jarvis commands
- developer/codebase-aware dictation
- VS Code/Cursor integration
- meeting transcription
- speaker labels
- cloud sync

Do not try to beat Wispr Flow, Superwhisper, Hapi, and Otter all at once.

---

## 14. Features to delay

Do not start yet:

- Jarvis command dispatch
- Agentic email/calendar/Jira commands
- Meeting transcription
- Speaker diarization
- Cloud sync
- Firebase backend
- Bundled Qwen/Ollama model
- Full app rename/package/install
- Broad UI redesign

---

## 15. Safe work while waiting for Claude

Safe:

- manual timing benchmarks
- Ollama behavior notes
- Jarvis test notes
- UI hierarchy notes
- competitor feature comparisons
- pricing/positioning notes
- Claude handoff file
- NotebookLM source document

Avoid:

- paste/clipboard code
- hotkey controller code
- Jarvis wake loop code
- sidecar threading code
- Ollama cleanup logic
- packaging/install scripts

---

## 16. Next Claude priority order

When Claude is available again:

1. Verify current git state and checks.
2. Confirm Quartz paste optimization commit.
3. Confirm `wake_enabled=false` as safe default.
4. Create/update `CLAUDE_HANDOFF_TODO.md`.
5. Compare Python Jarvis wake loop vs Tauri sidecar wake loop.
6. Fix Jarvis wake parity using Python behavior as source of truth.
7. Optimize Jarvis CPU only after detection works.
8. Restore Python clipboard preservation behavior.
9. Port Python Ollama skip-simple-cleanup logic.
10. Restore local auto-correction/SymSpell parity.
11. Add AI Cleanup/Ollama onboarding pop-up.
12. Add advanced Ollama installed-model selector.
13. Fix smaller UI bugs.

---

## 17. First message for Claude

```text
Before editing anything, read CLAUDE_HANDOFF_TODO.md and run:

cd /Users/user1/jarvis-tauri
git status --short
git log --oneline -12
npx tsc --noEmit
cd src-tauri && cargo check

Do not touch /Applications/Quill.app.
Do not touch /Users/user1/dictation/src/jarvis_dictation.py.
Do not install Tauri to /Applications.

The stable Python app is the behavioral source of truth.
The Tauri app should match it.

Current biggest priority:
Jarvis wake-word parity. Jarvis worked in Python and is heavily used. In Tauri, it says Listening, uses about 10% CPU, and does not trigger recording. Compare the stable Python wake loop to the Tauri sidecar before changing code.
```
