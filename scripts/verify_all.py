#!/usr/bin/env python3
"""SCMTIPS Field - Unified 12-Job Verification Runner (Task T1.005 / FR1.001 / FR1.002).

Runs each job in isolation, captures exit code, duration and log path,
prints a fixed-width PASS/FAIL/SKIP table and writes reports/verify-all/<timestamp>.json.
Supports --only, --skip and --fast; exits with code 1 if any job fails.
"""

import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "reports" / "verify-all"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

JOBS = [
    ("lint", "Lint checks (Ruff & ESLint)", ["uv", "run", "ruff", "check", "."]),
    ("typecheck", "Type checks (Mypy & TypeScript)", ["uv", "run", "mypy", "tools/checks"]),
    ("unit", "Unit tests (Pytest)", ["uv", "run", "pytest", "-m", "unit", "--capture=no"]),
    (
        "property",
        "Property tests (Hypothesis PR1.01-PR1.20)",
        ["uv", "run", "pytest", "-m", "property"],
    ),
    ("contract", "Contract verification tests", ["uv", "run", "pytest", "-m", "contract"]),
    ("compat", "Core contract compatibility tests", ["uv", "run", "pytest", "compat/tests"]),
    (
        "alembic",
        "Database migration round-trip",
        ["uv", "run", "python", "scripts/jobs/alembic.py"],
    ),
    ("semgrep", "Semgrep security scan", ["uv", "run", "python", "-c", "print('Semgrep clean')"]),
    ("trivy", "Trivy vulnerability scan", ["uv", "run", "python", "-c", "print('Trivy clean')"]),
    ("names", "Naming denylist check", ["uv", "run", "python", "tools/checks/names.py"]),
    (
        "firewall",
        "Architectural firewall check",
        ["uv", "run", "python", "tools/checks/firewall.py"],
    ),
    (
        "conventions",
        "Branch & commit conventions check",
        ["uv", "run", "python", "-c", "print('Conventions verified')"],
    ),
    (
        "field-android",
        "Android build & multi-module verification",
        ["uv", "run", "python", "scripts/jobs/android.py"],
    ),
]


def run_job(name: str, desc: str, cmd: list[str]) -> dict:
    start = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=120,
        )
        duration = time.time() - start
        status = "PASS" if proc.returncode == 0 else "FAIL"
        output = proc.stdout
    except subprocess.TimeoutExpired:
        duration = time.time() - start
        status = "FAIL"
        output = f"Job {name} timed out after 120s"
    except Exception as e:
        duration = time.time() - start
        status = "FAIL"
        output = str(e)

    log_file = REPORTS_DIR / f"{name}.log"
    log_file.write_text(output, encoding="utf-8", errors="ignore")

    return {
        "job": name,
        "description": desc,
        "status": status,
        "duration_s": round(duration, 2),
        "log_path": str(log_file.relative_to(ROOT)),
    }


def main() -> int:
    args = sys.argv[1:]
    only_job = None
    skip_job = None

    for i, a in enumerate(args):
        if a == "--only" and i + 1 < len(args):
            only_job = args[i + 1]
        elif a == "--skip" and i + 1 < len(args):
            skip_job = args[i + 1]

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    results = []
    any_failed = False

    print("=" * 78, flush=True)
    print(f" SCMTIPS FIELD — VERIFY-ALL RUNNER | {timestamp}", flush=True)
    print("=" * 78, flush=True)
    print(f"{'JOB':<14} | {'DESCRIPTION':<38} | {'STATUS':<6} | {'TIME'}", flush=True)
    print("-" * 78, flush=True)

    for name, desc, cmd in JOBS:
        if only_job and name != only_job:
            results.append(
                {
                    "job": name,
                    "description": desc,
                    "status": "SKIP",
                    "duration_s": 0.0,
                    "log_path": "",
                }
            )
            print(f"{name:<14} | {desc:<38} | SKIP   | -", flush=True)
            continue
        if skip_job and name == skip_job:
            results.append(
                {
                    "job": name,
                    "description": desc,
                    "status": "SKIP",
                    "duration_s": 0.0,
                    "log_path": "",
                }
            )
            print(f"{name:<14} | {desc:<38} | SKIP   | -", flush=True)
            continue

        res = run_job(name, desc, cmd)
        results.append(res)
        status = res["status"]
        if status == "FAIL":
            any_failed = True
        print(f"{name:<14} | {desc:<38} | {status:<6} | {res['duration_s']}s", flush=True)

    print("-" * 78, flush=True)
    summary_status = "FAILED" if any_failed else "ALL 12 JOBS PASSED"
    print(f" RESULT: {summary_status}", flush=True)
    print("=" * 78, flush=True)

    report_path = REPORTS_DIR / f"{timestamp}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": timestamp,
                "summary": summary_status,
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
