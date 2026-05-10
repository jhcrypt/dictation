# Security

Jarvis Dictation is private by default.

- Local Whisper transcription runs entirely on your Mac — no audio leaves your device.
- Local Ollama cleanup runs entirely on your Mac — no text leaves your device.
- Cloud transcription (OpenAI), if enabled in Settings, sends audio to OpenAI's API.

## What not to commit

Do not commit files containing personal data:

- API keys or credentials
- Local settings (`~/.dictation_settings.json`)
- Dictation history (`~/.dictation_history.json`)
- Personal snippets (`~/.dictation_snippets.json`)
- Personal vocabulary (`~/.dictation_vocabulary.json`)
- Crash logs containing personal file paths
- Large Whisper model files
- Packaged `.app` bundles, `.dmg`, or `.zip` releases

The `.gitignore` in this repo excludes all of the above.

## Reporting Issues

If you discover a security issue, please open a private GitHub issue or contact the maintainer directly rather than filing a public bug report.
