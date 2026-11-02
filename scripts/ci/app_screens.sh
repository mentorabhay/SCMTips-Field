#!/usr/bin/env bash
# Screenshot book (M5-K01): install the hosted APK on the running emulator with every permission granted,
# then walk the app (tools/app_screens) and keep the screenshots, the walk's recording and steps.json.
# Usage: scripts/ci/app_screens.sh <apk>
set -uo pipefail
apk="$1"
pkg="com.scmtips.field.debug"
out="${GITHUB_WORKSPACE:-.}/app-screens"
logs="${GITHUB_WORKSPACE:-.}/ci-out"
mkdir -p "$out" "$logs"
adb wait-for-device
adb shell settings put system screen_off_timeout 1800000
adb shell svc power stayon true
adb install -r -g "$apk"
adb logcat -c
python3 -m tools.app_screens.drive --out "$out" --package "$pkg" 2>&1 | tee "$logs/app-screens-walk.log"
code=${PIPESTATUS[0]}
adb logcat -d > "$logs/app-screens-logcat.log"
cp "$out/steps.json" "$logs/app-screens-steps.log" 2>/dev/null
ls -la "$out" | tee -a "$logs/app-screens-walk.log"
exit "$code"
