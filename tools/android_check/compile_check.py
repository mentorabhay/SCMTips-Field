"""Type-check the M1 Android slice with the real Kotlin 2.2.21 compiler + Compose plugin against the real
class files of every library it uses (Meta DAT 1.0.1, AndroidX, Compose, ML Kit, OkHttp...) and the
Android 15 framework classes (Robolectric's android-all jar). No Android SDK licence is involved.

What it proves: the Kotlin sources compile against the exact APIs (e.g. the DAT calls in DatGlasses.kt).
What it does NOT prove: resources, manifest merge, dexing, lint, packaging or runtime behaviour - only a
Gradle build (scripts/jobs/android.py, CI) does. It also compiles every source against ONE classpath, so
a module that exposes a library type through `implementation` instead of `api` passes here and fails in
Gradle (CI run 41096609521: core-outbox's retrofit2.Response was invisible to :app). Artifacts are cached in ~/.cache/scmtips-android-check.

    uv run python -m tools.android_check.compile_check          # the M1 slice
    uv run python -m tools.android_check.compile_check --all    # every module
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "apps" / "field-android"
CACHE = Path(os.environ.get("ANDROID_CHECK_CACHE", Path.home() / ".cache" / "scmtips-android-check"))
REPOS = (
    os.environ.get("GOOGLE_MAVEN", "https://dl.google.com/dl/android/maven2"),
    os.environ.get("MAVEN_CENTRAL", "https://maven-central.storage-download.googleapis.com/maven2"),
)
NS = "{http://maven.apache.org/POM/4.0.0}"
KOTLIN = "2.2.21"
COMPILER = [f"org.jetbrains.kotlin:{a}:{KOTLIN}" for a in
            ("kotlin-compiler-embeddable", "kotlin-stdlib", "kotlin-script-runtime", "kotlin-reflect",
             "kotlin-daemon-embeddable")] + ["org.jetbrains.intellij.deps:trove4j:1.0.20200330",
                                             "org.jetbrains:annotations:13.0",
                                             "org.jetbrains.kotlinx:kotlinx-coroutines-core-jvm:1.11.0"]
COMPOSE_PLUGIN = f"org.jetbrains.kotlin:kotlin-compose-compiler-plugin-embeddable:{KOTLIN}"
ANDROID_ALL = "org.robolectric:android-all:15-robolectric-13954326"
ROOTS = [  # the app's direct dependencies (versions as in gradle/libs.versions.toml)
    "com.meta.wearable:mwdat-core:1.0.1", "com.meta.wearable:mwdat-camera:1.0.1",
    "com.meta.wearable:mwdat-speech:1.0.1", "com.meta.wearable:mwdat-inputs:1.0.1",
    "androidx.activity:activity-compose:1.13.0", "androidx.lifecycle:lifecycle-runtime-ktx:2.10.0",
    "androidx.compose.material3:material3:1.4.0", "androidx.security:security-crypto:1.1.0",
    "com.google.mlkit:barcode-scanning:17.3.0", "com.google.android.gms:play-services-code-scanner:16.1.0",
    "androidx.core:core-ktx:1.16.0", "com.squareup.okhttp3:okhttp:4.12.0",
    "org.jetbrains.kotlinx:kotlinx-serialization-json-jvm:1.9.0",
]
APP = "app/src/main/kotlin/com/scmtips/field/app"
SOURCES = [f"{APP}/{p}" for p in ("MainActivity.kt", "FieldApplication.kt", "SliceController.kt", "device/DeviceIo.kt",
                                   "ui/SliceScreens.kt", "ui/theme/Theme.kt", "ui/theme/Color.kt",
                                   "glasses/DatGlasses.kt", "net/FieldHttp.kt", "slice/ReceiveFlow.kt",
                                   "slice/Pairing.kt")]
MODULES = ("core-common", "core-voice", "core-wearables")
# --all: every module's main sources (the whole Gradle project, minus code generation such as Room/KSP)
ALL_ROOTS = [
    "androidx.room:room-runtime:2.7.2", "androidx.room:room-ktx:2.7.2", "androidx.work:work-runtime-ktx:2.10.5",
    "net.zetetic:android-database-sqlcipher:4.5.4", "com.squareup.retrofit2:retrofit:2.11.0",
    "com.squareup.retrofit2:converter-kotlinx-serialization:2.11.0", "com.squareup.okhttp3:logging-interceptor:4.12.0",
]


def _fetch(path: str) -> bytes | None:
    for r in REPOS:
        try:
            with urllib.request.urlopen(f"{r}/{path}", timeout=120) as f:  # noqa: S310 - fixed https repos
                return bytes(f.read())
        except Exception:  # noqa: BLE001 - try the next repository
            continue
    return None


def _base(g: str, a: str, v: str) -> str:
    return f"{g.replace('.', '/')}/{a}/{v}/{a}-{v}"


def _vkey(v: str) -> list[int | str]:
    return [int(x) if x.isdigit() else x for x in re.split(r"[.\-]", v)]


def _child(e: ET.Element, tag: str) -> str | None:
    c = e.find(NS + tag)
    return (c.text or "").strip() if c is not None else None


def resolve(roots: list[str]) -> dict[tuple[str, str], str]:
    """Transitive compile+runtime closure from POMs; the highest version of each artifact wins."""
    seen: dict[tuple[str, str], str] = {}

    def walk(g: str, a: str, v: str) -> None:
        if (g, a) in seen and _vkey(v) <= _vkey(seen[(g, a)]):
            return
        seen[(g, a)] = v
        data = _fetch(_base(g, a, v) + ".pom")
        if not data:
            return
        pom = ET.fromstring(data)
        props = {c.tag.replace(NS, ""): (c.text or "").strip() for c in (pom.find(NS + "properties") or [])}
        for d in pom.find(NS + "dependencies") or []:
            dg, da, dv, sc, opt = (_child(d, t) for t in ("groupId", "artifactId", "version", "scope", "optional"))
            if not (dg and da and dv) or (sc or "compile") not in ("compile", "runtime") or opt == "true":
                continue
            dv = re.sub(r"\$\{([^}]+)\}", lambda m: v if m.group(1) == "project.version" else props.get(m.group(1), ""), dv)
            dv = dv.strip("[]()").split(",")[0]
            if dg == "org.jetbrains.kotlin" and da.startswith("kotlin-stdlib"):
                continue
            walk(dg, da, dv)

    for spec in roots:
        walk(*spec.split(":"))
    return seen


def jar(g: str, a: str, v: str) -> Path | None:
    dst = CACHE / f"{g}.{a}-{v}.jar"
    if dst.exists():
        return dst
    CACHE.mkdir(parents=True, exist_ok=True)
    data = _fetch(_base(g, a, v) + ".aar")
    if data:
        z = zipfile.ZipFile(io.BytesIO(data))
        if "classes.jar" not in z.namelist():
            return None
        dst.write_bytes(z.read("classes.jar"))
        return dst
    data = _fetch(_base(g, a, v) + ".jar")
    if data is None:
        return None
    dst.write_bytes(data)
    return dst


def main() -> int:
    compiler = [jar(*c.split(":")) for c in COMPILER]
    plugin = jar(*COMPOSE_PLUGIN.split(":"))
    android = jar(*ANDROID_ALL.split(":"))
    if None in compiler or plugin is None or android is None:
        print("[FAIL] could not download the Kotlin compiler / Compose plugin / android-all jar")
        return 1
    everything = "--all" in sys.argv
    libs = [p for (g, a), v in sorted(resolve(ROOTS + (ALL_ROOTS if everything else [])).items()) if (p := jar(g, a, v))]
    if everything:
        srcs = [str(p) for p in sorted(ANDROID.glob("*/src/main/kotlin/**/*.kt"))]
    else:
        srcs = [str(ANDROID / s) for s in SOURCES]
        for m in MODULES:
            srcs += [str(p) for p in sorted((ANDROID / m / "src" / "main" / "kotlin").rglob("*.kt"))]
    with tempfile.TemporaryDirectory() as tmp:
        bc = Path(tmp) / "BuildConfig.kt"  # generated by AGP in a real build
        bc.write_text('package com.scmtips.field.app\nobject BuildConfig { const val VERSION_NAME = "check" }\n')
        cmd = ["java", "-cp", os.pathsep.join(map(str, compiler)), "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
               "-no-stdlib", "-no-reflect", "-jvm-target", "17", f"-Xplugin={plugin}",
               "-cp", os.pathsep.join(map(str, [compiler[1], compiler[-1], android, *libs])),
               "-d", str(Path(tmp) / "out"), *srcs, str(bc)]
        print(f"kotlinc {KOTLIN} + compose plugin; {len(libs)} library jars; {len(srcs)} sources")
        rc = subprocess.run(cmd, cwd=ROOT).returncode
    what = "all modules" if everything else "M1 slice"
    print(f"[{'PASS' if rc == 0 else 'FAIL'}] Android compile check, {what} (not a Gradle build)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
