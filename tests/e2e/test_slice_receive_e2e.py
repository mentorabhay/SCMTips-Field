"""End-to-end goods receipt on the spec API, through the real worker and erp-sim (M1 slice).

erp-sim inbound delivery -> worker import -> GET /v1/tasks (API3.01) -> voice count (API3.04)
-> confirm (API3.06) -> PostingQueueWorker posts via ErpPort (SimAdapter, in-process ASGI)
-> erp_document carries the SAP material document number -> reversal (API3.07) nets stock to zero
(PR3.01 example).

The field API runs as the NOBYPASSRLS app role, so RLS is exercised. The worker and the seed use
the admin URL, as they do in deployment.
"""

from __future__ import annotations

import asyncio
import os
import random
import uuid
from decimal import Decimal
from typing import Any

import httpx
import psycopg
import pytest
from erp_sim.app import app as erp_app
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth.jwt import create_dev_token
from field_sap.sim.adapter import SimAdapter
from field_worker.posting.queue import PostingQueueWorker
from field_worker.warehouse.ibd_import import poll_and_import_inbound_deliveries

pytestmark = pytest.mark.unit

ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
ERPSIM = ADMIN.rsplit("/", 1)[0] + "/erpsim"
api = TestClient(app)


def _hdr(token: str, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4()), **extra}


def _stock(plant: str, mat: str) -> Decimal:
    with psycopg.connect(ERPSIM) as c, c.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM erpsim.stock WHERE plant = %s AND material_no = %s",
            (plant, mat),
        )
        row = cur.fetchone()
        return Decimal(row[0]) if row else Decimal(0)


@pytest.fixture
def world() -> dict[str, Any]:
    tenant = str(uuid.uuid4())
    site = str(uuid.uuid4())
    plant = f"P{uuid.uuid4().hex[:7].upper()}"  # unique: the importer takes every open delivery of a plant
    deliv = f"18{random.randint(10_000_000, 99_999_999)}"
    mats = [f"E2E-{uuid.uuid4().hex[:6].upper()}", f"E2E-{uuid.uuid4().hex[:6].upper()}"]
    with psycopg.connect(ERPSIM, autocommit=True) as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO erpsim.inbound_delivery (client, delivery_document, plant, storage_location, status)"
            " VALUES ('100', %s, %s, '0001', 'open')",
            (deliv, plant),
        )
        for no, mat, qty in (("000010", mats[0], 24), ("000020", mats[1], 12)):
            cur.execute(
                "INSERT INTO erpsim.inbound_delivery_item"
                " (client, delivery_document, item_no, material_no, delivery_qty, actual_qty, uom, status)"
                " VALUES ('100', %s, %s, %s, %s, 0, 'EA', 'open')",
                (deliv, no, mat, qty),
            )
    with psycopg.connect(ADMIN, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant,))
        cur.execute(
            "INSERT INTO field.site (id, tenant_id, code, name, kind, erp_plant, status)"
            " VALUES (%s, %s, %s, 'E2E DC', 'warehouse', %s, 'active')",
            (site, tenant, f"E2E-{plant}", plant),
        )
        for m in mats:
            cur.execute(
                "INSERT INTO field.material (tenant_id, erp_material_no, plant, description, base_uom)"
                " VALUES (%s, %s, %s, 'E2E material', 'EA')",
                (tenant, m, plant),
            )
    op = create_dev_token("op-1", tenant, ["field.operator"], site_ids=[site])
    op2 = create_dev_token("op-2", tenant, ["field.operator"], site_ids=[site])
    sup = create_dev_token("sup-1", tenant, ["field.supervisor"], site_ids=[site])
    return {"tenant": tenant, "site": site, "plant": plant, "deliv": deliv, "mats": mats,
            "op": op, "op2": op2, "sup": sup}


def _import(w: dict[str, Any]) -> None:
    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=erp_app), base_url="http://erp") as cl:
            created, _lines, _ = await poll_and_import_inbound_deliveries(
                tenant_id=w["tenant"], site_id=w["site"], plant=w["plant"], erp_url="http://erp",
                db_url=ADMIN, client=cl,
            )
            assert created == 1

    asyncio.run(run())


def _drain(w: dict[str, Any]) -> int:
    worker = PostingQueueWorker(erp_port=SimAdapter(app=erp_app), db_url=ADMIN)

    async def run() -> int:
        n = 0
        while await worker.process_one_job(w["tenant"]):
            n += 1
            assert n < 50, "queue did not drain"
        return n

    return asyncio.run(run())


def _task(w: dict[str, Any]) -> dict[str, Any]:
    r = api.get(f"/v1/tasks?site_id={w['site']}&type=receive", headers=_hdr(w["op"]))
    assert r.status_code == 200, r.text
    tasks = [t for t in r.json()["items"] if t["erp_ref"] == w["deliv"]]
    assert len(tasks) == 1
    return tasks[0]


def test_slice_goods_receipt_round_trip(world: dict[str, Any]) -> None:
    """TC3.109 / FR3.010: import, count, confirm, worker posts PATCH per line + PostGoodsReceipt, undo (PR3.01)."""
    w = world
    _import(w)
    task = _task(w)
    assert [ln["line_no"] for ln in task["lines"]] == [10, 20]
    assert task["lines"][0]["expected_qty"] == 24.0
    stock_before = [_stock(w["plant"], m) for m in w["mats"]]

    for ln, qty in zip(task["lines"], (24, 12), strict=True):
        r = api.post(f"/v1/tasks/{task['id']}/lines/{ln['id']}/counts",
                     json={"qty": qty, "uom": "EA", "source": "voice", "confidence": 0.93},
                     headers=_hdr(w["op"]))
        assert r.status_code == 200, r.text
        assert r.json()["counted_qty"] == qty

    r = api.post(f"/v1/tasks/{task['id']}/confirm", json={}, headers=_hdr(w["op"]))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["queue_key"] == f"IBD:{w['deliv']}" and out["jobs"] == 3 and out["status"] == "queued"

    assert _drain(w) == 3
    with psycopg.connect(ADMIN) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (w["tenant"],))
        cur.execute("SELECT status, doc_number, movement_type FROM field.erp_document WHERE id = %s",
                    (out["erp_document_id"],))
        row = cur.fetchone()
        assert row is not None
        status, doc_no, mvt = row
        cur.execute("SELECT status FROM field.task WHERE id = %s", (task["id"],))
        trow = cur.fetchone()
        assert trow is not None
        task_status = trow[0]
    assert status == "posted" and mvt == "101"
    assert 4_900_000_000 <= int(doc_no) <= 4_999_999_999  # T3.022 done_when: SAP material document range
    assert task_status == "completed"
    assert [_stock(w["plant"], m) - b for m, b in zip(w["mats"], stock_before, strict=True)] == [24, 12]

    # Undo after post: 102 reversal by the poster within the window nets stock to zero (PR3.01).
    r = api.post(f"/v1/erp-documents/{out['erp_document_id']}/reverse", json={"reason": "wrong_material"},
                 headers=_hdr(w["op"]))
    assert r.status_code == 200, r.text
    assert r.json()["doc_type"] == "GR_REV"
    assert _drain(w) == 1
    assert [_stock(w["plant"], m) for m in w["mats"]] == stock_before
    r = api.post(f"/v1/erp-documents/{out['erp_document_id']}/reverse", json={"reason": "again"},
                 headers=_hdr(w["op"]))
    assert r.status_code == 409 and "ALREADY-REVERSED" in r.text


def test_partial_receipt_posts_counted_not_delivery_quantity(world: dict[str, Any]) -> None:
    w = world
    _import(w)
    task = _task(w)
    before = [_stock(w["plant"], m) for m in w["mats"]]
    l10, l20 = task["lines"]
    api.post(f"/v1/tasks/{task['id']}/lines/{l10['id']}/counts",
             json={"qty": 20, "uom": "EA", "source": "scan"}, headers=_hdr(w["op"]))
    api.post(f"/v1/tasks/{task['id']}/lines/{l20['id']}/counts",
             json={"qty": 0, "uom": "EA", "source": "scan"}, headers=_hdr(w["op"]))
    r = api.post(f"/v1/tasks/{task['id']}/confirm", json={}, headers=_hdr(w["op"]))
    assert r.status_code == 422 and "FIELD-RCV-422-REASON" in r.text  # under-delivery needs a reason
    for ln in (l10, l20):
        r = api.post(f"/v1/tasks/{task['id']}/lines/{ln['id']}/flags",
                     json={"flag": "short", "reason_code": "Short shipment"}, headers=_hdr(w["op"]))
        assert r.status_code == 200, r.text
    r = api.post(f"/v1/tasks/{task['id']}/confirm", json={}, headers=_hdr(w["op"]))
    assert r.status_code == 200, r.text
    _drain(w)
    assert [_stock(w["plant"], m) - b for m, b in zip(w["mats"], before, strict=True)] == [20, 0]


def test_count_rules_and_scope(world: dict[str, Any]) -> None:
    w = world
    _import(w)
    task = _task(w)
    ln = task["lines"][0]
    url = f"/v1/tasks/{task['id']}/lines/{ln['id']}/counts"
    r = api.post(url, json={"qty": 24, "uom": "EA", "source": "voice", "confidence": 0.79}, headers=_hdr(w["op"]))
    assert r.status_code == 422 and "FIELD-VOICE-422-CONFIDENCE" in r.text
    r = api.post(url, json={"qty": 24, "uom": "KG", "source": "scan"}, headers=_hdr(w["op"]))
    assert r.status_code == 422 and "FIELD-TASK-422-UOM" in r.text
    r = api.post(url, json={"qty": 24, "uom": "EA", "source": "voice", "confidence": 0.80}, headers=_hdr(w["op"]))
    assert r.status_code == 200
    other_site = str(uuid.uuid4())
    r = api.get(f"/v1/tasks?site_id={other_site}", headers=_hdr(w["op"]))
    assert r.status_code == 403 and "FIELD-AUTH-403-SCOPE" in r.text
    # A different tenant sees nothing (RLS), even with every site in scope.
    stranger = create_dev_token("x", str(uuid.uuid4()), ["field.operator"], site_ids=["*"])
    r = api.get("/v1/tasks", headers=_hdr(stranger))
    assert r.status_code == 200 and all(t["erp_ref"] != w["deliv"] for t in r.json()["items"])


def test_over_tolerance_blocks_confirm_and_opens_case(world: dict[str, Any]) -> None:
    w = world
    _import(w)
    task = _task(w)
    ln = task["lines"][0]
    api.post(f"/v1/tasks/{task['id']}/lines/{ln['id']}/counts",
             json={"qty": 30, "uom": "EA", "source": "scan"}, headers=_hdr(w["op"]))
    r = api.post(f"/v1/tasks/{task['id']}/confirm", json={"lines": [ln["id"]]}, headers=_hdr(w["op"]))
    assert r.status_code == 409 and "FIELD-RCV-409-OVER-TOLERANCE" in r.text
    with psycopg.connect(ADMIN) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (w["tenant"],))
        cur.execute("SELECT count(*) FROM field.approval_request WHERE task_id = %s AND approval_type ="
                    " 'receipt_over_tolerance' AND status = 'pending'", (task["id"],))
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT count(*) FROM field.posting_job WHERE queue_key = %s", (f"IBD:{w['deliv']}",))
        assert cur.fetchone()[0] == 0


def test_reverse_permissions(world: dict[str, Any]) -> None:
    w = world
    _import(w)
    task = _task(w)
    for ln, qty in zip(task["lines"], (24, 12), strict=True):
        api.post(f"/v1/tasks/{task['id']}/lines/{ln['id']}/counts",
                 json={"qty": qty, "uom": "EA", "source": "scan"}, headers=_hdr(w["op"]))
    doc = api.post(f"/v1/tasks/{task['id']}/confirm", json={}, headers=_hdr(w["op"])).json()["erp_document_id"]
    r = api.post(f"/v1/erp-documents/{doc}/reverse", json={"reason": "x"}, headers=_hdr(w["op"]))
    assert r.status_code == 409 and "NOT-POSTED" in r.text
    _drain(w)
    r = api.post(f"/v1/erp-documents/{doc}/reverse", json={"reason": "x"}, headers=_hdr(w["op2"]))
    assert r.status_code == 403  # another operator may not undo someone else's document
    r = api.post(f"/v1/erp-documents/{doc}/reverse", json={"reason": "x"}, headers=_hdr(w["sup"]))
    assert r.status_code == 200, r.text
