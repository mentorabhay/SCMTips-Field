"""Run the Android app's own HTTP client + job runner (Kotlin, compiled for the JVM) on a receive job against the
live field-test stack: proves the phone's code path end to end without a phone or glasses.

    uv run python -m tools.dev_stack.stack up
    uv run python -m tools.android_check.drive_backend

Compiles app/net/FieldHttp.kt, app/slice/*.kt, app/jobs/*.kt, core-common, core-voice, core-wearables, core-safety and the
driver app/src/test/.../slice/BackendDriver.kt with Kotlin 2.2.21 against real OkHttp/kotlinx jars,
creates a fresh inbound delivery in erp-sim, pairs like the QR does, and requires "RESULT: PASS"
(the erp.posted live event for the posted goods receipt).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

from tools.android_check.compile_check import ANDROID, COMPILER, ROOT, jar
from tools.dev_stack.stack import (
    STATE,
    apply_ports,
    create_inbound_delivery,
    ensure_demo_site,
    load_env,
    local,
    pairing_payload,
)

RUNTIME = [
    "com.squareup.okhttp3:okhttp:4.12.0", "com.squareup.okio:okio-jvm:3.6.0",
    "org.jetbrains.kotlinx:kotlinx-serialization-json-jvm:1.9.0",
    "org.jetbrains.kotlinx:kotlinx-serialization-core-jvm:1.9.0",
]
APP = ANDROID / "app" / "src"
SOURCES = [*sorted((APP / "main/kotlin/com/scmtips/field/app/net").glob("*.kt")),
           *sorted((APP / "main/kotlin/com/scmtips/field/app/slice").glob("*.kt")),
           *sorted((APP / "main/kotlin/com/scmtips/field/app/jobs").glob("*.kt")),
           APP / "test/kotlin/com/scmtips/field/app/slice/BackendDriver.kt"]


def main() -> int:
    compiler = [jar(*c.split(":")) for c in COMPILER]
    runtime = [jar(*c.split(":")) for c in RUNTIME]
    if None in compiler or None in runtime:
        print("[FAIL] could not download the compiler or runtime jars")
        return 1
    stdlib, coroutines = compiler[1], compiler[-1]
    srcs = [str(p) for p in SOURCES]
    for m in ("core-common", "core-voice", "core-wearables", "core-safety"):
        srcs += [str(p) for p in sorted((ANDROID / m / "src/main/kotlin").rglob("*.kt"))]
    load_env()
    apply_ports()  # the stack moves off busy ports (var/dev_stack_ports.json)
    state = ensure_demo_site(json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {})
    deliv = create_inbound_delivery(3)
    tok = httpx.post(local("fake-core") + "/api/v1/auth/token", json={
        "principal_id": "jvm-driver", "tenant_id": state["tenant"], "roles": ["field.operator"],
        "site_ids": [state["site"]], "ttl_seconds": 1800}, timeout=5).raise_for_status().json()["access_token"]
    payload = pairing_payload(local("field-api"), tok, state["tenant"], state["site"], state["site_name"])
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "classes"
        cp = os.pathsep.join(map(str, [stdlib, coroutines, *runtime]))
        rc = subprocess.run(["java", "-cp", os.pathsep.join(map(str, compiler)), "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
                             "-no-stdlib", "-no-reflect", "-jvm-target", "17", "-cp", cp, "-d", str(out), *srcs], cwd=ROOT).returncode
        if rc != 0:
            print("[FAIL] driver did not compile")
            return 1
        res = subprocess.run(["java", "-cp", os.pathsep.join([str(out), cp]), "com.scmtips.field.app.slice.BackendDriver",
                              payload, deliv], cwd=ROOT, capture_output=True, text=True, timeout=180)
    print(res.stdout)
    ok = "RESULT: PASS" in res.stdout
    if not ok:
        print(res.stderr[-2000:])
    print(f"[{'PASS' if ok else 'FAIL'}] app HTTP client + job runner (receive) against the live stack (delivery {deliv})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
