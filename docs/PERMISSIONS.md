# macOS Permissions

Jarvis Dictation requires four macOS permissions. Grant them in:

**System Settings → Privacy & Security**

---

## Required Permissions

### Microphone
**Why:** Records your voice for transcription.

Grant to: your terminal app (e.g. iTerm2 or Terminal) when running from source, or **JarvisDictation.app** when running the packaged app.

---

### Accessibility
**Why:** Types and pastes transcribed text into other apps. Also used for controlling System Events.

Grant to: your terminal app or **JarvisDictation.app**.

If typing does not work, this permission is likely missing.

---

### Input Monitoring
**Why:** Detects the global record hotkey (Right Option) even when another app is in the foreground.

Grant to: your terminal app or **JarvisDictation.app**.

If the record key does not work, this permission is likely missing.

---

### Automation / Apple Events
**Why:** Controls apps like Reminders, Spark, Spotify, and System Events for Jarvis-style commands.

Grant to: your terminal app or **JarvisDictation.app**.

This is optional — the app functions without it if you do not use Jarvis commands.

---

## Important Note

> **Permissions are per app bundle.**
>
> Permissions granted to Terminal or iTerm2 are **not** shared with the packaged JarvisDictation.app.
> After building the `.app`, you must grant all four permissions to it separately.

---

## Troubleshooting Permissions

**Record key does not work:**
→ Check Input Monitoring. Add your terminal app or JarvisDictation.app.

**Text does not type after recording:**
→ Check Accessibility. Try dictating into TextEdit first to isolate the issue.

**Jarvis commands do not work:**
→ Check Automation. You may need to approve each app individually the first time.

**Microphone error on launch:**
→ Check Microphone. Restart the app after granting permission.
