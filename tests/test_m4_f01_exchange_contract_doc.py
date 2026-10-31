"""docs/EXCHANGE_CONTRACT.md stays honest about the exchange contract it describes (M4-F01, F6 open-source readiness).

The page is hand-written, so these tests pin what it can get wrong: the pinned contract folder is still the core's
export of 31 Oct 2026, byte for byte; every one of the contract's messages is in the page's table with a schema that
exists; every relative link resolves; every setting it names is one Field really reads (names only, never a value);
and nothing in it looks like a credential.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "EXCHANGE_CONTRACT.md"
CONTRACT = ROOT / "docs" / "integration" / "exchange-contract-v1"
# The core's export of 31 Oct 2026 (README: generated 2026-10-31T09:32:41Z), as committed in 7587b1c: 33 files.
PINNED_FILES = 33
PINNED_FINGERPRINT = "18efcde0b590f5543172653ae0517a5f92b992693e60c9fc825872c142956903"


def _fingerprint(folder: Path) -> tuple[int, str]:
    """SHA-256 over every file's relative path and SHA-256, in path order."""
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    h = hashlib.sha256()
    for p in files:
        rel = p.relative_to(folder).as_posix()
        h.update(rel.encode() + b"\0" + hashlib.sha256(p.read_bytes()).hexdigest().encode() + b"\n")
    return len(files), h.hexdigest()


def test_m4_f01_the_contract_folder_is_the_cores_export_of_31_october_byte_for_byte() -> None:
    assert _fingerprint(CONTRACT) == (PINNED_FILES, PINNED_FINGERPRINT), (
        "docs/integration/exchange-contract-v1 changed: it must stay the core's export, never edited by hand; a new "
        "export is a new pin (and, if the contract changed, a new version folder)"
    )
    readme = (CONTRACT / "README.md").read_text(encoding="utf-8")
    assert "Generated from the SCMTIPS core on 2026-10-31T09:32:41Z" in readme
    doc = DOC.read_text(encoding="utf-8")
    assert "2026-10-31T09:32:41Z" in doc and "scmtips.exchange/v1" in doc


def test_m4_f01_every_message_of_the_contract_is_in_the_table_with_its_schema() -> None:
    contract = json.loads((CONTRACT / "contract.json").read_text(encoding="utf-8"))
    assert contract["contract"] == "scmtips.exchange/v1"
    messages = list(contract["messages"])
    assert len(messages) == 8
    doc = DOC.read_text(encoding="utf-8")
    rows = {m.group(1): m.group(0) for m in re.finditer(r"^\| \[`([a-z_]+)`\]\(([^)]+)\) \|.*$", doc, re.M)}
    assert sorted(rows) == sorted(messages)
    for key in messages:
        schema = CONTRACT / "schemas" / f"{key}.schema.json"
        assert schema.is_file()
        assert f"(integration/exchange-contract-v1/schemas/{key}.schema.json)" in rows[key]
        direction = contract["messages"][key]["x-direction"]
        assert ("to the core" if direction == "in" else "from the core") in rows[key], key
    # the decision outcome is never imported, and the page says so
    assert contract["messages"]["decision_outcome"]["x-file-import"] is False
    assert "**never**" in rows["decision_outcome"]


def test_m4_f01_every_relative_link_resolves() -> None:
    doc = DOC.read_text(encoding="utf-8")
    links = re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", doc)
    assert links
    for link in links:
        if link.startswith(("http://", "https://")):
            continue
        assert (DOC.parent / link).resolve().exists(), link


def test_m4_f01_every_setting_named_is_one_field_reads_and_no_value_is_given() -> None:
    doc = DOC.read_text(encoding="utf-8")
    named = set(re.findall(r"\b((?:FIELD_CORE|ASSISTANT|MODEL_API)_[A-Z_]*[A-Z])\b", doc))
    assert {"FIELD_CORE_BASE_URL", "FIELD_CORE_INVENTORY_FEED_SECRET", "FIELD_CORE_SUPPLY_FEED_SECRET"} <= named
    known = (ROOT / ".env.example").read_text(encoding="utf-8")
    for d in ("services", "connectors", "tools"):
        for p in (ROOT / d).rglob("*.py"):
            if "node_modules" not in p.parts:
                known += p.read_text(encoding="utf-8", errors="ignore")
    for name in sorted(named):
        if name == "FIELD_CORE_SMOKE":  # the FIELD_CORE_SMOKE_* family
            continue
        assert name in known, f"{name} is named in the page but Field never reads it"
        assert not re.search(rf"\b{name}\s*=\s*\S", doc), f"{name} is given a value"


def test_m4_f01_nothing_in_the_page_looks_like_a_credential() -> None:
    doc = DOC.read_text(encoding="utf-8")
    assert not re.search(r"\b[0-9a-f]{32,}\b", doc)  # no digest, key or signature value
    assert not re.search(r"\bey[A-Za-z0-9_-]{20,}\.", doc)  # no JWT
    assert not re.search(r"(?i)password\s*[:=]\s*\S", doc)
    assert "dev-postgres-password" not in doc and "@scmtips.local" not in doc  # no dev credentials or demo accounts
