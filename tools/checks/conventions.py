#!/usr/bin/env python3
"""SCMTIPS Conventions Check (Remediation Rule 2.5 / Task R0.3).

Validates branch naming and commit message format against binding rules:
- Branch names: main, master, or <type>/<description> (feat, fix, docs, chore, remediation)
- Commit messages: must follow conventional commit structure and reference task IDs:
  e.g. feat(phase4-ws4.9): ... (tasks T4.027-T4.028)
  or docs: ...
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

VALID_BRANCH_PATTERNS = [
    r"^(main|master)$",
    r"^(feat|fix|docs|refactor|test|chore|remediation)/[a-zA-Z0-9._-]+$",
]

TASK_ID_PATTERN = re.compile(
    r"(T[1-4]\.\d{3}|WS[1-4]\.\d|R[0-7](\.\d)?|PR[1-4]\.\d{2}|FR[1-4]\.\d{3}|remediation|bootstrap|initial|baseline)",
    re.IGNORECASE,
)

CONVENTIONAL_PREFIX_PATTERN = re.compile(
    r"^(feat|fix|docs|refactor|test|chore|perf|style|build|ci|remediation)(\([a-zA-Z0-9._-]+\))?:\s+.+",
    re.IGNORECASE,
)


def validate_branch_name(branch: str) -> tuple[bool, str]:
    branch = branch.strip()
    if not branch:
        return False, "Branch name is empty"
    for pat in VALID_BRANCH_PATTERNS:
        if re.match(pat, branch):
            return True, "Valid branch name"
    return False, f"Invalid branch name '{branch}'. Expected main or <type>/<description>"


def validate_commit_message(msg: str) -> tuple[bool, str]:
    msg = msg.strip()
    if not msg:
        return False, "Empty commit message"

    first_line = msg.splitlines()[0]

    # Merge commits are allowed
    if first_line.startswith("Merge "):
        return True, "Merge commit accepted"

    # Check conventional prefix
    if not CONVENTIONAL_PREFIX_PATTERN.match(first_line):
        return False, f"Commit message does not match conventional prefix (e.g. feat(scope): ...): '{first_line}'"

    # Check task reference
    if not TASK_ID_PATTERN.search(msg):
        return False, f"Commit message must reference task ID (T*.***, WS*.*, R*.*, PR*.*, FR*.*): '{first_line}'"

    return True, "Commit message valid"


def check_git_history(max_commits: int = 15) -> list[str]:
    violations: list[str] = []

    # Check branch name
    res_b = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    branch = res_b.stdout.strip()
    if branch:
        valid_b, reason_b = validate_branch_name(branch)
        if not valid_b:
            violations.append(f"Branch convention violation: {reason_b}")

    # Check recent commit messages
    res_c = subprocess.run(
        ["git", "log", f"-n{max_commits}", "--pretty=format:%H%x00%B%x00"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    
    entries = res_c.stdout.split("\x00\x00")
    for entry in entries:
        if not entry.strip():
            continue
        parts = entry.split("\x00")
        if len(parts) >= 2:
            sha, msg = parts[0].strip(), parts[1].strip()
            valid_m, reason_m = validate_commit_message(msg)
            if not valid_m:
                violations.append(f"Commit {sha[:8]} convention violation: {reason_m}")

    return violations


def main() -> int:
    violations = check_git_history(max_commits=10)
    if violations:
        print(f"[FAIL] Found {len(violations)} convention violation(s):")
        for v in violations:
            print(f"  - {v}")
        return 1

    print("[PASS] Branch and commit conventions verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
