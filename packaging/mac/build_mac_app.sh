#!/usr/bin/env bash
# build_mac_app.sh — Build JarvisDictation.app for Intel Mac
# Usage: cd packaging/mac && chmod +x build_mac_app.sh && ./build_mac_app.sh
#
# Requirements:
#   conda activate dictation
#   pyinstaller installed in the dictation conda env
#
# Output: packaging/mac/dist/JarvisDictation.app

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo ""
echo "=== Jarvis Dictation — Mac App Build ==="
echo "Repo root : $REPO_ROOT"
echo "Spec file : $SCRIPT_DIR/JarvisDictation.spec"
echo ""

# Sanity check — make sure the source file exists
SRC="$REPO_ROOT/src/jarvis_dictation.py"
if [[ ! -f "$SRC" ]]; then
    echo "ERROR: Source file not found: $SRC"
    exit 1
fi

# Sanity check — make sure pyinstaller is available
if ! command -v pyinstaller &>/dev/null; then
    echo "ERROR: pyinstaller not found. Run: conda activate dictation && pip install pyinstaller"
    exit 1
fi

echo "Source  : $SRC"
echo "Python  : $(python --version)"
echo ""

# Run from the packaging/mac directory so relative paths in the spec work
cd "$SCRIPT_DIR"

pyinstaller --clean JarvisDictation.spec

echo ""
echo "=== Build complete ==="
echo "App: $SCRIPT_DIR/dist/JarvisDictation.app"
echo ""
echo "To run the app:"
echo "  open $SCRIPT_DIR/dist/JarvisDictation.app"
echo ""
echo "Remember to grant Microphone, Accessibility, and Input Monitoring"
echo "permissions to JarvisDictation.app in System Settings."
