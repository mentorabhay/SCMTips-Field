"""The submission drafts (docs/submission/: WRITEUP.md, RUN_SCRIPT_3MIN.md, SHOT_LIST.md; M4-F02) and the demo-run page
(docs/DEMO_RUN.md; M4-C17) stay honest about what they describe. They are hand-written, so these tests pin what can
go stale: every relative link resolves; nothing looks like a credential; the ledger counts the write-up quotes are
the ledgers' own; "nothing has been proven on the glasses yet" holds only while the register's glasses rows are
UNVERIFIED (a row turning VERIFIED fails here until the write-up is updated). The demo-run page's beats and
commands are pinned against the orchestrator in tools/dev_stack/tests/test_demo_run.py.
"""

from __future__ import annotations

import collections
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SUB = ROOT / "docs" / "submission"
DOCS = [SUB / "WRITEUP.md", SUB / "RUN_SCRIPT_3MIN.md", SUB / "SHOT_LIST.md", ROOT / "docs" / "DEMO_RUN.md"]


def test_m4_f02_every_relative_link_resolves() -> None:
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8")
        for link in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text):
            if not link.startswith(("http://", "https://")):
                assert (doc.parent / link).resolve().exists(), f"{doc.name}: {link}"
        for m in re.finditer(r"`((?:docs|tools|scripts)/[A-Za-z0-9_./-]+\.(?:md|py|txt|ps1|cmd|sh|yaml))`", text):
            if "core" in text[max(0, m.start() - 8):m.start()]:  # "the core's `docs/...`": a page of the core repo
                continue
            assert (ROOT / m.group(1)).exists(), f"{doc.name} names {m.group(1)}, which does not exist"


def test_m4_f02_nothing_in_the_drafts_looks_like_a_credential() -> None:
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8")
        assert not re.search(r"\b[0-9a-f]{32,}\b", text), doc.name
        assert not re.search(r"\bey[A-Za-z0-9_-]{20,}\.", text), doc.name
        assert not re.search(r"(?i)password\s*[:=]\s*\S", text), doc.name
        assert "dev-postgres-password" not in text and "@scmtips.local" not in text, doc.name


def test_m4_f02_the_ledger_counts_in_the_write_up_are_the_ledgers() -> None:
    counts: collections.Counter[str] = collections.Counter()
    rows = 0
    for n in (1, 2, 3, 4):
        ledger = yaml.safe_load((ROOT / "docs" / "STATUS" / f"phase{n}.yaml").read_text(encoding="utf-8"))
        rows += len(ledger)
        counts.update(str(r["status"]) for r in ledger)
    text = (SUB / "WRITEUP.md").read_text(encoding="utf-8")
    sentence = (f"{rows} rows: {counts['done']} `done`, {counts['partial']} `partial`, {counts['stub']} `stub`,"
                f" {counts['missing']} `missing`")
    assert sentence in re.sub(r"\s+", " ", text), f"the write-up must say: {sentence}"
    for ledger_name in ("m3", "m4"):
        ledger = yaml.safe_load((ROOT / "docs" / "STATUS" / f"{ledger_name}.yaml").read_text(encoding="utf-8"))
        assert all(r["status"] != "done" for r in ledger), (
            f"{ledger_name}.yaml has a done row now: the write-up says every M3 and M4 row is partial")


def test_m4_f02_not_proven_on_the_glasses_holds_while_the_register_says_so() -> None:
    register = (ROOT / "docs" / "META_FIELD.md").read_text(encoding="utf-8")
    glasses_rows = [ln for ln in register.splitlines()
                    if re.match(r"^\| (?:[1-9]|10|25|HW-0[1-6]) \|", ln)]
    assert len(glasses_rows) == 17  # rows 1 to 10, 25 and HW-01 to HW-06
    assert all("UNVERIFIED" in ln for ln in glasses_rows), "a glasses row changed: update the write-up's section 5"
    text = re.sub(r"\s+", " ", (SUB / "WRITEUP.md").read_text(encoding="utf-8"))
    assert "nothing has been proven on the glasses yet" in text
    for label in ("SAMPLE", "SIMULATED", "UNVERIFIED", "VERIFIED access"):
        assert label in text, label
