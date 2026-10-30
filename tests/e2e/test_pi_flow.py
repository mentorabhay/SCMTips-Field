"""Physical inventory on the spec API (API3.10-3.12) incl. the C3 P0 regression.

PR3.03 blind count, PR3.04 recount rule + different operator, PR3.05 approval with SoD, and the
ERP round trip through the worker (create PI doc -> counts -> PostDifferences 701/702 on erp-sim).
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from erp_sim.app import app as erp_app
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth.jwt import create_dev_token
from field_api.pi.api import recount_accepted, recount_needed
from field_sap.sim.adapter import SimAdapter
from field_worker.posting.queue import PostingQueueWorker
from hypothesis import given, settings
from hypothesis import strategies as st

pytestmark = pytest.mark.unit
ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
ERPSIM = ADMIN.rsplit("/", 1)[0] + "/erpsim"
api = TestClient(app)
BOOK_KEYS = ("book_qty", "book_value", "difference", "recount_reason", "unit_price")


def _h(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}", "Idempotency-Key": str(uuid.uuid4())}


@pytest.fixture
def pi_world() -> dict[str, Any]:
    tenant, site = str(uuid.uuid4()), str(uuid.uuid4())
    plant, sloc = f"Q{uuid.uuid4().hex[:7].upper()}", "0001"
    mats = [f"PI-{uuid.uuid4().hex[:6].upper()}" for _ in range(2)]
    with psycopg.connect(ADMIN, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant,))
        cur.execute("INSERT INTO field.site (id, tenant_id, code, name, kind, erp_plant, status)"
                    " VALUES (%s, %s, %s, 'PI DC', 'warehouse', %s, 'active')", (site, tenant, f"PI-{plant}", plant))
        for m in mats:
            cur.execute("INSERT INTO field.material (tenant_id, erp_material_no, plant, description, base_uom)"
                        " VALUES (%s, %s, %s, 'pi mat', 'EA')", (tenant, m, plant))
    with psycopg.connect(ERPSIM, autocommit=True) as c, c.cursor() as cur:
        for m, q in zip(mats, (100, 40), strict=True):
            cur.execute("INSERT INTO erpsim.stock (client, plant, storage_location, material_no, quantity, uom)"
                        " VALUES ('100', %s, %s, %s, %s, 'EA')", (plant, sloc, m, q))
    tok = {name: create_dev_token(name, tenant, roles, site_ids=[site]) for name, roles in (
        ("ctrl", ["inventory.controller"]), ("op1", ["field.operator"]), ("op2", ["field.operator"]),
        ("sup", ["field.supervisor"]))}
    return {"tenant": tenant, "site": site, "plant": plant, "sloc": sloc, "mats": mats, "tok": tok}


def _create(w: dict[str, Any], price: str = "1000") -> dict[str, Any]:
    body = {"site_id": w["site"], "plant": w["plant"], "storage_location": w["sloc"],
            "items": [{"bin": "03-05-01", "material": w["mats"][0], "book_qty": "100", "unit_price": price},
                      {"bin": "03-05-02", "material": w["mats"][1], "book_qty": "40", "unit_price": price}]}
    r = api.post("/v1/pi-documents", json=body, headers=_h(w["tok"]["ctrl"]))
    assert r.status_code == 201, r.text
    return r.json()


def _count(w: dict[str, Any], doc: str, item: int, qty: int, who: str) -> Any:
    return api.post(f"/v1/pi-documents/{doc}/items/{item}/counts", json={"qty": qty, "source": "scan"},
                    headers=_h(w["tok"][who]))


def _drain(tenant: str) -> int:
    worker = PostingQueueWorker(erp_port=SimAdapter(app=erp_app), db_url=ADMIN)

    async def run() -> int:
        n = 0
        while await worker.process_one_job(tenant):
            n += 1
        return n

    return asyncio.run(run())


def _no_book(payload: Any, books: set[str]) -> None:
    text = json.dumps(payload)
    for k in BOOK_KEYS:
        assert f'"{k}' not in text, f"operator response leaks {k}"
    if isinstance(payload, dict):
        for k, v in payload.items():
            if k in ("expected_qty", "counted_qty") and str(v) in books:
                raise AssertionError(f"labelled field {k} equals a book quantity")


def test_p0_regression_client_supplied_approval_route_is_gone(pi_world: dict[str, Any]) -> None:
    r = api.post("/v1/warehouse/inventory/differences/post",
                 json={"line_id": "L1", "counted_qty": 0, "book_qty": 5000, "unit_price": 100,
                       "approval_record": {"status": "approved", "approved_by": "someone-else"}},
                 headers=_h(pi_world["tok"]["sup"]))
    assert r.status_code in (404, 405)


def test_pi_flow_blind_count_recount_approval_sod_and_erp_posting(pi_world: dict[str, Any]) -> None:
    w = pi_world
    doc = _create(w)
    pid = doc["id"]
    # PR3.03: the operator's task list for the count task never shows book values
    r = api.get(f"/v1/tasks?site_id={w['site']}&type=count", headers=_h(w["tok"]["op1"]))
    assert r.status_code == 200
    _no_book(r.json(), {"100", "100.0", "40", "40.0"})
    # count 1 on item 1: 60 vs book 100 -> 40 % diff -> recount required (status hidden from operator)
    r = _count(w, pid, 1, 60, "op1")
    assert r.status_code == 200 and r.json() == {"item": "1", "count_no": 1, "status": "committed"}
    _no_book(r.json(), {"100"})
    assert _count(w, pid, 2, 40, "op1").status_code == 200  # item 2 matches book, no recount
    r = api.post(f"/v1/pi-documents/{pid}/post-differences", headers=_h(w["tok"]["ctrl"]))
    assert r.status_code == 409 and "OPEN-RECOUNTS" in r.text
    assert "RECOUNT-SAME-OPERATOR" in _count(w, pid, 1, 61, "op1").text  # PR3.04
    assert _count(w, pid, 1, 60, "op2").status_code == 200  # within max(1, 0.5 %) -> accepted
    assert "NOT-ASSIGNED" in _count(w, pid, 1, 60, "op1").text  # accepted: no further count wanted
    # value 40 x 1000 = 40,000 <= 50,000 (FIELD_PI_APPROVAL_VALUE): queued without approval
    r = api.post(f"/v1/pi-documents/{pid}/post-differences", headers=_h(w["tok"]["ctrl"]))
    assert r.status_code == 200 and r.json()["status"] == "queued" and r.json()["band"] == "B1"
    assert _drain(w["tenant"]) == 1
    with psycopg.connect(ERPSIM) as c, c.cursor() as cur:
        cur.execute("SELECT quantity FROM erpsim.stock WHERE plant = %s AND material_no = %s",
                    (w["plant"], w["mats"][0]))
        assert Decimal(cur.fetchone()[0]) == 60  # type: ignore[index] # 702 loss of 40 posted in ERP


def test_pi_above_threshold_needs_independent_approver(pi_world: dict[str, Any]) -> None:
    w = pi_world
    pid = _create(w, price="1800")["id"]  # 40 x 1800 = 72,000 INR -> band B2 (TC3.015)
    assert _count(w, pid, 1, 60, "op1").status_code == 200
    assert _count(w, pid, 1, 60, "op2").status_code == 200
    assert _count(w, pid, 2, 40, "op1").status_code == 200
    r = api.post(f"/v1/pi-documents/{pid}/post-differences", headers=_h(w["tok"]["ctrl"]))
    out = r.json()
    assert r.status_code == 200 and out["status"] == "awaiting_approval" and out["band"] == "B2"
    assert out["value_abs"] == "72000.00"
    apr = out["approval_request_id"]
    # nothing queued before approval (PR3.05)
    with psycopg.connect(ADMIN) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (w["tenant"],))
        cur.execute("SELECT count(*) FROM field.erp_document WHERE payload->>'pi_document_id' = %s", (pid,))
        assert cur.fetchone()[0] == 0  # type: ignore[index]
    # requester (controller holds discrepancy.approve) is excluded: SoD
    r = api.post(f"/v1/approval-requests/{apr}/decide", json={"decision": "approve", "reason": "ok"},
                 headers=_h(w["tok"]["ctrl"]))
    assert r.status_code == 403 and "FIELD-APR-403-SOD" in r.text
    # operators cannot decide at all
    r = api.post(f"/v1/approval-requests/{apr}/decide", json={"decision": "approve", "reason": "ok"},
                 headers=_h(w["tok"]["op2"]))
    assert r.status_code == 403
    r = api.post(f"/v1/approval-requests/{apr}/decide", json={"decision": "approve", "reason": "checked bin"},
                 headers=_h(w["tok"]["sup"]))
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["erp_document_id"]
    assert _drain(w["tenant"]) == 1
    r = api.post(f"/v1/approval-requests/{apr}/decide", json={"decision": "approve", "reason": "again"},
                 headers=_h(w["tok"]["sup"]))
    assert r.status_code == 409


@settings(max_examples=500, deadline=None)
@given(
    book=st.integers(min_value=0, max_value=10_000),
    delta=st.integers(min_value=-300, max_value=300),
    price=st.integers(min_value=0, max_value=50_000),
)
def test_pr3_04_recount_rule_matches_reference(book: int, delta: int, price: int) -> None:
    """PR3.04: recount required iff |diff|/book > 2.0 % or |diff value| > 25,000 (BR3.09)."""
    counted = max(0, book + delta)
    diff = abs(counted - book)
    expected = diff != 0 and (book == 0 or diff * 100 > 2 * book or diff * price > 25_000)
    assert recount_needed(Decimal(book), Decimal(counted), Decimal(price)) is expected


@settings(max_examples=500, deadline=None)
@given(prev=st.integers(min_value=0, max_value=100_000), d=st.integers(min_value=-1000, max_value=1000))
def test_pr3_04_recount_acceptance_tolerance(prev: int, d: int) -> None:
    """PR3.04 / FR3.033: a recount is accepted iff within max(1 unit, 0.5 %) of the previous count."""
    cur = max(0, prev + d)
    assert recount_accepted(Decimal(prev), Decimal(cur)) is (abs(cur - prev) * 1000 <= max(1000, prev * 5))


def test_pr3_04_shrink_case_book_50_count_49_needs_no_recount() -> None:
    assert recount_needed(Decimal(50), Decimal(49), Decimal(1)) is False
    assert recount_needed(Decimal(100), Decimal(97), Decimal(1)) is True  # TC3.011
    assert recount_needed(Decimal(100), Decimal(98), Decimal(1)) is False  # TC3.012
