#!/usr/bin/env bash
# Собирает APK и кладёт его в android/release — оттуда сервер календаря раздаёт
# приложение по адресу /app.apk, а установленные приложения видят новую версию.
#   1) увеличьте versionCode (и versionName) в android/version.properties
#   2) ./android/build-release.sh
#   3) закоммитьте android/release — сервер обновится сам
set -euo pipefail
cd "$(dirname "$0")"
export ANDROID_HOME="${ANDROID_HOME:-/opt/android-sdk}"
[ -f local.properties ] || echo "sdk.dir=$ANDROID_HOME" > local.properties
./gradlew --no-daemon -q clean assembleRelease
mkdir -p release
cp app/build/outputs/apk/release/app-release.apk release/homehub-calendar.apk
code=$(grep versionCode version.properties | cut -d= -f2)
name=$(grep versionName version.properties | cut -d= -f2)
printf '{"versionCode": %s, "versionName": "%s", "built": "%s"}\n' "$code" "$name" "$(date -Iseconds)" > release/version.json
echo "Готово: release/homehub-calendar.apk ($name, $code)"
