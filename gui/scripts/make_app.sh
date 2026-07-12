#!/usr/bin/env bash
# Assemble a clickable NybiScan.app from the SwiftPM executable output.
# Usage: gui/scripts/make_app.sh [debug|release]
set -euo pipefail

cd "$(dirname "$0")/.."   # -> gui/
CONFIG="${1:-debug}"

swift build -c "$CONFIG"
BIN_DIR="$(swift build -c "$CONFIG" --show-bin-path)"
APP="NybiScan.app"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp "$BIN_DIR/NybiScanApp" "$APP/Contents/MacOS/NybiScan"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>NybiScan</string>
    <key>CFBundleDisplayName</key><string>NybiScan</string>
    <key>CFBundleIdentifier</key><string>dev.nybiscan.gui</string>
    <key>CFBundleExecutable</key><string>NybiScan</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>0.1.0</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>LSMinimumSystemVersion</key><string>14.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>LSApplicationCategoryType</key><string>public.app-category.developer-tools</string>
</dict>
</plist>
PLIST

echo "Built $APP"
echo "Run: open $APP"
echo "  (from the repo it finds ../.venv/bin/nybiscan automatically; if you move"
echo "   the .app out of the repo, set NYBISCAN_BIN to the nybiscan binary.)"
