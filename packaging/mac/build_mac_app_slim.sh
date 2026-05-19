#!/usr/bin/env bash
# build_mac_app_slim.sh — Slim build: tiny.en + small.en only (no base.en)
# Saves ~141 MB compared to the full build.
#
# Usage: cd packaging/mac && chmod +x build_mac_app_slim.sh && ./build_mac_app_slim.sh
#
# Requirements:
#   conda activate dictation
#   pyinstaller installed in the dictation conda env
#
# Build output : packaging/mac/dist/Jarvis Dictation.app  (build artifact)
# Install target: /Applications/Jarvis Dictation.app       (always launch from here)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
APP_NAME="Quill"
APP_PATH="$SCRIPT_DIR/dist/${APP_NAME}.app"

echo ""
echo "=== Jarvis Dictation — Slim Mac App Build (tiny.en + small.en) ==="
echo "Repo root : $REPO_ROOT"
echo "Spec file : $SCRIPT_DIR/JarvisDictation-slim.spec"
echo ""

SRC="$REPO_ROOT/src/jarvis_dictation.py"
if [[ ! -f "$SRC" ]]; then
    echo "ERROR: Source file not found: $SRC"
    exit 1
fi

PYINSTALLER="$HOME/miniconda3/envs/dictation/bin/pyinstaller"
if [[ ! -x "$PYINSTALLER" ]]; then
    PYINSTALLER="$(command -v pyinstaller 2>/dev/null || true)"
fi
if [[ -z "$PYINSTALLER" ]]; then
    echo "ERROR: pyinstaller not found. Run: conda activate dictation && pip install pyinstaller"
    exit 1
fi

echo "Source     : $SRC"
echo "Python     : $("$HOME/miniconda3/envs/dictation/bin/python" --version 2>&1)"
echo "PyInstaller: $PYINSTALLER"
echo "Models     : tiny.en + small.en (base.en excluded)"
echo ""

cd "$SCRIPT_DIR"

echo "=== Removing old dist ==="
rm -rf "$SCRIPT_DIR/dist"
echo "dist cleared."
echo ""

"$PYINSTALLER" --clean JarvisDictation-slim.spec

# ── Pre-sign cleanup ──────────────────────────────────────────────────────────
echo ""
echo "=== Pre-sign cleanup ==="
find "$APP_PATH/Contents/Frameworks" -name "*.dist-info" -type d -exec rm -rf {} + 2>/dev/null || true
echo "Removed .dist-info dirs"

if [[ -d "$APP_PATH/Contents/Frameworks/whisper_models" ]]; then
    mv "$APP_PATH/Contents/Frameworks/whisper_models" "$APP_PATH/Contents/MacOS/whisper_models"
    ln -s "../MacOS/whisper_models" "$APP_PATH/Contents/Frameworks/whisper_models"
    echo "Moved whisper_models → MacOS/ (symlink in Frameworks/)"
fi

# ── Ad-hoc re-sign ────────────────────────────────────────────────────────────
echo ""
echo "=== Ad-hoc signing bundle ==="
find "$APP_PATH/Contents" \( -name "*.dylib" -o -name "*.so" \) -exec codesign --force --sign - {} \; 2>/dev/null || true
codesign --force --sign - "$APP_PATH/Contents/MacOS/JarvisDictation"
codesign --force --sign - "$APP_PATH"
echo "Signing complete."

# ── Report sizes ──────────────────────────────────────────────────────────────
echo ""
echo "=== Slim build sizes ==="
du -sh "$APP_PATH"
du -sh "$APP_PATH/Contents/MacOS/whisper_models/"* 2>/dev/null || true

# ── Strip quarantine ──────────────────────────────────────────────────────────
xattr -cr "$APP_PATH" 2>/dev/null || true

# ── Quit running instance ─────────────────────────────────────────────────────
INSTALL_PATH="/Applications/${APP_NAME}.app"
echo ""
echo "=== Quitting any running Jarvis Dictation instance ==="
if pgrep -x "JarvisDictation" > /dev/null 2>&1; then
    echo "Running instance found — sending SIGTERM..."
    pkill -x "JarvisDictation" || true
    sleep 1.5
    if pgrep -x "JarvisDictation" > /dev/null 2>&1; then
        pkill -9 -x "JarvisDictation" || true
        sleep 0.5
    fi
    echo "Old instance stopped."
else
    echo "No running instance found."
fi

# ── Install to /Applications ──────────────────────────────────────────────────
echo ""
echo "=== Installing slim build to /Applications ==="
rm -rf "$INSTALL_PATH"
cp -rP "$APP_PATH" "$INSTALL_PATH"
xattr -cr "$INSTALL_PATH" 2>/dev/null || true
echo "Installed: $INSTALL_PATH"
echo "Quarantine cleared."

echo ""
echo "=== Slim build complete ==="
echo "Installed : $INSTALL_PATH"
echo "dist copy : $APP_PATH  ← build artifact, do not launch"
echo ""
echo "Models bundled: tiny.en (~74 MB) + small.en (~464 MB)"
echo "base.en (~141 MB) excluded — ~141 MB smaller than full build"
echo ""
echo "To launch:"
echo "  open \"$INSTALL_PATH\""
