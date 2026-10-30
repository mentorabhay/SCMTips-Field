"""docs/META_FIELD.md structure and evidence honesty (TC1.169 / T1.066 / FR1.058).

C0 rewrite (review §3.14): the previous test asserted the presence of words such as
"VERIFIED" and a spike path. It now enforces the exit criterion: at least 15 capability
rows, each marked VERIFIED, UNVERIFIED or BLOCKED; every VERIFIED row must cite an
existing committed evidence path; decision D1.04 is recorded.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
DOC_PATH = ROOT / "docs" / "META_FIELD.md"
STATUS_RE = re.compile(r"\*\*(VERIFIED|UNVERIFIED|BLOCKED)\b")


def _capability_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells and cells[0].isdigit():
            rows.append(cells)
    return rows


@pytest.mark.property
def test_meta_field_structure_and_decision():
    content = DOC_PATH.read_text(encoding="utf-8")
    rows = _capability_rows(content)
    assert len(rows) >= 15, f"need >= 15 capability rows, found {len(rows)}"
    for cells in rows:
        statuses = STATUS_RE.findall(" ".join(cells))
        assert statuses, f"row {cells[0]} has no VERIFIED/UNVERIFIED/BLOCKED status"
        if statuses[0] == "VERIFIED":
            paths = re.findall(r"`([\w./-]+\.\w+)`", cells[-1])
            assert paths and all((ROOT / p).exists() for p in paths), (
                f"row {cells[0]} is VERIFIED without an existing committed evidence path"
            )
    assert "Decision D1.04" in content
