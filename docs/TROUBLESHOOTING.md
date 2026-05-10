# Troubleshooting

---

## Right Option does not start recording

1. Check **Input Monitoring** — go to System Settings → Privacy & Security → Input Monitoring and add your terminal app or JarvisDictation.app.
2. Check **Accessibility** — same location.
3. Restart the app after granting permissions.
4. Confirm the record key is set to **Right Option** in Settings.
5. Try pressing Right Option while the terminal window is focused first.

---

## Recording works but text does not appear

1. Check **Accessibility** — the app needs this permission to type into other apps.
2. Try dictating into **TextEdit** to rule out app-specific issues.
3. Check the terminal log for errors after releasing the record key.
4. Some apps (password managers, some browsers) block simulated keystrokes by design.

---

## Jarvis does not activate

1. Check **Microphone** permission.
2. Open Settings and confirm **Enable Jarvis Wake Word** is on.
3. Make sure the mic is working — try Right Option push-to-dictate first.
4. The wake phrase is "Hey Jarvis" — speak clearly at a normal volume.
5. There is a cooldown after each recording — wait 2 seconds before trying again.

---

## Packaged app behaves differently than the terminal version

macOS permissions are per app bundle. Permissions granted to Terminal or iTerm2 are not shared with JarvisDictation.app.

After building:
1. Open `JarvisDictation.app`.
2. Grant Microphone, Accessibility, and Input Monitoring to it separately in System Settings.
3. Restart the app.

---

## Ollama output is strange or incorrect

1. Keep the default Ollama settings — they have been tuned carefully.
2. Try **Safe Mode** in the menu bar — this bypasses Ollama entirely.
3. Try the **Verbatim** writing profile — this also bypasses AI cleanup.
4. Make sure Ollama is running: `ollama serve` in a terminal.
5. Check the model is downloaded: `ollama list`.

---

## Microphone test

The microphone test feature was removed intentionally. It caused repeated crashes in both the terminal version and the packaged app.

To verify your microphone is working:
```bash
python -c "import sounddevice as sd; print(sd.query_devices())"
```

Check the mic device index matches your Settings. Update it if needed.

---

## App crashes immediately on launch

1. Check the terminal for the error message.
2. Common causes:
   - Missing Python dependency — run `pip install -r requirements.txt`
   - Wrong Python version — confirm `python --version` shows 3.11
   - Wrong conda env — run `conda activate dictation`
3. Try: `python -m py_compile src/jarvis_dictation.py` to check for syntax errors.

---

## Caps Lock triggers issues while windows are open

This is handled automatically by the app. If you see unexpected crashes involving Caps Lock and Settings/Snippets/History windows, restart the app. Do not remove or modify the Caps Lock suppression behavior.

---

## HUD (recording indicator) is not visible

Open Settings and check:
- **Show HUD** is enabled
- The HUD position coordinates are on-screen (not negative or off-screen)

You can reset HUD position in Settings.
