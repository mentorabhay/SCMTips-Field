"""C3 authenticity check API (M5-T04, M5-T07): verdicts through the API, the first check, the two-step visual seal
check, idempotency, site and permission rules, RLS, and an unreachable or unconfigured maker."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth.jwt import Principal
from field_api.authenticity import service
from field_api.authenticity.oem import checker_ref, get_oem_port, sim_url
from field_api.authenticity.seal import VisualPorts, get_visual_ports
from field_api.authenticity.service import CheckIn, create_check
from field_oem.real.adapter import RealOemAdapter
from field_oem_testing.memory import MemoryOem


def test_m5_t04_genuine_new_then_same_checker_then_another_checker(
        client: TestClient, env: dict[str, Any], h: SimpleNamespace, ai_off: None) -> None:
    r = h.check(client, env["op"], env["new"])
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["verdict"] == "GENUINE_NEW" and c["rule"] == "R14" and c["final"] is True and c["tamper"] is None
    assert c["say"] == "Code is genuine. This unit is new: it was never activated or returned."
    assert c["signals"]["code"]["status"] == "valid" and c["signals"]["code"]["oem"] == "kestrel-sample"
    assert c["signals"]["registry"]["status"] == "found"
    assert [e["type"] for e in c["signals"]["registry"]["events"]] == ["manufactured", "shipped_to_seller", "delivered"]
    assert c["signals"]["first_check"]["status"] == "first" and c["signals"]["visual"]["status"] == "none"
    assert c["site_id"] == env["site"] and c["checked_by"] == "op-c3" and c["say_next"] is None
    assert c["evidence_url"] == f"/v1/authenticity/checks/{c['check_id']}/evidence"
    again = h.check(client, env["op"], env["new"]).json()
    assert again["verdict"] == "GENUINE_NEW" and again["signals"]["first_check"]["status"] == "same_checker"
    other = h.check(client, env["op2"], env["new"]).json()
    assert other["verdict"] == "CANNOT_VERIFY" and other["rule"] == "R13"
    assert "first_check:other_checker" in other["reasons"]
    today = datetime.now(UTC)
    assert other["say"] == (f"Code is genuine, but it was first checked on {today.day} {today.strftime('%B')} by "
                            "someone else. A printed code can be copied, so I cannot verify this unit.")


def test_m5_t04_returned_unit_says_the_contract_example(client: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                                         ai_off: None) -> None:
    c = h.check(client, env["op"], env["returned"]).json()
    assert c["verdict"] == "RETURNED_REFURBISHED" and c["rule"] == "R11"
    assert c["reasons"] == ["history:activated", "history:returned"]
    assert c["say"] == ("Code is genuine. But this unit was activated on 12 October and returned on 20 October. "
                        "It is not a new unit.")
    assert c["signals"]["registry"]["activated_at"] == "2026-10-12"
    assert c["signals"]["registry"]["returned_at"] == "2026-10-20"
    a = h.check(client, env["op"], env["activated"]).json()
    assert a["verdict"] == "GENUINE_PREVIOUSLY_ACTIVATED" and a["rule"] == "R12"
    assert a["say"] == "Code is genuine. But this unit was activated on 12 October. It is not a new unit."


def test_m5_t04_counterfeit_and_unreadable_codes(client: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                                 oem: MemoryOem, ai_off: None) -> None:
    f = h.check(client, env["op"], env["forged"]).json()
    assert f["verdict"] == "LIKELY_COUNTERFEIT" and f["rule"] == "R6" and f["reasons"] == ["code:bad_signature"]
    assert f["say"] == "This code is not signed by the maker. This is likely a counterfeit."
    assert f["signals"]["registry"]["status"] == "not_asked"
    assert f["signals"]["first_check"]["status"] == "not_recorded"
    assert oem.checks == []  # a code that did not verify never reaches the registry
    junk = h.check(client, env["op"], "https://example.invalid/not-a-seal").json()
    assert junk["verdict"] == "CANNOT_VERIFY" and junk["rule"] == "R1"
    assert junk["say"] == "I cannot verify this code. It is not a seal code."
    prefix, kid, payload, sig = env["new"].split(".")
    unknown = h.check(client, env["op"], f"{prefix}.{'0' * 16}.{payload}.{sig}").json()
    assert unknown["verdict"] == "LIKELY_COUNTERFEIT" and unknown["rule"] == "R5"


def test_m5_t04_unknown_unit_and_sku_mismatch_cannot_verify(client: TestClient, env: dict[str, Any],
                                                           h: SimpleNamespace, oem: MemoryOem, ai_off: None) -> None:
    code = oem.add_unit("KSO-GONE-0001")
    del oem.units["KSO-GONE-0001"]
    gone = h.check(client, env["op"], code).json()
    assert gone["verdict"] == "CANNOT_VERIFY" and gone["rule"] == "R9"
    assert gone["say"] == "I cannot verify this code. The maker has no record of this unit."
    code2 = oem.add_unit("KSO-SKU-0001", sku="KSO-BIN-842")
    oem.units["KSO-SKU-0001"].sku = "KSO-SCOPE-60"
    m = h.check(client, env["op"], code2).json()
    assert m["verdict"] == "CANNOT_VERIFY" and m["rule"] == "R10" and m["signals"]["registry"]["status"] == "sku_mismatch"


def test_m5_t04_unreachable_or_unconfigured_maker_is_a_verdict_not_an_error(
        client: TestClient, env: dict[str, Any], h: SimpleNamespace, oem: MemoryOem, ai_off: None) -> None:
    oem.unreachable = True
    r = h.check(client, env["op"], env["new"])
    assert r.status_code == 200 and r.json()["rule"] == "R4" and r.json()["reasons"] == ["oem:unavailable"]
    app.dependency_overrides[get_oem_port] = RealOemAdapter
    try:
        real = h.check(client, env["op"], env["new"]).json()
    finally:
        app.dependency_overrides[get_oem_port] = lambda: oem
    assert real["verdict"] == "CANNOT_VERIFY" and real["rule"] == "R3" and real["reasons"] == ["oem:not_configured"]
    assert real["say"] == "I cannot verify this code. The maker's records cannot be reached."


def test_m5_t04_visual_check_two_steps_flags_tape_over_the_seal(
        client: TestClient, env: dict[str, Any], h: SimpleNamespace, seal: Any, oem: MemoryOem, ai_on: None) -> None:
    seal.seal = {"seal_visible": True, "signs": ["tape_over_seal", "not-a-sign"]}
    captured: list[Any] = []
    principal = Principal(id="op-c3", tenant_id=env["tenant"], roles=["field.operator"],
                          permissions=["field.authenticity.check"], site_ids=[env["site"]])
    first = create_check(principal, CheckIn(code=env["returned"], capture_id=env["capture"]), str(uuid.uuid4()),
                         oem, seal.ports(), defer=captured.append)
    assert first["final"] is False and first["signals"]["visual"]["status"] == "pending" and first["tamper"] is None
    assert first["verdict"] == "RETURNED_REFURBISHED"  # the verdict does not wait for the photo
    assert first["say"].endswith("It is not a new unit. Checking the seal.")
    (task,) = captured
    task()
    done = client.get(f"/v1/authenticity/checks/{first['check_id']}", headers=h.auth(env["op"])).json()
    assert done["final"] is True and done["tamper"] is True and done["verdict"] == "RETURNED_REFURBISHED"
    assert done["say"] == ("Code is genuine. But this unit was activated on 12 October and returned on 20 October. "
                           "It is not a new unit. The seal shows tape over the original.")
    assert done["say_next"] == "The seal shows tape over the original."
    assert done["signals"]["visual"]["signs"] == ["tape_over_seal"] and done["signals"]["visual"]["box"] == [
        300, 200, 700, 420]
    assert "visual:tape_over_seal" in done["reasons"]
    assert [m["purpose"] for m in done["models"]] == ["seal", "seal_tamper"]
    assert seal.prompts == ["seal"]
    assert seal.muse_requests[0]["response_format"]["json_schema"]["name"] == "SealInspection"


def test_m5_t04_visual_check_through_the_api_intact_seal_and_sticker_fallback(
        client: TestClient, env: dict[str, Any], h: SimpleNamespace, seal: Any, ai_on: None) -> None:
    seal.boxes_by_prompt = {"seal": []}  # SAM finds nothing for "seal", the seal for "sticker"
    r = h.check(client, env["op"], env["new"], capture_id=env["capture"])
    assert r.status_code == 200 and r.json()["final"] is False  # TestClient runs the background task after this
    done = client.get(f"/v1/authenticity/checks/{r.json()['check_id']}", headers=h.auth(env["op"])).json()
    assert done["final"] is True and done["tamper"] is False and done["say_next"] == "The seal looks intact."
    assert done["say"] == "Code is genuine. This unit is new: it was never activated or returned."
    assert seal.prompts == ["seal", "sticker"]


def test_m5_t04_visual_failures_degrade(client: TestClient, env: dict[str, Any], h: SimpleNamespace, seal: Any,
                                        ai_on: None) -> None:
    seal.muse_status = 500
    r = h.check(client, env["op"], env["new"], capture_id=env["capture"])
    done = client.get(f"/v1/authenticity/checks/{r.json()['check_id']}", headers=h.auth(env["op"])).json()
    assert done["final"] is True and done["tamper"] is None and done["verdict"] == "GENUINE_NEW"
    assert done["signals"]["visual"]["status"] == "failed" and done["say_next"] == "I couldn't check the seal."
    assert "visual:muse-spark-1.3:AI_HTTP_500" in done["reasons"]
    seal.muse_status, seal.sam_status = None, 503
    r2 = h.check(client, env["op"], env["new"], capture_id=env["capture"])
    d2 = client.get(f"/v1/authenticity/checks/{r2.json()['check_id']}", headers=h.auth(env["op"])).json()
    assert d2["signals"]["visual"]["status"] == "done"  # Muse read the whole photo without an outline
    assert "visual:sam-3.1:AI_HTTP_503" in d2["reasons"] and "visual:seal_not_outlined" in d2["reasons"]
    app.dependency_overrides[get_visual_ports] = lambda: VisualPorts(None, None)
    try:
        nm = h.check(client, env["op"], env["new"], capture_id=env["capture"]).json()
    finally:
        app.dependency_overrides[get_visual_ports] = seal.ports
    assert nm["final"] is True and nm["signals"]["visual"]["status"] == "failed" and "visual:no_model" in nm["reasons"]


def test_m5_t04_unfinished_visual_check_is_ended_by_the_next_read(
        client: TestClient, env: dict[str, Any], h: SimpleNamespace, seal: Any, oem: MemoryOem, ai_on: None) -> None:
    principal = Principal(id="op-c3", tenant_id=env["tenant"], roles=["field.operator"],
                          permissions=["field.authenticity.check"], site_ids=[env["site"]])
    out = create_check(principal, CheckIn(code=env["new"], capture_id=env["capture"]), str(uuid.uuid4()),
                       oem, seal.ports(), defer=lambda _task: None)  # the read never runs
    assert out["final"] is False
    h.admin_sql(env["tenant"], "UPDATE field.authenticity_check SET visual_due_at = %s WHERE id = %s",
                (datetime.now(UTC) - timedelta(seconds=1), out["check_id"]))
    done = client.get(f"/v1/authenticity/checks/{out['check_id']}", headers=h.auth(env["op"])).json()
    assert done["final"] is True and "visual:not_finished" in done["reasons"]
    assert done["signals"]["visual"]["status"] == "failed" and done["say_next"] == "I couldn't check the seal."


def test_m5_t04_idempotent_replay_returns_the_first_answer(client: TestClient, env: dict[str, Any],
                                                           h: SimpleNamespace, oem: MemoryOem, ai_off: None) -> None:
    key = str(uuid.uuid4())
    a = h.check(client, env["op"], env["new"], key=key).json()
    b = h.check(client, env["op"], env["new"], key=key).json()
    assert a["check_id"] == b["check_id"] and len(oem.checks) == 1
    p = Principal(id="op-c3", tenant_id=env["tenant"], roles=[], permissions=[], site_ids=[env["site"]])
    again = create_check(p, CheckIn(code=env["new"]), key, oem, VisualPorts(None, None))  # past the middleware
    assert again["check_id"] == a["check_id"] and len(oem.checks) == 1


def test_m5_t04_roles_sites_and_validation(client: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                           ai_off: None) -> None:
    assert h.check(client, env["viewer"], env["new"]).status_code == 200
    assert h.check(client, env["sup"], env["new"], site_id=env["site"]).status_code == 200
    for who in ("tech", "integration"):
        assert h.check(client, env[who], env["new"]).status_code == 403, who
    r = h.check(client, env["sup"], env["new"])
    assert r.status_code == 422 and r.json()["code"] == "FIELD-AUT-422-SITE"
    assert h.check(client, env["op"], env["new"], site_id=env["site2"]).status_code == 403
    r = h.check(client, env["op"], env["new"], capture_id=str(uuid.uuid4()))
    assert r.status_code == 404 and r.json()["code"] == "FIELD-AUT-404-CAPTURE"
    assert h.check(client, env["op"], env["new"], area="18.52 73.85").status_code == 422  # no coordinates
    assert h.check(client, env["op"], "x" * 1025).status_code == 422
    assert h.check(client, env["op"], env["new"], area="Pune").status_code == 200
    with_capture = h.check(client, env["sup"], env["new"], capture_id=env["capture"])
    assert with_capture.status_code == 200 and with_capture.json()["site_id"] == env["site"]  # the capture's site


def test_m5_t04_rls_isolates_tenants_and_sites(client: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                               ai_off: None) -> None:
    cid = h.check(client, env["op"], env["new"]).json()["check_id"]
    assert client.get(f"/v1/authenticity/checks/{cid}", headers=h.auth(env["op"])).status_code == 200
    for who in ("other_op", "op_elsewhere"):
        r = client.get(f"/v1/authenticity/checks/{cid}", headers=h.auth(env[who]))
        assert r.status_code == 404 and r.json()["code"] == "FIELD-AUT-404-CHECK", who
    assert client.get("/v1/authenticity/checks/not-a-uuid", headers=h.auth(env["op"])).status_code == 404
    rows = h.admin_sql(env["tenant"], "SELECT relforcerowsecurity FROM pg_class WHERE oid ="
                                      " 'field.authenticity_check'::regclass")
    assert rows == [(True,)]


def test_m5_t07_first_check_race_through_the_api_one_of_two_wins(
        client: TestClient, env: dict[str, Any], h: SimpleNamespace, ai_off: None) -> None:
    results: list[str] = []
    barrier = threading.Barrier(2)

    def go(token: str) -> None:
        barrier.wait()
        results.append(h.check(client, env[token], env["new"]).json()["signals"]["first_check"]["status"])

    threads = [threading.Thread(target=go, args=(t,)) for t in ("op", "op2")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["first", "other_checker"]


def test_m5_t04_checker_ref_is_pseudonymous_and_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    a = checker_ref("t1", "op-1")
    assert a == checker_ref("t1", "op-1") and len(a) == 32 and "op-1" not in a
    assert a != checker_ref("t2", "op-1") and a != checker_ref("t1", "op-2")
    monkeypatch.setenv("FIELD_ERP_SIM_URL", "http://erp-sim:8002/")
    monkeypatch.delenv("FIELD_OEM_SIM_URL", raising=False)
    assert sim_url() == "http://erp-sim:8002/_oem"
    monkeypatch.setenv("FIELD_OEM_SIM_URL", "http://oem.local/_oem/")
    assert sim_url() == "http://oem.local/_oem"
    monkeypatch.setenv("FIELD_OEM_ADAPTER", "oem")
    assert isinstance(get_oem_port(), RealOemAdapter)
    monkeypatch.setenv("FIELD_OEM_ADAPTER", "sim")
    assert type(get_oem_port()).__name__ == "SimOemAdapter" and get_oem_port() is get_oem_port()


def test_m5_t04_logs_never_carry_the_code_or_the_checker(client: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                                          ai_off: None, capsys: pytest.CaptureFixture[str]) -> None:
    h.check(client, env["op"], env["new"], area="Pune")
    out = capsys.readouterr()
    text = out.out + out.err
    assert env["new"] not in text and checker_ref(env["tenant"], "op-c3") not in text and "Pune" not in text
    assert service.SEAL_FAILED == "I couldn't check the seal."
