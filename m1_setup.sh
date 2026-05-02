#!/bin/bash
# M1 Mac setup script for dictate_v2.py
# Run after every git pull: bash m1_setup.sh

PYTHON="/Users/user1/miniconda3/envs/dictation/bin/python3"
PIP="/Users/user1/miniconda3/envs/dictation/bin/pip"
FILE="$(pwd)/dictate_v2.py"
DICT_PATH="$($PYTHON -c "import symspellpy, os; print(os.path.join(os.path.dirname(symspellpy.__file__), 'frequency_dictionary_en_82_765.txt'))" 2>/dev/null)"

echo "Installing dependencies..."
$PIP install Pillow symspellpy openwakeword onnxruntime faster-whisper sounddevice numpy pynput --quiet

echo "Downloading wake word models..."
$PYTHON -c "from openwakeword.utils import download_models; download_models()" 2>/dev/null

echo "Applying M1 fixes..."
$PYTHON << PYEOF
import re, sys

file = "$FILE"
dict_path = "$DICT_PATH"

with open(file, 'r') as f:
    content = f.read()

if dict_path:
    content = re.sub(r'"[^"]*frequency_dictionary_en_82_765\.txt"', f'"{dict_path}"', content)

content = re.sub(r'MIC_DEVICE\s*=\s*\d+', 'MIC_DEVICE  = 0', content)
content = content.replace('if rms < 0.002:', 'if rms < 0.0001:')
content = content.replace(
    "ICON_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))",
    "ICON_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.argv[0] if sys.argv else '.')))"
)

with open(file, 'w') as f:
    f.write(content)
print('All M1 fixes applied!')
PYEOF

echo "Done! Run: $PYTHON $FILE"
