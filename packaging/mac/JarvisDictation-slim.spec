# -*- mode: python ; coding: utf-8 -*-
# JarvisDictation-slim.spec — Slim build: tiny.en + small.en only (no base.en)
# Build: cd packaging/mac && pyinstaller --clean JarvisDictation-slim.spec
# Or use the provided build_mac_app_slim.sh script.
#
# Output: packaging/mac/dist/Jarvis Dictation.app
# Bundle ID: com.jhcrypt.jarvis-dictation

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules
import os, sys, pathlib

# packaging/mac/ directory
spec_dir = os.path.dirname(os.path.abspath(SPEC))
# repo root is two levels up
project_dir = os.path.dirname(os.path.dirname(spec_dir))

def resolve(symlink_path):
    p = pathlib.Path(symlink_path)
    return str(p.resolve()) if p.is_symlink() else str(p)

# ── Bundled Whisper models (tiny.en + small.en only — slim build) ────────────
WHISPER_MODELS = {
    "tiny.en":  "~/.cache/huggingface/hub/models--Systran--faster-whisper-tiny.en/snapshots/0d3d19a32d3338f10357c0889762bd8d64bbdeba",
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
datas += collect_data_files('PIL')
datas += collect_data_files('scipy')
datas += collect_data_files('sklearn')
datas += whisper_model_datas

# App icon PNG — used by menu bar and HUD
assets_dir = os.path.join(spec_dir, 'assets')
datas += [
    (os.path.join(assets_dir, 'dictate_icon.png'),      '.'),
    (os.path.join(assets_dir, 'icon_idle.png'),         '.'),
    (os.path.join(assets_dir, 'icon_recording.png'),    '.'),
    (os.path.join(assets_dir, 'icon_transcribing.png'), '.'),
]

# ── Dynamic libraries ─────────────────────────────────────────────────────────
binaries = []
binaries += collect_dynamic_libs('ctranslate2')
binaries += collect_dynamic_libs('onnxruntime')
binaries += collect_dynamic_libs('PIL')
binaries += collect_dynamic_libs('scipy')
binaries += collect_dynamic_libs('sklearn')

# ── Analysis ──────────────────────────────────────────────────────────────────
src_dir = os.path.join(project_dir, 'src')

a = Analysis(
    [os.path.join(src_dir, 'jarvis_dictation.py')],
    pathex=[src_dir, project_dir],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageTk',
        'PIL.ImageFilter',
        'PIL._imaging',
        'PIL.PngImagePlugin',
        'PIL.JpegImagePlugin',
        'PIL.TiffImagePlugin',
        # openwakeword — all submodules (custom_verifier_model imports scipy at top level)
        *collect_submodules('openwakeword'),
        'onnxruntime',
        'onnxruntime.capi',
        'faster_whisper',
        'ctranslate2',
        'tokenizers',
        'huggingface_hub',
        'sounddevice',
        '_sounddevice_data',
        'AppKit',
        'Foundation',
        'objc',
        'symspellpy',
        'pynput',
        'pynput.keyboard',
        'pynput.keyboard._darwin',
        'pynput._util',
        'pynput._util.darwin',
        'wave',
        'json',
        'tempfile',
        'threading',
        'urllib.request',
        'ctypes',
        'ctypes.util',
        'keyring',
        'keyring.backends',
        'keyring.backends.macOS',
        'queue',
        'uuid',
        'platform',
        'Quartz',
        'Quartz.CoreGraphics',
        # scipy — openwakeword.custom_verifier_model uses scipy.io.wavfile
        *collect_submodules('scipy'),
        'scipy.io',
        'scipy.io.wavfile',
        # sklearn — openwakeword.custom_verifier_model uses LogisticRegression, pipelines
        'sklearn',
        'sklearn.linear_model',
        'sklearn.linear_model._logistic',
        'sklearn.pipeline',
        'sklearn.preprocessing',
        'sklearn.preprocessing._data',
        'sklearn.preprocessing._function_transformer',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'pandas', 'cv2',
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
    name='JarvisDictation',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=os.path.join(spec_dir, 'entitlements.plist'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='JarvisDictation',
)

app = BUNDLE(
    coll,
    # Bundle display name uses a space so macOS Finder shows "Jarvis Dictation".
    # The executable inside remains JarvisDictation (no space).
    name='Jarvis Dictation.app',
    icon=os.path.join(spec_dir, 'assets', 'jarvis_dictation.icns'),
    bundle_identifier='com.jhcrypt.jarvis-dictation',
    info_plist={
        # ── Identity ──────────────────────────────────────────────────────────
        'CFBundleName':             'Jarvis Dictation',
        'CFBundleDisplayName':      'Jarvis Dictation',
        'CFBundleExecutable':       'JarvisDictation',
        'CFBundleIdentifier':       'com.jhcrypt.jarvis-dictation',
        'CFBundleShortVersionString': '6.1.19',
        'CFBundleVersion':          '6.1.19',
        'CFBundlePackageType':      'APPL',
        'LSMinimumSystemVersion':   '10.15',
        # ── Menu-bar agent (no Dock icon) ─────────────────────────────────────
        'LSUIElement': True,
        # ── TCC privacy usage descriptions ────────────────────────────────────
        # These strings appear in System Settings permission prompts.
        'NSMicrophoneUsageDescription':
            'Jarvis Dictation uses the microphone to transcribe your voice.',
        'NSAppleEventsUsageDescription':
            'Jarvis Dictation sends keystrokes to type transcribed text into other apps.',
        'NSSpeechRecognitionUsageDescription':
            'Jarvis Dictation transcribes speech locally using Whisper.',
        'NSInputMonitoringUsageDescription':
            'Jarvis Dictation monitors the keyboard to detect the recording hotkey.',
        # ── Apple Events target allowlist ─────────────────────────────────────
        'NSAppleEventsUsageDescription':
            'Jarvis Dictation uses Apple Events to send keystrokes to other apps.',
    },
)
