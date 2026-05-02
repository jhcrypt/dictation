# -*- mode: python ; coding: utf-8 -*-
# Dictation.spec — Intel Mac, Python 3.11, conda env "dictation"
# Build: pyinstaller --clean Dictation.spec

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs
import os, sys

project_dir = os.path.dirname(os.path.abspath(SPEC))

# ── Data files ────────────────────────────────────────────────────────────────
datas = []

# openwakeword ONNX models + resources
datas += collect_data_files('openwakeword')

# faster-whisper bundled model data (Hugging Face tokenizer files etc.)
datas += collect_data_files('faster_whisper')

# ctranslate2 native model data
datas += collect_data_files('ctranslate2')

# symspellpy frequency dictionary
datas += collect_data_files('symspellpy')

# Project icon PNGs (used by MenuBarApp._set_icon at runtime)
datas += [
    (os.path.join(project_dir, 'icon_idle.png'),        '.'),
    (os.path.join(project_dir, 'icon_recording.png'),   '.'),
    (os.path.join(project_dir, 'icon_transcribing.png'),'.'),
]

# ── Dynamic libraries ─────────────────────────────────────────────────────────
binaries = []
binaries += collect_dynamic_libs('ctranslate2')
binaries += collect_dynamic_libs('onnxruntime')

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [os.path.join(project_dir, 'dictate_v2.py')],
    pathex=[project_dir],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        # openwakeword
        'openwakeword',
        'openwakeword.model',
        'onnxruntime',
        'onnxruntime.capi',
        # faster-whisper / ctranslate2
        'faster_whisper',
        'ctranslate2',
        'tokenizers',
        'huggingface_hub',
        # audio
        'sounddevice',
        '_sounddevice_data',
        # pyobjc — AppKit / Foundation / objc + NSObject for _Trampoline
        'AppKit',
        'Foundation',
        'objc',
        # symspell
        'symspellpy',
        # pynput keyboard listener
        'pynput',
        'pynput.keyboard',
        'pynput.keyboard._darwin',
        'pynput._util',
        'pynput._util.darwin',
        # standard lib used at runtime
        'wave',
        'json',
        'tempfile',
        'threading',
        'urllib.request',
        # ctypes used by _init_menubar fallback path
        'ctypes',
        'ctypes.util',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'pandas', 'scipy', 'PIL', 'cv2',
        'IPython', 'notebook', 'pytest',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Dictation',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=os.path.join(project_dir, 'entitlements.plist'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Dictation',
)

app = BUNDLE(
    coll,
    name='Dictation.app',
    icon=None,
    bundle_identifier='com.jhcrypt.dictation',
    info_plist={
        'NSMicrophoneUsageDescription': 'Dictation needs the microphone to transcribe your voice.',
        'NSAppleEventsUsageDescription': 'Dictation needs Apple Events to type text into other apps.',
        'LSUIElement': True,
        'LSMinimumSystemVersion': '10.15',
        'CFBundleName': 'Dictation',
        'CFBundleDisplayName': 'Cryptic Dictation',
        'CFBundleShortVersionString': '2.0.0',
        'CFBundleVersion': '2.0.0',
    },
)
