from setuptools import setup

APP = ['dictate_v2.py']
DATA_FILES = []
OPTIONS = {
    'argv_emulation': False,
    'plist': {
        'CFBundleName': 'Dictation',
        'CFBundleDisplayName': 'Dictation',
        'CFBundleIdentifier': 'com.jhcrypt.dictation',
        'CFBundleVersion': '2.0.0',
        'CFBundleShortVersionString': '2.0.0',
        'NSMicrophoneUsageDescription': 'Dictation needs microphone access for speech to text.',
        'NSAppleEventsUsageDescription': 'Dictation needs accessibility access to type into other apps.',
        'LSUIElement': True,
    },
    'packages': [
        'faster_whisper',
        'symspellpy',
        'sounddevice',
        'pynput',
        'numpy',
        'tkinter',
    ],
    'excludes': ['matplotlib', 'scipy', 'PIL'],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
