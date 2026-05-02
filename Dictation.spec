# -*- mode: python ; coding: utf-8 -*-
# Dictation.spec — Intel Mac, Python 3.11, conda env "dictation"
# Build: pyinstaller --clean Dictation.spec

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_all
import os, sys, pathlib

project_dir = os.path.dirname(os.path.abspath(SPEC))

def resolve(symlink_path):
    p = pathlib.Path(symlink_path)
    return str(p.resolve()) if p.is_symlink() else str(p)

# ── Bundled Whisper models (tiny.en, base.en, small.en) ──────────────────────
WHISPER_MODELS = {
    "tiny.en":  "~/.cache/huggingface/hub/models--Systran--faster-whisper-tiny.en/snapshots/0d3d19a32d3338f10357c0889762bd8d64bbdeba",
    "base.en":  "~/.cache/huggingface/hub/models--Systran--faster-whisper-base.en/snapshots/3d3d5dee26484f91867d81cb899cfcf72b96be6c",
    "small.en": "~/.cache/huggingface/hub/models--Systran--faster-whisper-small.en/snapshots/d1d751a5f8271d482d14ca55d9e2deeebbae577f",
}
MODEL_FILES = ["model.bin", "config.json", "tokenizer.json", "vocabulary.txt"]

whisper_model_datas = []
for model_name, snapshot_path in WHISPER_MODELS.items():
    snapshot = os.path.expanduser(snapshot_path)
    for fname in MODEL_FILES:
        src = resolve(os.path.join(snapshot, fname))
        if os.path.exists(src):
            whisper_model_datas.append((src, f"whisper_models/{model_name}"))
        else:
            print(f"WARNING: whisper model file not found: {src}")

# ── Data files ────────────────────────────────────────────────────────────────
datas = []
datas += collect_data_files('openwakeword')
datas += collect_data_files('faster_whisper')
datas += collect_data_files('ctranslate2')
datas += collect_data_files('symspellpy')
datas += collect_data_files('PIL')        # Pillow image data files
datas += whisper_model_datas

# Icon PNGs — transparent background, used by HUD and menu bar
datas += [
    (os.path.join(project_dir, 'icon_idle.png'),        '.'),
    (os.path.join(project_dir, 'icon_recording.png'),   '.'),
    (os.path.join(project_dir, 'icon_transcribing.png'),'.'),
]

# ── Dynamic libraries ─────────────────────────────────────────────────────────
binaries = []
binaries += collect_dynamic_libs('ctranslate2')
binaries += collect_dynamic_libs('onnxruntime')
binaries += collect_dynamic_libs('PIL')   # Pillow native libs (_imaging etc.)

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [os.path.join(project_dir, 'dictate_v2.py')],
    pathex=[project_dir],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        # Pillow — needed for HUD app icon rendering
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageTk',
        'PIL.ImageFilter',
        'PIL._imaging',
        'PIL.PngImagePlugin',
        'PIL.JpegImagePlugin',
        'PIL.TiffImagePlugin',
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
        # pyobjc
        'AppKit',
        'Foundation',
        'objc',
        # symspell
        'symspellpy',
        # pynput
        'pynput',
        'pynput.keyboard',
        'pynput.keyboard._darwin',
        'pynput._util',
        'pynput._util.darwin',
        # stdlib
        'wave',
        'json',
        'tempfile',
        'threading',
        'urllib.request',
        'ctypes',
        'ctypes.util',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'pandas', 'scipy', 'cv2',
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
