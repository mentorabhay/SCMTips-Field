#!/usr/bin/env bash
# List every lint error and warning (file:line id message) from the XML reports, so the
# published logs show all of them, not just Gradle's "first failure" line.
# Exit status: 1 if any report has an Error/Fatal issue, 2 if no report was found.
set -uo pipefail
reports=$(find . -path '*/build/reports/lint-results-debug.xml' 2>/dev/null)
if [ -z "$reports" ]; then echo "no lint XML report found"; exit 2; fi
python3 - $reports <<'PY'
import sys, xml.etree.ElementTree as ET
errors = 0
for path in sys.argv[1:]:
    root = ET.parse(path).getroot()
    print(f"== {path} (lint {root.get('version', '?')})")
    for issue in root.iter("issue"):
        sev = issue.get("severity", "?")
        loc = issue.find("location")
        where = f"{loc.get('file')}:{loc.get('line', '?')}" if loc is not None else "?"
        print(f"{sev:8} {issue.get('id')}  {where}\n         {issue.get('message')}")
        if sev in ("Error", "Fatal"):
            errors += 1
print(f"lint errors: {errors}")
sys.exit(1 if errors else 0)
PY
