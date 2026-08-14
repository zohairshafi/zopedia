#!/usr/bin/env bash
# Build Zopedia macOS .app bundle and wrap in DMG.
# Prerequisites:
#   pip install pyinstaller pystray pillow platformdirs pyobjc-framework-Cocoa
#   brew install create-dmg   (optional; falls back to hdiutil)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DIST_DIR="$PROJECT_DIR/dist"
APP_NAME="Zopedia"
APP_VERSION="${APP_VERSION:-1.0.0}"

cd "$PROJECT_DIR"

echo "==> Installing packaging dependencies..."
pip install -q pyinstaller pystray pillow platformdirs "pywebview>=4.4.1"

if [[ "$(uname)" == "Darwin" ]]; then
    pip install -q pyobjc-framework-Cocoa 2>/dev/null || true
fi

echo "==> Building frontend..."
(cd frontend && npm run build)

echo "==> Running PyInstaller..."
rm -rf "$DIST_DIR/$APP_NAME" "$DIST_DIR/$APP_NAME.app"
pyinstaller --clean packaging/Zopedia.spec

echo "==> Creating DMG..."
APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
DMG_PATH="$DIST_DIR/$APP_NAME-${APP_VERSION}.dmg"

if [[ ! -d "$APP_BUNDLE" ]]; then
    echo "ERROR: .app bundle not found at $APP_BUNDLE"
    exit 1
fi

rm -f "$DMG_PATH"

if command -v create-dmg &>/dev/null; then
    create-dmg \
        --volname "$APP_NAME $APP_VERSION" \
        --window-pos 200 120 \
        --window-size 500 320 \
        --icon-size 80 \
        --icon "$APP_NAME.app" 120 150 \
        --app-drop-link 370 150 \
        "$DMG_PATH" \
        "$DIST_DIR/"
else
    echo "==> create-dmg not found, using hdiutil with an Applications shortcut..."
    # Stage the .app next to a symlink to /Applications so the mounted DMG
    # shows an "Applications" target for drag-to-install.
    STAGING_DIR="$DIST_DIR/dmg-staging"
    rm -rf "$STAGING_DIR"
    mkdir -p "$STAGING_DIR"
    cp -R "$APP_BUNDLE" "$STAGING_DIR/"
    ln -s /Applications "$STAGING_DIR/Applications"
    hdiutil create -volname "$APP_NAME" \
        -srcfolder "$STAGING_DIR" \
        -ov -format UDZO \
        "$DMG_PATH"
    rm -rf "$STAGING_DIR"
fi

echo "==> Done: $DMG_PATH"
