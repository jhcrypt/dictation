#!/usr/bin/env bash
# build_mac_app.sh — Build and INSTALL "Jarvis Dictation.app" for Intel Mac
# Usage: cd packaging/mac && chmod +x build_mac_app.sh && ./build_mac_app.sh
#
# Requirements:
#   conda activate dictation
#   pyinstaller installed in the dictation conda env
#
# Build output : packaging/mac/dist/Jarvis Dictation.app  (build artifact — do NOT launch directly)
# Install target: /Applications/Jarvis Dictation.app       (always launch from here)
#
# The script quits any running instance, builds, installs to /Applications,
# and strips quarantine — so the installed copy is always the authoritative one.
# Never run the dist/ copy for testing; always use /Applications/.

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

# Remove previous dist so PyInstaller's COLLECT step never fails with "not empty".
echo "=== Removing old dist ==="
rm -rf "$SCRIPT_DIR/dist"
echo "dist cleared."
echo ""

"$PYINSTALLER" --clean JarvisDictation.spec

# ── Pre-sign cleanup ──────────────────────────────────────────────────────────
# codesign --deep treats every subdirectory in Frameworks/ as a potential
# sub-bundle.  Two kinds of directories break it:
#   1. Python .dist-info metadata dirs (not bundles)
#   2. whisper_models/*  (content-addressed blob dirs, not bundles)
# Fix: remove dist-info dirs (runtime doesn't need them) and move
# whisper_models to MacOS/ where codesign does not recurse.
echo ""
echo "=== Pre-sign cleanup ==="
find "$APP_PATH/Contents/Frameworks" -name "*.dist-info" -type d -exec rm -rf {} + 2>/dev/null || true
echo "Removed .dist-info dirs"

if [[ -d "$APP_PATH/Contents/Frameworks/whisper_models" ]]; then
    mv "$APP_PATH/Contents/Frameworks/whisper_models" "$APP_PATH/Contents/MacOS/whisper_models"
    # Symlink back so sys._MEIPASS (→ Frameworks) can still resolve the path
    ln -s "../MacOS/whisper_models" "$APP_PATH/Contents/Frameworks/whisper_models"
    echo "Moved whisper_models → MacOS/ (symlink in Frameworks/)"
fi

# ── Ad-hoc re-sign ────────────────────────────────────────────────────────────
# Sign all dylibs/SOs individually first, then sign the top-level bundle.
# Avoids --deep which recurses into Frameworks/ and chokes on non-bundle dirs.
echo ""
echo "=== Ad-hoc signing bundle ==="
find "$APP_PATH/Contents" \( -name "*.dylib" -o -name "*.so" \) -exec codesign --force --sign - {} \; 2>/dev/null || true
codesign --force --sign - "$APP_PATH/Contents/MacOS/JarvisDictation"
codesign --force --sign - "$APP_PATH"
echo "Signing complete."

# ── Verify identity ───────────────────────────────────────────────────────────
echo ""
echo "=== Bundle identity ==="
echo "App path        : $APP_PATH"
echo "Bundle ID       : $(defaults read "$APP_PATH/Contents/Info" CFBundleIdentifier)"
echo "Display name    : $(defaults read "$APP_PATH/Contents/Info" CFBundleDisplayName)"
codesign -dvvv "$APP_PATH" 2>&1 | grep -E "Identifier|flags|TeamID"

# ── Strip quarantine attribute from dist copy ─────────────────────────────────
xattr -cr "$APP_PATH" 2>/dev/null || true

# ── Quit any running instance before installing ───────────────────────────────
# Replacing a running .app bundle on macOS is safe (the old process keeps its
# already-mapped pages), but quitting first avoids any file-handle surprises
# and ensures the freshly installed binary is picked up on the very next launch.
INSTALL_PATH="/Applications/${APP_NAME}.app"
echo ""
echo "=== Quitting any running Jarvis Dictation instance ==="
if pgrep -x "JarvisDictation" > /dev/null 2>&1; then
    echo "Running instance found — sending SIGTERM..."
    pkill -x "JarvisDictation" || true
    sleep 1.5
    # Force-kill if it did not exit cleanly
    if pgrep -x "JarvisDictation" > /dev/null 2>&1; then
        echo "Still running — force-killing..."
        pkill -9 -x "JarvisDictation" || true
        sleep 0.5
    fi
    echo "Old instance stopped."
else
    echo "No running instance found."
fi

# ── Install to /Applications and clear quarantine there too ──────────────────
# macOS re-flags the binary as quarantined whenever a new build is copied in.
# We install automatically here so the xattr strip and the copy happen together
# every time — no manual step, no "right-click to open" prompt.
#
# IMPORTANT: /Applications is the authoritative install location.
#   - Always launch from /Applications/Jarvis Dictation.app
#   - Never launch from packaging/mac/dist/ — that is a build artifact only
echo ""
echo "=== Installing to /Applications ==="
rm -rf "$INSTALL_PATH"
# Use -P to preserve symlinks (e.g. Frameworks/whisper_models → ../MacOS/whisper_models)
# so the codesign seal remains valid after copying.
cp -rP "$APP_PATH" "$INSTALL_PATH"
xattr -cr "$INSTALL_PATH" 2>/dev/null || true
echo "Installed: $INSTALL_PATH"
echo "Quarantine cleared on installed copy."

echo ""
echo "=== Build complete ==="
echo "Installed: $INSTALL_PATH"
echo "dist copy: $APP_PATH  ← build artifact, do not launch"
echo ""
echo "To launch the installed app:"
echo "  open \"$INSTALL_PATH\""
echo ""
echo "Do NOT launch the dist/ copy — always use /Applications/."
echo ""
echo "After first launch, grant these permissions in System Settings"
echo "→ Privacy & Security for:  ${APP_NAME}.app"
echo "    Accessibility"
echo "    Input Monitoring"
echo "    Microphone"
