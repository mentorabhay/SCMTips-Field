#!/usr/bin/env python3
"""SCMTIPS Field - Android Verification Runner (Task T2.001 / FR2.001).

Validates Gradle configuration, libs.versions.toml version catalog,
multi-module project layout, manifests, and executes `./gradlew check`.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ANDROID_ROOT = ROOT / "apps" / "field-android"


def verify_android_structure() -> None:
    print(f"Verifying Android project at: {ANDROID_ROOT}")
    assert (ANDROID_ROOT / "settings.gradle.kts").exists(), "Missing settings.gradle.kts"
    assert (ANDROID_ROOT / "build.gradle.kts").exists(), "Missing build.gradle.kts"
    assert (ANDROID_ROOT / "gradle" / "libs.versions.toml").exists(), "Missing libs.versions.toml"

    # Verify version catalog contents
    catalog_text = (ANDROID_ROOT / "gradle" / "libs.versions.toml").read_text(encoding="utf-8")
    assert 'minSdk = "29"' in catalog_text, "minSdk must be 29"
    assert 'targetSdk = "35"' in catalog_text, "targetSdk must be 35"
    assert 'compileSdk = "35"' in catalog_text, "compileSdk must be 35"
    assert "composeBom" in catalog_text, "Missing composeBom pin"
    assert "wearablesToolkit" in catalog_text, "Missing wearablesToolkit pin"

    # Verify all 7 modules
    modules = [
        "app",
        "core-capture",
        "core-voice",
        "core-outbox",
        "core-wearables",
        "core-positioning-stub",
        "feature-tasks",
    ]
    for mod in modules:
        mod_dir = ANDROID_ROOT / mod
        assert mod_dir.exists(), f"Missing module directory: {mod}"
        assert (mod_dir / "build.gradle.kts").exists(), f"Missing build.gradle.kts in {mod}"
        assert (mod_dir / "src" / "main" / "AndroidManifest.xml").exists(), (
            f"Missing manifest in {mod}"
        )
    print(f"[PASS] All {len(modules)} Android modules verified with SDK 29..35 bounds.")


def run_gradle_check() -> None:
    gradlew_cmd = "gradlew.bat" if os.name == "nt" else "./gradlew"
    gradlew_path = ANDROID_ROOT / gradlew_cmd

    if gradlew_path.exists():
        print(f"Running {gradlew_cmd} check...")
        res = subprocess.run(
            [str(gradlew_path), "check"], cwd=ANDROID_ROOT, capture_output=True, text=True
        )
        print(res.stdout)
        if res.returncode != 0:
            print(res.stderr)
            sys.exit(res.returncode)
    else:
        print("[WARN] gradlew wrapper not found, skipping execution.")


if __name__ == "__main__":
    verify_android_structure()
    run_gradle_check()
    print("[PASS] Android project verification complete.")
