#!/usr/bin/env python3
"""SCMTIPS Field - Android Verification Runner (Rule 2.1 / Task R0.5).

Runs the official Gradle wrapper to execute:
assembleDebug testDebugUnitTest lintDebug

Fails honestly if any module fails to compile, test, or lint.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ANDROID_ROOT = ROOT / "apps" / "field-android"


def verify_android_structure() -> None:
    print(f"Verifying Android project structure at: {ANDROID_ROOT}")
    assert (ANDROID_ROOT / "settings.gradle.kts").exists(), "Missing settings.gradle.kts"
    assert (ANDROID_ROOT / "build.gradle.kts").exists(), "Missing build.gradle.kts"
    assert (ANDROID_ROOT / "gradle" / "libs.versions.toml").exists(), "Missing libs.versions.toml"
    assert (ANDROID_ROOT / "gradle" / "wrapper" / "gradle-wrapper.jar").exists(), "Missing gradle-wrapper.jar"
    assert (ANDROID_ROOT / "gradle" / "wrapper" / "gradle-wrapper.properties").exists(), "Missing gradle-wrapper.properties"

    # Verify version catalog contents
    catalog_text = (ANDROID_ROOT / "gradle" / "libs.versions.toml").read_text(encoding="utf-8")
    assert 'minSdk = "29"' in catalog_text, "minSdk must be 29"
    assert 'targetSdk = "35"' in catalog_text, "targetSdk must be 35"
    assert 'compileSdk = "35"' in catalog_text, "compileSdk must be 35"
    print("[PASS] Android project layout and version catalog verified.")


def run_gradle_build() -> int:
    gradlew_cmd = "gradlew.bat" if os.name == "nt" else "./gradlew"
    gradlew_path = ANDROID_ROOT / gradlew_cmd

    if not gradlew_path.exists():
        print(f"[FAIL] Gradle wrapper {gradlew_cmd} not found in {ANDROID_ROOT}")
        return 1

    targets = ["assembleDebug", "testDebugUnitTest", "lintDebug"]
    print(f"Executing Gradle build targets: {' '.join(targets)}")
    
    cmd = [str(gradlew_path)] + targets
    proc = subprocess.run(
        cmd,
        cwd=ANDROID_ROOT,
        text=True,
    )
    return proc.returncode


def main() -> int:
    verify_android_structure()
    rc = run_gradle_build()
    if rc != 0:
        print(f"[FAIL] Gradle build failed with exit code {rc}")
        return rc
    print("[PASS] Android project build and verification complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
