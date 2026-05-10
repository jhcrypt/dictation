# Contributing

Thank you for your interest in Jarvis Dictation.

## Before you contribute

- Use Python 3.11 in the `dictation` conda environment.
- Test the terminal version (`python src/jarvis_dictation.py`) before packaging.
- Run `python -m py_compile src/jarvis_dictation.py` to check for syntax errors.

## Rules

- **Do not call Tkinter directly from Quartz, PyObjC, or sounddevice callbacks.**
  The safe architecture is: `callback → queue small command → Tkinter main loop handles real work`.

- **Do not change the hotkey/input system without careful testing.**
  The Quartz HID tap + main thread architecture is the result of many iterations fixing SIGILL crashes.

- **Do not add arbitrary terminal command execution.**
  Any shell command execution must be reviewed carefully.

- **Do not retune Ollama defaults without user testing.**
  The current options are stable and intentional.

- **Keep Right Option as the recommended record hotkey.**
  Supported options are: Right Option, F13, F14, F15.

- **Do not re-add removed features without discussion:**
  - Microphone test (caused repeated crashes)
  - Left Option / Command / Control hotkeys (unreliable or conflicting)

- **Do not remove Caps Lock suppression** around Settings/Snippets/History windows.
  That protection was added specifically to avoid macOS SIGILL crashes.

## Submitting changes

1. Fork the repo and create a feature branch.
2. Make your changes and test manually.
3. Open a pull request with a clear description of what changed and why.
