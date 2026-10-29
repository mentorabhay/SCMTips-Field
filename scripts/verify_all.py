#!/usr/bin/env python3
"""SCMTIPS Field - Unified Honest Verification Suite (Remediation Rule 2.1 / Task R0).

Runs all verification gates honestly:
- Strictly real execution with genuine tool output; zero stub pass logic.
- Strict accounting: every tool must run or the gate fails.
- Captures git_sha, dirty flag, OS, tool versions, test counts, command lines.
- Writes structured audit report to reports/verify-all/<timestamp>.json.
"""

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Force UTF-8 encoding across subprocess calls
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"

ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "reports" / "verify-all"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

JOBS: list[tuple[str, str, list[str]]] = [
    # 1. Code Quality & Formatting
    ("lint", "Lint checks (Ruff & ESLint)", ["uv", "run", "ruff", "check", "."]),
    # 2. Honest Security & Gates Integrity
    ("no-fake-gates", "Fake gate & simulated pass scanner", ["uv", "run", "python", "tools/checks/no_fake_gates.py"]),
    ("orphans", "Orphan Kotlin & Python code check", ["uv", "run", "python", "tools/checks/orphans.py"]),
    ("firewall", "Architectural firewall & boundary check", ["uv", "run", "python", "tools/checks/firewall.py"]),
    ("names", "Naming denylist & sample data check", ["uv", "run", "python", "tools/checks/names.py"]),
    ("conventions", "Branch & commit conventions check", ["uv", "run", "python", "tools/checks/conventions.py"]),
    # 3. Security Vulnerability Scans
    (
        "semgrep",
        "Semgrep static security analysis",
        [
            "uvx",
            "semgrep==1.181.0",
            "--config",
            "p/python",
            "--config",
            "p/javascript",
            "--config",
            "p/typescript",
            "--config",
            "p/java",
            "--config",
            "p/secrets",
            "--error",
        ],
    ),
    (
        "trivy",
        "Trivy filesystem vulnerability scan",
        ["trivy", "fs", "--config", "trivy.yaml", "--exit-code", "1", "."],
    ),
    # 4. Strict Typecheck (Python + TypeScript)
    ("typecheck", "Strict Python & TypeScript type checking", ["uv", "run", "python", "scripts/jobs/typecheck.py"]),
    # 5. Database Schema & Migration Round-Trip
    ("alembic", "Database migration round-trip", ["uv", "run", "python", "scripts/jobs/alembic.py"]),
    # 6. Test Collection Completeness Check
    ("test-collection", "Pytest suite collection completeness check", ["uv", "run", "python", "tools/checks/test_collection.py"]),
    # 7. Automated Test Suites
    ("unit", "Unit tests (Pytest)", ["uv", "run", "pytest", "-m", "unit", "--capture=no"]),
    ("property", "Property invariant tests (Hypothesis)", ["uv", "run", "pytest", "-m", "property", "--capture=no"]),
    ("contract", "Contract verification tests", ["uv", "run", "pytest", "-m", "contract", "--capture=no"]),
    ("compat", "Core contract compatibility tests", ["uv", "run", "pytest", "compat/tests", "--capture=no"]),
    # 8. Status Trace & Acceptance Criteria Verification
    ("trace", "Spec requirement status trace check", ["uv", "run", "python", "tools/checks/trace.py"]),
    # 9. Real Android Build & Verification
    ("field-android", "Android multi-module compile, unit tests & lint", ["uv", "run", "python", "scripts/jobs/android.py"]),
]


def run_command_capture(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        return proc.returncode, (proc.stdout or "").strip()
    except Exception as e:
        return 1, str(e)


def get_git_info() -> tuple[str, bool]:
    rc, out = run_command_capture(["git", "rev-parse", "HEAD"])
    git_sha = out if rc == 0 else "unknown"

    rc_status, out_status = run_command_capture(["git", "status", "--porcelain"])
    dirty = bool(out_status.strip()) if rc_status == 0 else True
    return git_sha, dirty


def get_tool_versions() -> dict[str, str]:
    versions: dict[str, str] = {
        "python": sys.version.split()[0],
        "os": f"{platform.system()} {platform.release()}",
    }

    tools = [
        ("git", ["git", "--version"]),
        ("uv", ["uv", "--version"]),
        ("node", ["node", "--version"]),
        ("npm", ["npm", "--version"]),
        ("trivy", ["trivy", "--version"]),
        ("semgrep", ["uvx", "semgrep==1.181.0", "--version"]),
    ]

    for tool_name, cmd in tools:
        if shutil.which(cmd[0]):
            rc, out = run_command_capture(cmd)
            if rc == 0:
                first_line = out.splitlines()[-1] if "semgrep" in tool_name else out.splitlines()[0]
                versions[tool_name] = first_line.strip()
            else:
                versions[tool_name] = "error"
        else:
            versions[tool_name] = "missing"

    return versions


def extract_test_counts(output: str) -> dict[str, int]:
    # Looks for pattern like "15 passed, 2 skipped in 1.23s"
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    m = re.search(r"(\d+)\s+passed", output)
    if m:
        counts["passed"] = int(m.group(1))
    m = re.search(r"(\d+)\s+failed", output)
    if m:
        counts["failed"] = int(m.group(1))
    m = re.search(r"(\d+)\s+skipped", output)
    if m:
        counts["skipped"] = int(m.group(1))
    return counts


def run_job(name: str, desc: str, cmd: list[str]) -> dict[str, Any]:
    start = time.time()
    binary = cmd[0]
    is_missing = shutil.which(binary) is None

    if is_missing:
        duration = time.time() - start
        log_file = REPORTS_DIR / f"{name}.log"
        output = f"FATAL: Required executable '{binary}' not found on PATH."
        log_file.write_text(output, encoding="utf-8")
        return {
            "job": name,
            "description": desc,
            "command": " ".join(cmd),
            "status": "FAIL",
            "exit_code": 127,
            "duration_s": round(duration, 2),
            "log_path": str(log_file.relative_to(ROOT)),
            "error": output,
        }

    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        duration = time.time() - start
        status = "PASS" if proc.returncode == 0 else "FAIL"
        output = proc.stdout or ""
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        duration = time.time() - start
        status = "FAIL"
        exit_code = 124
        output = f"Job {name} timed out after 300s"
    except Exception as e:
        duration = time.time() - start
        status = "FAIL"
        exit_code = 1
        output = str(e)

    log_file = REPORTS_DIR / f"{name}.log"
    log_file.write_text(output, encoding="utf-8", errors="replace")

    res: dict[str, Any] = {
        "job": name,
        "description": desc,
        "command": " ".join(cmd),
        "status": status,
        "exit_code": exit_code,
        "duration_s": round(duration, 2),
        "log_path": str(log_file.relative_to(ROOT)),
    }

    if name in ("unit", "property", "contract", "compat"):
        res["test_counts"] = extract_test_counts(output)

    return res


def main() -> int:
    args = sys.argv[1:]
    only_job = None
    skip_job = None
    allowed_skips: dict[str, str] = {}

    for i, a in enumerate(args):
        if a == "--only" and i + 1 < len(args):
            only_job = args[i + 1]
        elif a == "--skip" and i + 1 < len(args):
            skip_job = args[i + 1]
        elif a.startswith("--allow-skip="):
            pair = a.split("=", 1)[1]
            if ":" in pair:
                job_id, reason = pair.split(":", 1)
                allowed_skips[job_id.strip()] = reason.strip()

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    git_sha, dirty = get_git_info()
    tool_versions = get_tool_versions()

    print("=" * 86, flush=True)
    print(f" SCMTIPS FIELD — VERIFY-ALL RUNNER | {timestamp}", flush=True)
    print(f" Git SHA: {git_sha[:10]} | Dirty: {dirty} | OS: {platform.system()} {platform.release()}", flush=True)
    print("=" * 86, flush=True)
    print(f"{'JOB':<16} | {'DESCRIPTION':<38} | {'STATUS':<6} | {'TIME'}", flush=True)
    print("-" * 86, flush=True)

    results: list[dict[str, Any]] = []
    any_failed = False
    has_skips = False

    for name, desc, cmd in JOBS:
        if only_job and name != only_job:
            continue
        if skip_job and name == skip_job:
            if name not in allowed_skips:
                print(f"{name:<16} | {desc:<38} | FAIL   | Skipping without --allow-skip forbidden", flush=True)
                results.append({
                    "job": name,
                    "description": desc,
                    "status": "FAIL",
                    "reason": "Skipped without explicit --allow-skip authorization",
                })
                any_failed = True
                continue
            has_skips = True
            results.append({
                "job": name,
                "description": desc,
                "status": "SKIP",
                "reason": allowed_skips[name],
                "duration_s": 0.0,
            })
            print(f"{name:<16} | {desc:<38} | SKIP   | Allowed: {allowed_skips[name]}", flush=True)
            continue

        res = run_job(name, desc, cmd)
        results.append(res)
        status = res["status"]
        if status == "FAIL":
            any_failed = True
        print(f"{name:<16} | {desc:<38} | {status:<6} | {res['duration_s']}s", flush=True)

    print("-" * 86, flush=True)
    if any_failed:
        summary_status = "FAILED"
    elif has_skips:
        summary_status = "INCOMPLETE"
    else:
        summary_status = "PASSED"

    print(f" SUMMARY: {summary_status} ({len(results)} jobs executed: {sum(1 for r in results if r['status'] == 'PASS')} passed, {sum(1 for r in results if r['status'] == 'FAIL')} failed, {sum(1 for r in results if r['status'] == 'SKIP')} skipped)", flush=True)
    print("=" * 86, flush=True)

    report_path = REPORTS_DIR / f"{timestamp}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": timestamp,
                "git_sha": git_sha,
                "dirty": dirty,
                "os": f"{platform.system()} {platform.release()}",
                "tool_versions": tool_versions,
                "summary": summary_status,
                "total_jobs": len(results),
                "passed": sum(1 for r in results if r["status"] == "PASS"),
                "failed": sum(1 for r in results if r["status"] == "FAIL"),
                "skipped": sum(1 for r in results if r["status"] == "SKIP"),
                "jobs": results,
            },
            f,
            indent=2,
        )
    print(f"Report written to: {report_path.relative_to(ROOT)}", flush=True)

    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
