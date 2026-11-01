"""The real-core smokes (tools/dev_stack/core_smoke.py, M4-C13): the pieces that do not need a running core.

The smokes themselves run against the SCMTIPS core (`stack smoke --core` / `--approver` with FIELD_CORE_TARGET=core);
here: the RFC 6238 code for a strict step-up, the settings they need, how the code map names the core's PO line, how
the core's on-hand is read, and that FIELD_CORE_TARGET=core routes to them and never to the stand-in's dev helpers.
"""

from __future__ import annotations

import argparse
import base64
import csv
import inspect
import io
import json
from types import MappingProxyType
from typing import Any

import httpx
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


def test_m4_c14_export_mode_receives_the_cores_own_po_without_a_code_map(monkeypatch: pytest.MonkeyPatch) -> None:
    """erp-sim seeded from the core's export holds the core's POs under their own refs: no mapping is involved."""
    received = {**LINES[0], "status": "received"}
    web = _Web({"/v1/open-supply": [received, LINES[1], {**LINES[1], "kind": "WO", "ref": "WO-26-2001"}]})
    monkeypatch.delenv("FIELD_CORE_SMOKE_PO", raising=False)
    assert core_smoke.export_line(web, set()) is None  # erp-sim holds none of them: code-map mode
    m = core_smoke.export_line(web, {"PO-26-1001", "PO-26-1003"})
    assert m is not None
    assert (m["erp_po"], m["ref"], m["material"], m["plant"], m["item"], m["export"]) == (
        "PO-26-1003", "PO-26-1003", "CP-208", "PLANT-GOA", "CP-208", True)  # the first line not received yet
    monkeypatch.setenv("FIELD_CORE_SMOKE_PO", "PO-26-1001")
    m = core_smoke.export_line(web, {"PO-26-1001", "PO-26-1003"})
    assert m is not None and (m["ref"], m["line"]["status"]) == ("PO-26-1001", "received")
    monkeypatch.setenv("FIELD_CORE_SMOKE_PO", "PO-26-1009")  # erp-sim holds it, the core has no such line
    with pytest.raises(stack.SmokeFailure, match="FIELD_CORE_SMOKE_PO PO-26-1009"):
        core_smoke.export_line(web, {"PO-26-1001", "PO-26-1003", "PO-26-1009"})
    monkeypatch.setenv("FIELD_CORE_SMOKE_PO", "4500261003")  # a code-map PO number: code-map mode decides
    assert core_smoke.export_line(web, {"PO-26-1001", "PO-26-1003"}) is None


# --- M4-C16: smoke --approver --scenario (the core's SAMPLE scenario pack, Q13) -------------------------------------

def _pack(tmp: Any, transport: str = "signal_file") -> Any:
    """A scenario pack folder like the core's samples/scenarios: a manifest and one SIMULATED signal message."""
    row = {"external_id": "SAMPLE-SCN-01", "title": "Export licence checks hold motor shipments (SIMULATED)",
           "summary": "SIMULATED scenario, with a comma.", "url": "", "event_at": "2026-11-03T06:00:00Z",
           "source_name": "SAMPLE market feed", "category": "export_control", "severity": 4, "countries": [],
           "corridors": [], "supplier_codes": ["SUP-S02"], "supplier_names": ["Supplier S-02"],
           "site_codes": ["SS-SZX-02"], "item_codes": ["CP-204", "CP-206"]}
    (tmp / "scenarios.json").write_text(json.dumps({"pack": "scmtips.scenario-pack/v1", "scenarios": [
        {"name": "magnet-export-curbs", "file": "m.signal.json", "transport": transport, "polished": True}]}))
    (tmp / "m.signal.json").write_text(json.dumps({"contract": "scmtips.exchange/v1", "message": "signal",
                                                    "message_id": "x", "simulated": True, "rows": [row]}))
    return tmp


def test_m4_c16_the_scenario_is_sent_as_the_cores_signals_workbook(monkeypatch: pytest.MonkeyPatch,
                                                                     tmp_path: Any) -> None:
    monkeypatch.setenv("FIELD_CORE_SCENARIOS_DIR", str(_pack(tmp_path)))
    msg = core_smoke.scenario_message("magnet-export-curbs")
    data, title = core_smoke.scenario_csv(msg, "run1", now=1_793_000_000)
    assert title == "Export licence checks hold motor shipments (SIMULATED)"
    rows = list(csv.DictReader(io.StringIO(data.decode())))
    assert len(rows) == 1
    r = rows[0]
    assert r["external_id"] == "SAMPLE-SCN-01-run1"  # a new article for the core, every run
    assert r["event_at"] == "2026-10-26T07:33:20Z"  # now, so the core's staleness rule passes
    assert r["item_codes"] == "CP-204;CP-206" and r["supplier_codes"] == "SUP-S02"  # the core's list separator
    assert r["summary"] == "SIMULATED scenario, with a comma." and r["countries"] == ""
    assert core_smoke.scenario_csv(msg, "run2")[0] != data


def test_m4_c16_the_scenario_needs_the_cores_checkout_and_a_workbook(monkeypatch: pytest.MonkeyPatch,
                                                                       tmp_path: Any) -> None:
    monkeypatch.delenv("FIELD_CORE_SCENARIOS_DIR", raising=False)
    with pytest.raises(core_smoke.SmokeFailure, match="FIELD_CORE_SCENARIOS_DIR"):
        core_smoke.scenario_message("magnet-export-curbs")
    monkeypatch.setenv("FIELD_CORE_SCENARIOS_DIR", str(_pack(tmp_path, transport="test_inject")))
    with pytest.raises(core_smoke.SmokeFailure, match="not a signals workbook"):
        core_smoke.scenario_message("magnet-export-curbs")
    with pytest.raises(core_smoke.SmokeFailure, match="no 'nope'"):
        core_smoke.scenario_message("nope")


def test_m4_c16_scenario_only_with_the_approver_against_the_real_core(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(stack, "load_env", lambda: {})
    monkeypatch.setattr(stack, "apply_ports", lambda: None)
    monkeypatch.setattr(core_smoke, "smoke_approver_real",
                        lambda api, st, w, scenario=None: calls.append(f"approver {scenario}"))
    ns = argparse.Namespace(api="http://127.0.0.1:8020", wait=7.0, all=False, home=False, core=False, approver=True,
                            scenario="magnet-export-curbs")
    monkeypatch.setenv("FIELD_CORE_TARGET", "standin")
    assert stack.cmd_smoke(ns) == 1  # the stand-in has no scenario pack: refused, never skipped silently
    ns.approver = False
    monkeypatch.setenv("FIELD_CORE_TARGET", "core")
    assert stack.cmd_smoke(ns) == 1
    ns.approver = True
    assert stack.cmd_smoke(ns) == 0
    assert calls == ["approver magnet-export-curbs"]



def test_m4_c18_a_secure_session_cookie_is_sent_to_a_hosted_core_over_its_internal_http_address(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """VM-1: the core's cookie is Secure (LR_COOKIE_SECURE) and the ops image calls http://api:8000."""
    seen: list[str | None] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/auth/login":
            return httpx.Response(200, json={"mfa_required": False},
                                  headers={"set-cookie": "__Host-lr_session=tok123; Path=/; HttpOnly; Secure"})
        seen.append(req.headers.get("cookie"))
        return httpx.Response(200, json={"items": []})

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv("FIELD_CORE_SMOKE_PLANNER", "planner@sample.test")
    monkeypatch.setenv("FIELD_CORE_SMOKE_PLANNER_PASSWORD", "pw")
    web = core_smoke.CoreWeb("http://api:8000", "PLANNER")
    assert web.get("/v1/inventory") == {"items": []}
    assert seen == ["__Host-lr_session=tok123"]
