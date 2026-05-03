#!/bin/bash
# M1 Mac setup script for Cryptic Dictation
# Run once on a new M1 Mac: bash m1_setup.sh
# Then run: conda activate dictation && python dictate_v2.py

set -e

CONDA_BASE=$(conda info --base 2>/dev/null || echo "$HOME/miniconda3")
ENV_NAME="dictation"
ENV_PYTHON="$CONDA_BASE/envs/$ENV_NAME/bin/python3"
ENV_PIP="$CONDA_BASE/envs/$ENV_NAME/bin/pip"

echo "=== Cryptic Dictation — M1 Setup ==="
echo "Conda base: $CONDA_BASE"

# Create env if it doesn't exist
if ! conda env list | grep -q "^$ENV_NAME "; then
    echo "Creating conda env '$ENV_NAME' with Python 3.11..."
    conda create -n $ENV_NAME python=3.11 -y
fi

echo "Installing dependencies..."
$ENV_PIP install --upgrade pip --quiet
$ENV_PIP install \
    faster-whisper \
    sounddevice \
    numpy \
    pynput \
    pyobjc-framework-Cocoa \
    pyobjc-framework-AppKit \
    pyobjc-framework-AVFoundation \
    symspellpy \
    openwakeword \
    onnxruntime \
    Pillow \
    --quiet

echo "Downloading wake word models..."
$ENV_PYTHON -c "
from openwakeword.utils import download_models
download_models()
print('Wake word models downloaded')
" 2>/dev/null || echo "Wake word models download skipped"

echo "Downloading Whisper models (tiny + base)..."
$ENV_PYTHON -c "
from faster_whisper import WhisperModel
for m in ['tiny.en', 'base.en']:
    print(f'Downloading {m}...')
    WhisperModel(m, device='cpu', compute_type='float16')
    print(f'{m} ready')
"

echo "Finding default mic device..."
MIC_DEVICE=$($ENV_PYTHON -c "
import sounddevice as sd
devices = sd.query_devices()
for i, d in enumerate(devices):
    if d['max_input_channels'] > 0 and 'microphone' in d['name'].lower():
        print(i)
        exit()
# fallback: first input device
for i, d in enumerate(devices):
    if d['max_input_channels'] > 0:
        print(i)
        exit()
print(0)
" 2>/dev/null)

echo "Setting mic device to $MIC_DEVICE..."
$ENV_PYTHON -c "
import json, os
path = os.path.expanduser('~/.dictation_settings.json')
s = {}
if os.path.exists(path):
    with open(path) as f:
        s = json.load(f)
s['mic_device'] = $MIC_DEVICE
s.setdefault('model', 'base.en')
with open(path, 'w') as f:
    json.dump(s, f, indent=2)
print(f'Settings saved: mic_device={$MIC_DEVICE}')
"

echo ""
echo "=== Setup complete! ==="
echo "Run with:"
echo "  conda activate $ENV_NAME && python dictate_v2.py"
