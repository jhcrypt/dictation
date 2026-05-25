# Claude Task — [Specific Bug Name]

## Source of truth
Compare against:
- /Users/user1/dictation/src/jarvis_dictation.py
- /Users/user1/dictation/README.md

Do not invent new behavior. Port Python behavior unless explicitly told otherwise.

## Explicit product overrides (do NOT revert to Python reference)

| Behavior | Python | Quill decision |
|---|---|---|
| Clipboard after paste | Leaves dictated text on clipboard | **Restores previous clipboard** after 600 ms |

Clipboard restore rule: `pbcopy(dictation) → Cmd+V → sleep(600ms) → pbcopy(prev_clipboard)`
The 600 ms wait is mandatory — without it, slow apps read the restored old clipboard instead of the dictation.

## Protected rules
- Do not modify /Applications/Quill.app
- Do not modify /Applications/Jarvis Dictation.app
- Do not modify /Users/user1/dictation/src/jarvis_dictation.py
- Do not install Tauri to /Applications
- Do not create a second recording controller
- Do not call sidecar recording commands outside useGlobalHotkey.ts
- Do not bypass existing regression guards

## Fix method
1. Find the matching behavior in the Python reference.
2. Compare it to the Tauri implementation.
3. Identify the exact mismatch.
4. Make the smallest port/fix.
5. Add or update tests.
6. Run required checks.
7. Run manual QA.
8. Report root cause, changed files, tests, manual QA, and commit hash.

## Required regression checks
After every fix, verify:
- Normal dictation
- Record button dictation
- Wake/Jarvis dictation
- Wake/Jarvis command
- Short tap friendly message
- HUD waveform starts immediately
- Voice commands: period, next line, scratch that, open Safari
- Custom commands: Open URL, Open App, Type Text
- Clipboard preservation
- Email command does not put body text in To field
- Jarvis auto-stop obeys grace/silence/max
- No duplicate paste
- No invented words from cleanup
- State returns idle after command/error/short tap

## Required commands
```bash
cd /Users/user1/jarvis-tauri
cd sidecar && python3 test_sidecar_cmds.py && cd ..
npm test
npx tsc --noEmit
cd src-tauri && cargo check
```

## Rebuild procedure
After Python-only changes:
> Quit and reopen Jarvis Dictation Tauri — sidecar reloads from disk.

After TypeScript/React changes:
```bash
cd /Users/user1/jarvis-tauri
npm run build
cargo build --release --manifest-path src-tauri/Cargo.toml
cp src-tauri/target/release/jarvis-dictation \
   "src-tauri/target/release/bundle/macos/Jarvis Dictation Tauri.app/Contents/MacOS/jarvis-dictation"
```

After Rust-only changes:
```bash
cargo build --release --manifest-path src-tauri/Cargo.toml
cp src-tauri/target/release/jarvis-dictation \
   "src-tauri/target/release/bundle/macos/Jarvis Dictation Tauri.app/Contents/MacOS/jarvis-dictation"
```
