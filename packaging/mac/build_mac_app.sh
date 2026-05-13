#!/usr/bin/env bash
# build_mac_app.sh — Build "Jarvis Dictation.app" for Intel Mac
# Usage: cd packaging/mac && chmod +x build_mac_app.sh && ./build_mac_app.sh
#
# Requirements:
#   conda activate dictation
#   pyinstaller installed in the dictation conda env
#
# Output: packaging/mac/dist/Jarvis Dictation.app

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
APP_NAME="Jarvis Dictation"
APP_PATH="$SCRIPT_DIR/dist/${APP_NAME}.app"

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

# Prefer the conda env pyinstaller; fall back to PATH
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
echo ""

# Run from the packaging/mac directory so relative paths in the spec work
cd "$SCRIPT_DIR"

"$PYINSTALLER" --clean JarvisDictation.spec

# ── Ad-hoc re-sign ────────────────────────────────────────────────────────────
# PyInstaller signs each binary during the build, but a final deep re-sign
# gives the whole bundle one consistent ad-hoc identity. macOS TCC uses this
# identity to track permission grants (Accessibility, Input Monitoring, etc.)
# across launches, so a stable signature is critical for double-click use.
echo ""
echo "=== Ad-hoc signing bundle ==="
codesign --force --deep --sign - "$APP_PATH"
echo "Signing complete."

# ── Verify identity ───────────────────────────────────────────────────────────
echo ""
echo "=== Bundle identity ==="
echo "App path        : $APP_PATH"
echo "Bundle ID       : $(defaults read "$APP_PATH/Contents/Info" CFBundleIdentifier)"
echo "Display name    : $(defaults read "$APP_PATH/Contents/Info" CFBundleDisplayName)"
codesign -dvvv "$APP_PATH" 2>&1 | grep -E "Identifier|flags|TeamID"

# ── Strip quarantine attribute ────────────────────────────────────────────────
# cp -r preserves the com.apple.quarantine xattr, which makes macOS show a
# "Drag to Applications" prompt the first time the app is launched.
# Clearing it here (on the dist copy) means any subsequent cp to /Applications
# won't carry the flag along.
xattr -cr "$APP_PATH" 2>/dev/null || true
echo "Quarantine attribute cleared."

echo ""
echo "=== Build complete ==="
echo "App: $APP_PATH"
echo ""
echo "To run the app:"
echo "  open \"$APP_PATH\""
echo ""
echo "After first launch, grant these permissions in System Settings"
echo "→ Privacy & Security for:  ${APP_NAME}.app"
echo "    Accessibility"
echo "    Input Monitoring"
echo "    Microphone"
