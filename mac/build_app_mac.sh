#!/bin/bash
# Builds "Receipt Organizer.app" into ~/Applications, pointing at this folder. Built locally, so macOS does not quarantine it.
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/Applications/Receipt Organizer.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cat > "$APP/Contents/Info.plist" <<P
<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>CFBundleName</key><string>Receipt Organizer</string><key>CFBundleDisplayName</key><string>Receipt Organizer</string>
<key>CFBundleIdentifier</key><string>local.receipt-organizer</string><key>CFBundleExecutable</key><string>run</string><key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>1</string><key>LSMinimumSystemVersion</key><string>12.0</string><key>CFBundleIconFile</key><string>AppIcon</string><key>NSHighResolutionCapable</key><true/></dict></plist>
P
cat > "$APP/Contents/MacOS/run" <<R
#!/bin/bash
cd "$HERE"
exec "$HERE/.venv/bin/python" -m receipt_organizer.gui >> "\$HOME/Library/Logs/ReceiptOrganizer.log" 2>&1
R
chmod +x "$APP/Contents/MacOS/run"
if [ -f "$HERE/assets/icon.png" ]; then
  T=$(mktemp -d)/AppIcon.iconset; mkdir -p "$T"
  for s in 16 32 128 256 512; do sips -z $s $s "$HERE/assets/icon.png" --out "$T/icon_${s}x${s}.png" >/dev/null; d=$((s*2)); sips -z $d $d "$HERE/assets/icon.png" --out "$T/icon_${s}x${s}@2x.png" >/dev/null; done
  iconutil -c icns "$T" -o "$APP/Contents/Resources/AppIcon.icns" || echo "(icon not built)"
fi
touch "$APP"
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
echo "Built: $APP"
