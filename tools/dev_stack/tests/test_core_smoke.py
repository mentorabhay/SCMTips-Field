"""The real-core smokes (tools/dev_stack/core_smoke.py, M4-C13): the pieces that do not need a running core.

The smokes themselves run against the SCMTIPS core (`stack smoke --core` / `--approver` with FIELD_CORE_TARGET=core);
here: the RFC 6238 code for a strict step-up, the settings they need, how the code map names the core's PO line, how
the core's on-hand is read, and that FIELD_CORE_TARGET=core routes to them and never to the stand-in's dev helpers.
"""

from __future__ import annotations

import argparse
import base64
import inspect
from types import MappingProxyType
from typing import Any

import pytest
from field_worker.core_feeds.codes import CodeMap

from tools.dev_stack import core_smoke, stack


class _Web:
    """A test double of core_smoke.CoreWeb: pages of rows per path."""

    def __init__(self, rows: dict[str, list[dict[str, Any]]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, path: str, **params: Any) -> Any:
        self.calls.append((path, params))
        items = self.rows.get(path, [])  # no search: like a core that ignores q, every row comes back
        return {"items": items, "next_cursor": None, "has_more": False, "total": len(items)}


def _codes(**kw: dict[str, str]) -> CodeMap:
    return CodeMap(MappingProxyType(kw.get("materials", {})), MappingProxyType(kw.get("locations", {})),
                   MappingProxyType(kw.get("purchase_orders", {})))


LINES = [
    {"kind": "PO", "ref": "PO-26-1001", "item_code": "CP-203", "location_code": "PLANT-GOA", "qty": "6000.0000",
     "status": "in_transit", "updated_at": "2026-10-31T16:59:52Z"},
    {"kind": "PO", "ref": "PO-26-1003", "item_code": "CP-208", "location_code": "PLANT-GOA", "qty": "150.0000",
     "status": "open", "updated_at": "2026-10-31T16:59:52Z"},
]


def test_m4_c13_totp_is_rfc6238() -> None:
    secret = base64.b32encode(b"12345678901234567890").decode()  # RFC 6238 appendix B, SHA-1
    assert core_smoke.totp_now(secret, at=59) == "287082"
    assert core_smoke.totp_now(secret, at=1111111109) == "081804"
    assert core_smoke.totp_now(secret.lower().rstrip("="), at=1234567890) == "005924"


def test_m4_c13_member_settings_are_named_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIELD_CORE_SMOKE_APPROVER", raising=False)
    monkeypatch.delenv("FIELD_CORE_SMOKE_APPROVER_PASSWORD", raising=False)
    with pytest.raises(stack.SmokeFailure, match="FIELD_CORE_SMOKE_APPROVER and FIELD_CORE_SMOKE_APPROVER_PASSWORD"):
        core_smoke.member("APPROVER")
    monkeypatch.setenv("FIELD_CORE_SMOKE_APPROVER", "approver1@scmtips.local")
    monkeypatch.setenv("FIELD_CORE_SMOKE_APPROVER_PASSWORD", "dev-value")
    assert core_smoke.member("APPROVER") == ("approver1@scmtips.local", "dev-value")
    monkeypatch.delenv("FIELD_CORE_BASE_URL", raising=False)
    with pytest.raises(stack.SmokeFailure, match="FIELD_CORE_BASE_URL"):
        core_smoke.core_base()


def test_m4_c13_the_code_map_names_the_cores_po_line(monkeypatch: pytest.MonkeyPatch) -> None:
    web = _Web({"/v1/open-supply": LINES})
    codes = _codes(materials={"SAMPLE-MAT-0001": "CP-203", "SAMPLE-MAT-0003": "CP-208"},
                   locations={"1020": "PLANT-GOA", "1020/101A": "PLANT-GOA-RM"},
                   purchase_orders={"4500261001": "PO-26-1001", "4500261003": "PO-26-1003"})
    monkeypatch.delenv("FIELD_CORE_SMOKE_PO", raising=False)
    m = core_smoke.mapped_line(codes, web)
    assert (m["erp_po"], m["ref"], m["material"], m["plant"], m["item"]) == (
        "4500261001", "PO-26-1001", "SAMPLE-MAT-0001", "1020", "CP-203")
    monkeypatch.setenv("FIELD_CORE_SMOKE_PO", "4500261003")
    m = core_smoke.mapped_line(codes, web)
    assert (m["ref"], m["material"], m["line"]["status"]) == ("PO-26-1003", "SAMPLE-MAT-0003", "open")
    monkeypatch.setenv("FIELD_CORE_SMOKE_PO", "4599999999")
    with pytest.raises(stack.SmokeFailure, match="not in FIELD_CORE_CODE_MAP"):
        core_smoke.mapped_line(codes, web)
    monkeypatch.delenv("FIELD_CORE_SMOKE_PO")
    with pytest.raises(stack.SmokeFailure, match="no single erp-sim material maps to CP-203"):
        core_smoke.mapped_line(_codes(locations={"1020": "PLANT-GOA"},
                                      purchase_orders={"4500261001": "PO-26-1001"}), web)
    with pytest.raises(stack.SmokeFailure, match="no purchase_orders entry"):
        core_smoke.mapped_line(_codes(), web)


def test_m4_c13_the_cores_on_hand_is_its_latest_count() -> None:
    """The core keeps one inventory row per (item, location, as_of): a GR's row of today sits next to the older count."""
    web = _Web({"/v1/inventory": [
        {"item_code": "CP-203", "location_code": "PLANT-GOA", "as_of": "2026-10-19", "on_hand_qty": "3600.0000"},
        {"item_code": "CP-203", "location_code": "PLANT-GOA", "as_of": "2026-10-31", "on_hand_qty": "9600.0000"},
        {"item_code": "CP-203", "location_code": "DC-MIL", "as_of": "2026-11-01", "on_hand_qty": "1.0000"}]})
    assert core_smoke.core_on_hand(web, "CP-203", "PLANT-GOA") == 9600.0
    assert core_smoke.core_on_hand(web, "RM-307", "PLANT-GOA") is None


def test_m4_c13_core_target_runs_the_real_core_smokes_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(stack, "load_env", lambda: {})
    monkeypatch.setattr(stack, "apply_ports", lambda: None)
    def warehouse(s: dict[str, Any]) -> dict[str, Any]:
        calls.append("stand-in warehouse")
        return s

    monkeypatch.setattr(stack, "ensure_warehouse", warehouse)
    monkeypatch.setattr(core_smoke, "smoke_core_real", lambda api, st, w: calls.append(f"core {api} {w}"))
    monkeypatch.setattr(core_smoke, "smoke_approver_real", lambda api, st, w: calls.append(f"approver {api} {w}"))
    monkeypatch.setenv("FIELD_CORE_TARGET", "core")
    ns = argparse.Namespace(api="http://127.0.0.1:8020", wait=7.0, all=False, home=False, core=True, approver=False)
    assert stack.cmd_smoke(ns) == 0
    ns.core, ns.approver = False, True
    assert stack.cmd_smoke(ns) == 0
    assert calls == ["core http://127.0.0.1:8020 7.0", "approver http://127.0.0.1:8020 7.0"]

    def fail(api: str, st: dict[str, Any], w: float) -> None:
        raise stack.SmokeFailure("the core said no")

    monkeypatch.setattr(core_smoke, "smoke_approver_real", fail)
    assert stack.cmd_smoke(ns) == 1
    src = inspect.getsource(core_smoke)
    assert "/_standin/" not in src and "_core_token(" not in src  # no stand-in helper, no fake-core token
