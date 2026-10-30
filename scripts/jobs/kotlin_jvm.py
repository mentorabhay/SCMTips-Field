#!/usr/bin/env python3
"""Kotlin JVM unit-test job (rule 2.1).

Compiles the pure-JVM Kotlin sources of the modules listed in apps/field-android/jvm-unit.json with
the real Kotlin compiler shipped inside the Gradle distribution, then runs their JUnit 4 tests with
the real JUnitCore. Writes reports/junit-kotlin-jvm.xml for the trace job.

This job does not replace the Gradle Android build (scripts/jobs/android.py); it exists because the
Android build needs dependency repositories that some environments cannot reach. A missing compiler,
JUnit jar or JDK is a FAIL, never a skip.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ANDROID = ROOT / "apps" / "field-android"
CONFIG = ANDROID / "jvm-unit.json"
REPORT = ROOT / "reports" / os.environ.get("KOTLIN_JVM_REPORT", "junit-kotlin-jvm.xml")
RUNNER = ROOT / "tools" / "kotlin_jvm" / "JUnitXmlRunner.java"

COMPILER_JARS = (
    "kotlin-compiler-embeddable",
    "kotlin-stdlib",
    "kotlin-script-runtime",
    "kotlin-reflect",
    "kotlin-daemon-embeddable",
    "trove4j",
    "annotations",
    "kotlinx-coroutines-core-jvm",
)
CLASSPATH_JARS = (
    "kotlin-stdlib",
    "kotlinx-coroutines-core-jvm",
    "kotlinx-serialization-core-jvm",
    "kotlinx-serialization-json-jvm",
    "junit",
    "hamcrest-core",
)
TEST_CLASS_RE = re.compile(r"^(?:internal\s+)?class\s+(\w+)", re.M)
PACKAGE_RE = re.compile(r"^package\s+([\w.]+)", re.M)


def gradle_lib() -> Path:
    env = os.environ.get("GRADLE_HOME")
    candidates = [Path(env) / "lib"] if env else []
    exe = shutil.which("gradle")
    if exe:
        candidates.append(Path(exe).resolve().parent.parent / "lib")
    for c in candidates:
        if (c / "plugins").is_dir() or any(c.glob("kotlin-compiler-embeddable-*.jar")):
            return c
    raise SystemExit("[FAIL] no Gradle distribution found (set GRADLE_HOME or put gradle on PATH)")


def find_jar(lib: Path, stem: str) -> Path:
    pat = re.compile(rf"^{re.escape(stem)}-\d[\w.\-]*\.jar$")
    hits = sorted(p for d in (lib, lib / "plugins") if d.is_dir() for p in d.iterdir() if pat.match(p.name))
    if not hits:
        raise SystemExit(f"[FAIL] {stem}-*.jar not found under {lib}")
    return hits[-1]


def collect(cfg: dict[str, object]) -> tuple[list[Path], list[Path]]:
    excluded = cfg["android_bound"]
    assert isinstance(excluded, dict)
    for rel in excluded:
        if not (ANDROID / rel).exists():
            raise SystemExit(f"[FAIL] jvm-unit.json excludes a file that does not exist: {rel}")
    modules = cfg["modules"]
    assert isinstance(modules, list)
    only = os.environ.get("KOTLIN_JVM_MODULES")
    wanted = {m.strip() for m in only.split(",") if m.strip()} if only else {str(m) for m in modules}
    unknown = wanted - {str(m) for m in modules}
    if unknown:
        raise SystemExit(f"[FAIL] KOTLIN_JVM_MODULES names modules not in jvm-unit.json: {sorted(unknown)}")
    main: list[Path] = []
    test: list[Path] = []
    for m in modules:
        mdir = ANDROID / str(m)
        if not mdir.is_dir():
            raise SystemExit(f"[FAIL] jvm-unit.json lists a missing module: {m}")
        for kind, bucket in (("main", main), ("test", test)):
            if kind == "test" and str(m) not in wanted:
                continue  # KOTLIN_JVM_MODULES (local iteration only) narrows tests, never main sources
            for p in sorted((mdir / "src" / kind / "kotlin").rglob("*.kt")):
                if p.relative_to(ANDROID).as_posix() not in excluded:
                    bucket.append(p)
    return main, test


def test_classes(files: list[Path]) -> list[str]:
    out: list[str] = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        if "@Test" not in text:
            continue
        pkg = PACKAGE_RE.search(text)
        for name in TEST_CLASS_RE.findall(text):
            body_start = text.find(f"class {name}")
            nxt = TEST_CLASS_RE.search(text, body_start + 1)
            segment = text[body_start : nxt.start() if nxt else len(text)]
            if "@Test" in segment:
                out.append(f"{pkg.group(1)}.{name}" if pkg else name)
    return out


def run(cmd: list[str]) -> int:
    print("$ " + " ".join(cmd[:6]) + (f" ... (+{len(cmd) - 6} args)" if len(cmd) > 6 else ""), flush=True)
    return subprocess.run(cmd, cwd=ROOT).returncode


def main() -> int:
    java, javac = shutil.which("java"), shutil.which("javac")
    if not java or not javac:
        print("[FAIL] java/javac not on PATH")
        return 1
    lib = gradle_lib()
    compiler_cp = os.pathsep.join(str(find_jar(lib, j)) for j in COMPILER_JARS)
    cp = [find_jar(lib, j) for j in CLASSPATH_JARS]
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    main_src, test_src = collect(cfg)
    classes = test_classes(test_src)
    if not classes:
        print("[FAIL] no JUnit test classes found")
        return 1
    print(f"tool: kotlinc from {find_jar(lib, 'kotlin-compiler-embeddable').name}; {find_jar(lib, 'junit').name}")
    subprocess.run([java, "-cp", compiler_cp, "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler", "-version"], cwd=ROOT)
    print(f"sources: {len(main_src)} main, {len(test_src)} test; test classes: {len(classes)}")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "classes"
        rc = run(
            [java, "-cp", compiler_cp, "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler", "-no-stdlib", "-no-reflect",
             "-jvm-target", "17", "-Werror" if os.environ.get("KOTLIN_JVM_WERROR") else "-nowarn",
             "-cp", os.pathsep.join(map(str, cp)), "-d", str(out)]
            + [str(p) for p in main_src + test_src]
        )
        if rc != 0:
            print("[FAIL] Kotlin compilation failed")
            return 1
        runner_out = Path(tmp) / "runner"
        rc = run([javac, "-d", str(runner_out), "-cp", os.pathsep.join(map(str, cp)), str(RUNNER)])
        if rc != 0:
            print("[FAIL] could not compile the JUnit runner")
            return 1
        run_cp = os.pathsep.join([str(out), str(runner_out)] + [str(p) for p in cp])
        rc = run([java, "-cp", run_cp, "JUnitXmlRunner", str(REPORT)] + classes)
    print(f"[{'PASS' if rc == 0 else 'FAIL'}] kotlin-jvm tests (report: {REPORT})")
    return rc


if __name__ == "__main__":
    sys.exit(main())
