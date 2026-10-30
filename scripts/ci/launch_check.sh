#!/usr/bin/env bash
# CI launch check: install the debug APK on a running emulator, start it cold, and fail if the process
# is not alive 20 s later, if logcat shows a FATAL EXCEPTION for it, or if its crash log was written.
# Owner's phone, 2026-10-31: the first APK closed immediately on launch; this gate makes that a CI failure.
# Usage: scripts/ci/launch_check.sh <apk>
set -uo pipefail
apk="$1"
pkg="com.scmtips.field.debug"
out="${GITHUB_WORKSPACE:-.}/ci-out"
mkdir -p "$out"
adb wait-for-device
adb install -r -g "$apk"
adb logcat -c
adb shell am start -W -n "$pkg/com.scmtips.field.app.MainActivity"
sleep 20
adb logcat -d > "$out/launch-logcat.log"
adb shell run-as "$pkg" cat files/last-crash.txt > "$out/launch-crash.txt" 2>/dev/null
pid="$(adb shell pidof "$pkg" | tr -d '\r')"
adb exec-out screencap -p > "$out/launch-screen.png" 2>/dev/null
failed=0
if [ -z "$pid" ]; then echo "FAIL: $pkg is not running 20 s after launch"; failed=1; else echo "process alive: pid $pid"; fi
if grep -q "FATAL EXCEPTION" "$out/launch-logcat.log"; then
  echo "FAIL: FATAL EXCEPTION in logcat:"; grep -A40 "FATAL EXCEPTION" "$out/launch-logcat.log" | head -60; failed=1
fi
if [ -s "$out/launch-crash.txt" ]; then echo "FAIL: the app recorded a crash:"; head -40 "$out/launch-crash.txt"; failed=1; fi
grep -E "SCMTipsField|DATWearables|MetaWearables|AndroidRuntime" "$out/launch-logcat.log" | tail -30
[ "$failed" -eq 0 ] && echo "launch check: the app stayed up with no crash"
exit "$failed"
