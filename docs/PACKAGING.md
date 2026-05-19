# Phase 10 — Packaging

## Build a release .app

```bash
cd /Users/user1/jarvis-tauri
npm run tauri build
```

Output: `src-tauri/target/release/bundle/macos/Jarvis Dictation.app`

## What gets bundled

| Item | Location in .app |
|------|-----------------|
| Tauri shell (Rust binary) | `Contents/MacOS/jarvis-dictation` |
| React frontend | embedded in binary via Tauri |
| App icons | `Contents/Resources/` |

## Python sidecar — current status (Phase 5)

The sidecar is **not yet bundled** in the .app. For the hybrid phase:

1. The user must have the `dictation` conda environment: `~/miniconda3/envs/dictation/`
2. The sidecar script lives at: `~/jarvis-tauri/sidecar/jarvis_sidecar.py`
3. Tauri finds Python via hardcoded candidate paths in `commands.rs`

### To bundle Python properly (future work):
- Use PyInstaller to create a standalone sidecar binary
- Add it as a Tauri sidecar in `tauri.conf.json` under `bundle.externalBin`
- Configure entitlements for macOS microphone + accessibility access

## Permissions (macOS)

The app needs these entries in `Info.plist` / entitlements:

```xml
<key>NSMicrophoneUsageDescription</key>
<string>Jarvis Dictation needs microphone access to transcribe your speech.</string>

<key>NSAppleEventsUsageDescription</key>
<string>Jarvis Dictation uses AppleScript to compose emails and create reminders.</string>
```

And in the entitlements file:
```xml
<key>com.apple.security.device.audio-input</key>
<true/>
```

## First-run instructions (pre-bundle)

```bash
# 1. Install npm deps
cd ~/jarvis-tauri && npm install

# 2. Start dev server
npm run tauri dev

# 3. Or build for production
npm run tauri build
```

## Settings file compatibility

The Tauri app reads and writes `~/.dictation_settings.json` — the same file
the Python app uses. Both can run concurrently without conflict (each saves on
explicit user action, not on change).
