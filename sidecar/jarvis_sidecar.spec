# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for jarvis_sidecar — produces a self-contained onedir bundle
# that can be shipped inside the Tauri .app without any Python or conda dependency.
#
# Output:  dist/jarvis-sidecar/
#            jarvis-sidecar        (executable)
#            _internal/            (Python + all dylibs)
#
# Copy the whole dist/jarvis-sidecar/ folder to:
#   Jarvis Dictation Tauri.app/Contents/MacOS/jarvis-sidecar/
#
# Rust resolves the path as:
#   current_exe().parent() / "jarvis-sidecar" / "jarvis-sidecar"

from PyInstaller.utils.hooks import collect_all, collect_data_files

# ── Packages that need full binary + data + hidden-import collection ──────────
ctranslate2_datas, ctranslate2_binaries, ctranslate2_hiddenimports = collect_all('ctranslate2')
openwakeword_datas, openwakeword_binaries, openwakeword_hiddenimports = collect_all('openwakeword')
ort_datas, ort_binaries, ort_hiddenimports = collect_all('onnxruntime')

# sounddevice ships PortAudio as package data — must be collected explicitly
sd_datas = collect_data_files('_sounddevice_data')

# symspellpy ships frequency dictionaries as package data
sym_datas = collect_data_files('symspellpy')

a = Analysis(
    ['jarvis_sidecar.py'],
    pathex=[],
    binaries=ctranslate2_binaries + openwakeword_binaries + ort_binaries,
    datas=ctranslate2_datas + openwakeword_datas + ort_datas + sd_datas + sym_datas,
    hiddenimports=(
        ctranslate2_hiddenimports
        + openwakeword_hiddenimports
        + ort_hiddenimports
        + [
            # faster_whisper submodules
            'faster_whisper',
            'faster_whisper.audio',
            'faster_whisper.transcribe',
            'faster_whisper.tokenizer',
            'faster_whisper.utils',
            'faster_whisper.vad',
            # audio
            'sounddevice',
            '_sounddevice_data',
            # numerics
            'numpy',
            'numpy.core',
            # HTTP (cloud transcription + Ollama)
            'requests',
            'urllib.request',
            'urllib.error',
            # spell correction (optional feature)
            'symspellpy',
        ]
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Exclude large packages the sidecar never imports at runtime.
    # openwakeword's train.py pulls in scipy/sklearn — those are training-only.
    excludes=[
        'scipy',
        'sklearn', 'scikit_learn',
        'matplotlib',
        'PIL', 'Pillow',
        'pandas',
        'torch', 'torchvision', 'torchaudio',
        'transformers',
        'av',
        'tensorflow', 'keras',
        'IPython', 'jupyter', 'notebook',
        'tkinter', '_tkinter',
        'wx', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # onedir mode: binaries go into COLLECT, not embedded
    name='jarvis-sidecar',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,            # stdin/stdout protocol requires console mode
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,        # build for current arch (arm64 on M-series)
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='jarvis-sidecar',   # output folder name
)
