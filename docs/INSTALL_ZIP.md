# Jarvis Dictation — Install Guide (zip download)

This guide is for people who received **Jarvis Dictation v6.2.4.zip**.  
No terminal, no Python, no Conda required — just drag and drop.

---

## What you need

- A Mac running macOS 12 Monterey or later (Intel or Apple Silicon)
- About 500 MB of free disk space for the app
- Optional: [Ollama](https://ollama.com) if you want local AI text cleanup

---

## Step 1 — Unzip the archive

Double-click **Jarvis Dictation v6.2.4.zip** in Finder.  
This creates a folder called **Jarvis Dictation v6.2.4** containing:

```
Jarvis Dictation.app   ← the app
README.md              ← full user manual
CHANGELOG.md           ← version history
```

---

## Step 2 — Move the app to Applications

Drag **Jarvis Dictation.app** into your **/Applications** folder.

> Always run the app from /Applications. Do not run it from the zip folder — some macOS security features only work when the app is in Applications.

---

## Step 3 — Open the app (bypass Gatekeeper)

Because this app is not distributed through the Mac App Store, macOS will block it the first time.

**Right-click** (or Control-click) **Jarvis Dictation.app** → **Open**.

A dialog will appear saying the app is from an unidentified developer. Click **Open** (or **Open Anyway**).

> You only need to do this once. After the first launch the app opens normally.

If you see "damaged and can't be opened":

1. Open **Terminal** (Spotlight → Terminal).
2. Run: `xattr -cr "/Applications/Jarvis Dictation.app"`
3. Try right-click → Open again.

---

## Step 4 — Grant permissions

Jarvis Dictation needs three permissions to work. macOS will prompt for each one on first use, but you can also grant them manually:

**System Settings → Privacy & Security**

| Permission | Why it is needed | Where to find it |
|---|---|---|
| **Microphone** | Records your voice | Privacy & Security → Microphone |
| **Accessibility** | Types text into other apps | Privacy & Security → Accessibility |
| **Input Monitoring** | Detects the global record hotkey | Privacy & Security → Input Monitoring |

After granting Accessibility or Input Monitoring, **quit and relaunch** the app — macOS requires a restart for those permissions to take effect.

### How to add the app manually

1. Open **System Settings → Privacy & Security → Accessibility** (or whichever permission you need).
2. Click the **+** button.
3. Navigate to **/Applications** and select **Jarvis Dictation**.
4. Make sure the toggle next to it is **on**.

---

## Step 5 — First dictation

1. After launch, a small icon appears in your **menu bar** (top-right of screen). There is no Dock icon — this is expected.
2. Click the menu bar icon to open the menu.
3. Place your cursor in any text field (Notes, Mail, a browser search bar, etc.).
4. Press **Right Option** (the Option key on the right side of your keyboard) — the HUD pill at the top of the screen turns red.
5. Speak naturally.
6. Press **Right Option** again to stop — your words appear at the cursor.

---

## Step 6 — Optional: set up AI text cleanup

Jarvis Dictation works great without this. If you want the app to automatically polish punctuation and style:

1. Download and install **Ollama** from [https://ollama.com](https://ollama.com).
2. Launch Ollama (it lives in your menu bar).
3. In Jarvis Dictation: menu bar → **Settings** → **AI Cleanup** → click **Install Recommended Model**.
4. Wait for the ~2 GB model to download.

---

## Quick reference

| Action | How |
|---|---|
| Start recording | Press **Right Option** |
| Stop recording | Press **Right Option** again |
| Cancel recording | Press **Escape** |
| Open Settings | Menu bar icon → **Settings** |
| View dictation history | Menu bar icon → **History** |
| Quit the app | Menu bar icon → **Quit Jarvis Dictation** |

---

## Troubleshooting

**Nothing is typed after I speak**  
→ Grant **Accessibility** permission and restart the app.

**The record key does nothing**  
→ Grant **Input Monitoring** permission and restart the app.

**Microphone is not working**  
→ Grant **Microphone** permission. Then go to Settings → **Audio & Language** and select the correct microphone from the dropdown.

**"Jarvis Dictation is damaged and can't be opened"**  
→ Open Terminal and run: `xattr -cr "/Applications/Jarvis Dictation.app"`, then try again.

**How do I uninstall?**  
→ Quit the app (menu bar → Quit). Drag **Jarvis Dictation.app** from /Applications to the Trash.  
→ To remove saved settings and history: delete `~/.dictation_settings.json`, `~/.dictation_history.json`, and `~/.dictation_snippets.json` from your home folder.

---

For the full user manual including all voice commands, writing profiles, and advanced settings, see **README.md** included in the zip.
