#!/usr/bin/env bash
# Собирает «Домашний календарь.app» (универсальный arm64+x86_64) и zip. Запускать на macOS.
set -euo pipefail
cd "$(dirname "$0")"
VER=$(cat version.txt)
BUILD=${GITHUB_RUN_NUMBER:-1}
swift build -c release --arch arm64 --arch x86_64
BIN=$(swift build -c release --arch arm64 --arch x86_64 --show-bin-path)
APP="build/Домашний календарь.app"
rm -rf build
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN/HomeHubMac" "$APP/Contents/MacOS/HomeHubMac"
sed -e "s/__VERSION__/$VER/g" -e "s/__BUILD__/$BUILD/g" Info.plist.in > "$APP/Contents/Info.plist"
ICONSET=build/AppIcon.iconset
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s Resources/AppIcon.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s * 2)) $((s * 2)) Resources/AppIcon.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
# Подпись «на месте» (без аккаунта разработчика): приложение запустится после «Открыть» в контекстном меню.
codesign --force --deep --sign - "$APP"
(cd build && ditto -c -k --keepParent "Домашний календарь.app" HomeHub-Calendar.zip)
echo "Готово: macos/build/HomeHub-Calendar.zip"
