"""M2 jobs contract end to end (docs/design/M2_JOBS_CONTRACT.md), through field-api, the real worker
code and erp-sim (in-process ASGI), on Postgres with RLS (field-api runs as the app role).

receive -> putaway (task.assigned, bin scan, touch finish, field bin stock)
pick    -> OBD import, bin then product scans, short flag, goods issue 601 in erp-sim, bin stock
count   -> blind list, within tolerance 702 in erp-sim; beyond tolerance approval request, recount by
           a different operator, supervisor approval, 702 posted
audit   -> serial confirmations, missing flag, reconciliation (matched / serial_mismatch / erp_only),
           findings in GET /v1/mismatches with captured_by
swap    -> old/new serial scans, dismantle + install through the tower equipment queue, erp-sim state
"""

from __future__ import annotations

import asyncio
import hashlib
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
from field_api.audit.generate import generate_audit_task
from field_api.auth.jwt import create_dev_token
from field_api.jobs.tower_tasks import create_swap_task
from field_sap.equipment import SAPEquipmentAdapter
from field_sap.sim.adapter import SimAdapter
from field_worker.posting.equipment_queue import process_next_tower_job
from field_worker.posting.queue import PostingQueueWorker
from field_worker.tower.installed_base import sync_tower_installed_base
from field_worker.warehouse.ibd_import import poll_and_import_inbound_deliveries
from field_worker.warehouse.obd_import import poll_and_import_outbound_deliveries

pytestmark = pytest.mark.unit

ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
ERPSIM = ADMIN.rsplit("/", 1)[0] + "/erpsim"
api = TestClient(app)
BINS = ("02-01-01", "02-03-04", "03-05-01", "03-05-02")


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}


def _hash(lines: list[tuple[str, float]]) -> str:
    return hashlib.sha256("|".join(sorted(f"{lid}:{q:.3f}" for lid, q in lines)).encode()).hexdigest()


def _erp(sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with psycopg.connect(ERPSIM, autocommit=True) as c, c.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall()) if cur.description else []


def _field(tenant: str, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with psycopg.connect(ADMIN, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)", (tenant,))
        cur.execute(sql, params)
        return list(cur.fetchall()) if cur.description else []


def _stock(plant: str, mat: str) -> Decimal:
    rows = _erp("SELECT COALESCE(SUM(quantity), 0) FROM erpsim.stock WHERE plant = %s AND material_no = %s", (plant, mat))
    return Decimal(rows[0][0])


def _drain(tenant: str) -> int:
    worker = PostingQueueWorker(erp_port=SimAdapter(app=erp_app), db_url=ADMIN)

    async def run() -> int:
        n = 0
        while await worker.process_one_job(tenant):
            n += 1
            assert n < 50
        return n

    return asyncio.run(run())


def _device(token: str) -> str:
    r = api.post("/v1/devices", json={"kind": "phone", "serial_no": f"t-{uuid.uuid4().hex[:8]}", "model": "test"},
                 headers=_h(token))
    assert r.status_code in (200, 201), r.text
    return str(r.json()["id"])


def _events(token: str, device: str) -> list[dict[str, Any]]:
    import json

    r = api.get(f"/v1/devices/{device}/events", params={"once": "true"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    return [json.loads(ln[6:]) for ln in r.text.splitlines() if ln.startswith("data: ")]


@pytest.fixture
def wh() -> dict[str, Any]:
    tenant, site = str(uuid.uuid4()), str(uuid.uuid4())
    plant = f"M{uuid.uuid4().hex[:7].upper()}"
    mats = [f"M2-{uuid.uuid4().hex[:6].upper()}" for _ in range(3)]
    _erp("INSERT INTO erpsim.plant (client, plant, name) VALUES ('100', %s, 'M2 test') ON CONFLICT DO NOTHING", (plant,))
    for m in mats:
        _erp("INSERT INTO erpsim.material (client, material_no, description, base_uom) VALUES ('100', %s, 'M2 part', 'EA')",
             (m,))
        _erp("INSERT INTO erpsim.stock (client, plant, storage_location, material_no, quantity, uom)"
             " VALUES ('100', %s, '101A', %s, 100, 'EA')", (plant, m))
    _field(tenant, "INSERT INTO field.site (id, tenant_id, code, name, kind, erp_plant, status)"
                   " VALUES (%s, %s, %s, 'M2 DC', 'warehouse', %s, 'active')", (site, tenant, f"M2-{plant}", plant))
    for m in mats:
        _field(tenant, "INSERT INTO field.material (tenant_id, erp_material_no, plant, description, base_uom)"
                       " VALUES (%s, %s, %s, %s, 'EA')", (tenant, m, plant, f"Part {m}"))
    admin = create_dev_token("adm", tenant, ["field.admin"], site_ids=[site])
    r = api.post("/v1/locations", json={"site_id": site, "kind": "zone", "code": "02"}, headers=_h(admin))
    assert r.status_code == 201, r.text
    zone = r.json()["id"]
    for b in BINS:
        r = api.post("/v1/locations", json={"site_id": site, "parent_id": zone, "kind": "position", "code": b,
                                            "erp_ref": f"{plant}/{b}", "erp_ref_type": "storage_bin"}, headers=_h(admin))
        assert r.status_code == 201, r.text
    base = create_dev_token("op-1", tenant, ["field.operator"], site_ids=[site])
    dev = _device(base)
    op = create_dev_token("op-1", tenant, ["field.operator"], site_ids=[site], device_id=dev)
    op2 = create_dev_token("op-2", tenant, ["field.operator"], site_ids=[site])
    sup = create_dev_token("sup-1", tenant, ["field.supervisor"], site_ids=["*"])
    planner = create_dev_token("plan-1", tenant, ["inventory.controller"], site_ids=[site])
    return {"tenant": tenant, "site": site, "plant": plant, "mats": mats, "op": op, "op2": op2, "sup": sup,
            "planner": planner, "device": dev}


def _tasks(w: dict[str, Any], **params: str) -> list[dict[str, Any]]:
    r = api.get("/v1/tasks", params={"site_id": w["site"], **params}, headers={"Authorization": f"Bearer {w['op']}"})
    assert r.status_code == 200, r.text
    return list(r.json()["items"])


def _receive(w: dict[str, Any], qtys: tuple[int, int] = (24, 12)) -> dict[str, Any]:
    deliv = f"18{random.randint(10_000_000, 99_999_999)}"
    _erp("INSERT INTO erpsim.inbound_delivery (client, delivery_document, plant, storage_location, status, header_data)"
         " VALUES ('100', %s, %s, '101A', 'open', '{\"Vendor\": \"V-1\"}')", (deliv, w["plant"]))
    for i, q in enumerate(qtys):
        _erp("INSERT INTO erpsim.inbound_delivery_item (client, delivery_document, item_no, material_no, delivery_qty,"
             " actual_qty, uom, status) VALUES ('100', %s, %s, %s, %s, 0, 'EA', 'open')",
             (deliv, f"{(i + 1) * 10:06d}", w["mats"][i], q))

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=erp_app), base_url="http://erp") as cl:
            await poll_and_import_inbound_deliveries(tenant_id=w["tenant"], site_id=w["site"], plant=w["plant"],
                                                     erp_url="http://erp", db_url=ADMIN, client=cl)

    asyncio.run(run())
    return next(t for t in _tasks(w, type="receive") if t["ref_doc_no"] == deliv)


def test_task_list_contract_and_receive_to_putaway(wh: dict[str, Any]) -> None:
    """Contract §2 list shape, §3 confirmations, §4 receive -> putaway -> stored (T3.025 / T3.026 / FR3.013)."""
    w = wh
    task = _receive(w)
    assert task["title"].startswith("Delivery ") and task["subtitle"] == "From V-1 · 2 items · 36 pieces"
    assert task["status"] == "open" and task["erp_ref"] == task["ref_doc_no"] and task["completed_at"] is None
    ln = task["lines"][0]
    assert {"id", "line_no", "material", "description", "uom", "bin", "expected_qty", "counted_qty", "position",
            "expected_serial", "status", "version"} <= set(ln) and ln["status"] == "open"
    assert ln["description"] == f"Part {w['mats'][0]}"
    assert [t["id"] for t in _tasks(w, type="receive,putaway", status="open,in_progress")] == [task["id"]]
    r = api.get("/v1/tasks", params={"type": "receive,nonsense"}, headers={"Authorization": f"Bearer {w['op']}"})
    assert r.status_code == 422

    staged = []
    for line in task["lines"]:
        r = api.post("/v1/count-records", json={"task_line_id": line["id"], "value": line["expected_qty"], "unit": "EA",
                                                "source": "manual"}, headers=_h(w["op"]))
        assert r.status_code == 201, r.text
        staged.append((line["id"], line["expected_qty"]))
    r = api.post(f"/v1/tasks/{task['id']}/post-requests", json={"lines": [s[0] for s in staged], "staged_hash": "0" * 64,
                                                                "confirm": {"method": "touch"}}, headers=_h(w["op"]))
    assert r.status_code == 422 and "NO-CONFIRM" in r.text  # staged_hash still proves the reviewed lines
    r = api.post(f"/v1/tasks/{task['id']}/post-requests", json={"lines": [s[0] for s in staged],
                 "staged_hash": _hash(staged), "confirm": {"method": "touch"}}, headers=_h(w["op"]))
    assert r.status_code == 202 and r.json()["status"] == "queued" and r.json()["confirm_method"] == "touch", r.text
    assert _tasks(w, type="receive")[0]["status"] == "awaiting_posting"
    assert _drain(w["tenant"]) == 3
    assert _tasks(w, type="receive", status="done")[0]["completed_at"]

    events = _events(w["op"], w["device"])
    posted = next(e for e in events if e["kind"] == "erp.posted")
    assert posted["payload"]["task_id"] == task["id"] and posted["payload"]["doc_year"]
    assigned = next(e for e in events if e["kind"] == "task.assigned")["payload"]
    assert assigned["type"] == "putaway"
    put = next(t for t in _tasks(w, type="putaway") if t["id"] == assigned["task_id"])
    assert put["ref_doc_no"] == posted["payload"]["doc_number"]
    assert [ln["bin"] for ln in put["lines"]] == ["02-01-01", "02-03-04"]  # first empty bins, in walking order
    assert [ln["expected_qty"] for ln in put["lines"]] == [24.0, 12.0]

    l1, l2 = put["lines"]
    r = api.post(f"/v1/tasks/{put['id']}/lines/{l1['id']}/confirmations", json={"kind": "bin", "code": "03-05-01"},
                 headers=_h(w["op"]))
    assert r.status_code == 409 and r.json()["code"] == "FIELD-TASK-409-WRONG-CODE"
    assert r.json()["title"] == "That is bin 03-05-01. Go to 02-01-01."
    r = api.post(f"/v1/tasks/{put['id']}/lines/{l1['id']}/confirmations",
                 json={"kind": "bin", "code": "03-05-01", "reason": "bin_full"}, headers=_h(w["op"]))
    assert r.status_code == 200 and r.json() == {"ok": True, "bin": "03-05-01", "divergent": True,
                                                 "line_status": "confirmed"}, r.text
    finish = [(l1["id"], 0.0), (l2["id"], 0.0)]  # putaway lines are scanned, not counted
    r = api.post(f"/v1/tasks/{put['id']}/post-requests", json={"lines": [f[0] for f in finish],
                 "staged_hash": _hash(finish), "confirm": {"method": "touch"}}, headers=_h(w["op"]))
    assert r.status_code == 409 and "Scan the bin for line 20" in r.text
    r = api.post(f"/v1/tasks/{put['id']}/lines/{l2['id']}/confirmations", json={"kind": "bin", "code": "02-03-04"},
                 headers=_h(w["op"]))
    assert r.status_code == 200
    r = api.post(f"/v1/tasks/{put['id']}/post-requests", json={"lines": [f[0] for f in finish],
                 "staged_hash": _hash(finish), "confirm": {"method": "touch"}}, headers=_h(w["op"]))
    assert r.status_code == 202 and r.json()["status"] == "completed", r.text
    assert any(e["kind"] == "task.completed" and e["payload"]["task_id"] == put["id"]
               for e in _events(w["op"], w["device"]))
    stock = _field(w["tenant"], "SELECT storage_bin, material_no, quantity FROM field.bin_stock WHERE site_id = %s"
                                " ORDER BY storage_bin", (w["site"],))
    assert [(b, m, float(q)) for b, m, q in stock] == [("02-03-04", w["mats"][1], 12.0), ("03-05-01", w["mats"][0], 24.0)]
    scans = _field(w["tenant"], "SELECT accepted FROM field.task_line_confirmation WHERE task_id = %s ORDER BY created_at",
                   (put["id"],))
    assert [a for (a,) in scans] == [False, True, True]  # the refused scan is kept as evidence


def _put_stock(w: dict[str, Any], bin_: str, mat: str, qty: float) -> None:
    _field(w["tenant"], "INSERT INTO field.bin_stock (tenant_id, site_id, storage_bin, material_no, quantity)"
                        " VALUES (%s, %s, %s, %s, %s)", (w["tenant"], w["site"], bin_, mat, qty))


def test_pick_import_scans_short_and_goods_issue(wh: dict[str, Any]) -> None:
    """FR3.017 import with bins in walking order, FR3.018 bin then product, FR3.020 short, 601 in erp-sim (T3.029-T3.034)."""
    w = wh
    _put_stock(w, "03-05-02", w["mats"][0], 50)
    _put_stock(w, "02-01-01", w["mats"][1], 50)
    deliv = f"80{random.randint(10_000_000, 99_999_999)}"
    _erp("INSERT INTO erpsim.outbound_delivery (client, delivery_document, plant, storage_location, status, header_data)"
         " VALUES ('100', %s, %s, '101A', 'open', '{\"ShipTo\": \"C-9\"}')", (deliv, w["plant"]))
    for i, (m, q) in enumerate(((w["mats"][0], 4), (w["mats"][1], 3)), start=1):
        _erp("INSERT INTO erpsim.outbound_delivery_item (client, delivery_document, item_no, material_no, delivery_qty,"
             " picked_qty, uom, status) VALUES ('100', %s, %s, %s, %s, 0, 'EA', 'open')", (deliv, f"{i * 10:06d}", m, q))

    async def run() -> tuple[int, int]:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=erp_app), base_url="http://erp") as cl:
            return await poll_and_import_outbound_deliveries(w["tenant"], w["site"], w["plant"], erp_url="http://erp",
                                                             db_url=ADMIN, client=cl)

    assert asyncio.run(run()) == (1, 2)
    assert asyncio.run(run()) == (0, 0)  # idempotent
    task = next(t for t in _tasks(w, type="pick") if t["ref_doc_no"] == deliv)
    assert task["subtitle"] == "For C-9 · 2 stops · 7 pieces"
    assert [(ln["bin"], ln["line_no"]) for ln in task["lines"]] == [("02-01-01", 20), ("03-05-02", 10)]
    a, b = task["lines"]

    def scan(ln: dict[str, Any], kind: str, code: str) -> httpx.Response:
        return api.post(f"/v1/tasks/{task['id']}/lines/{ln['id']}/confirmations", json={"kind": kind, "code": code},
                        headers=_h(w["op"]))

    assert scan(a, "product", w["mats"][1]).json()["title"] == "Scan bin 02-01-01 first."
    assert scan(a, "bin", "03-05-02").json()["title"] == "That is bin 03-05-02. Go to 02-01-01."
    assert scan(a, "bin", "02-01-01").status_code == 200
    assert scan(a, "product", w["mats"][0]).status_code == 409
    assert scan(a, "product", w["mats"][1]).json()["line_status"] == "confirmed"
    for ln, qty in ((a, 3), (b, 2)):
        r = api.post("/v1/count-records", json={"task_line_id": ln["id"], "value": qty, "unit": "EA", "source": "manual"},
                     headers=_h(w["op"]))
        assert r.status_code == 201, r.text
    r = api.post(f"/v1/tasks/{task['id']}/lines/{b['id']}/flags", json={"flag": "short", "reason": "picked 2 of 4"},
                 headers=_h(w["op"]))
    assert r.status_code == 200 and r.json()["reason"] == "picked 2 of 4"  # the phone's own words
    r = api.post(f"/v1/tasks/{task['id']}/lines/{b['id']}/flags", json={"flag": "short"}, headers=_h(w["op"]))
    assert r.status_code == 422
    staged = [(a["id"], 3.0), (b["id"], 2.0)]
    body = {"lines": [s[0] for s in staged], "staged_hash": _hash(staged), "confirm": {"method": "touch"}}
    r = api.post(f"/v1/tasks/{task['id']}/post-requests", json=body, headers=_h(w["op"]))
    assert r.status_code == 409 and "Scan the bin and the product first" in r.text  # line b was never scanned
    assert scan(b, "bin", "03-05-02").status_code == 200 and scan(b, "product", w["mats"][0]).status_code == 200
    before = [_stock(w["plant"], m) for m in w["mats"][:2]]
    r = api.post(f"/v1/tasks/{task['id']}/post-requests", json=body, headers=_h(w["op"]))
    assert r.status_code == 202 and r.json()["status"] == "queued", r.text
    _drain(w["tenant"])
    doc = _field(w["tenant"], "SELECT status, movement_type FROM field.erp_document WHERE id = %s",
                 (r.json()["posting_request_id"],))
    assert doc == [("posted", "601")]
    assert [_stock(w["plant"], m) for m in w["mats"][:2]] == [before[0] - 2, before[1] - 3]
    bins = _field(w["tenant"], "SELECT storage_bin, quantity FROM field.bin_stock WHERE site_id = %s ORDER BY 1",
                  (w["site"],))
    assert [(x, float(q)) for x, q in bins] == [("02-01-01", 47.0), ("03-05-02", 48.0)]


def _count_task(w: dict[str, Any], bin_: str) -> dict[str, Any]:
    r = api.post("/v1/pi-documents", json={"site_id": w["site"], "plant": w["plant"], "storage_location": "101A",
                                           "items": [{"bin": bin_, "material": w["mats"][2]}]}, headers=_h(w["planner"]))
    assert r.status_code == 201, r.text
    return next(t for t in _tasks(w, type="count") if t["id"] == r.json()["task_id"])


def _count_and_finish(w: dict[str, Any], token: str, task: dict[str, Any], qty: float) -> httpx.Response:
    ln = task["lines"][0]
    r = api.post("/v1/count-records", json={"task_line_id": ln["id"], "value": qty, "unit": "EA", "source": "manual"},
                 headers=_h(token))
    if r.status_code != 201:
        return r
    staged = [(ln["id"], qty)]
    return api.post(f"/v1/tasks/{task['id']}/post-requests", json={"lines": [ln["id"]], "staged_hash": _hash(staged),
                    "confirm": {"method": "touch"}}, headers=_h(token))


def test_count_within_tolerance_posts_and_beyond_needs_approval_and_recount(wh: dict[str, Any]) -> None:
    """FR3.029 blind, FR3.031 tolerance, FR3.032 / FR3.033 recount, FR3.034 approval, 701/702 in erp-sim (T3.039-T3.045)."""
    w = wh
    mat = w["mats"][2]
    _put_stock(w, "03-05-01", mat, 100)
    task = _count_task(w, "03-05-01")
    assert task["title"] == "Count bin 03-05-01" and "blind count" in task["subtitle"]
    assert all("expected_qty" not in ln and "counted_qty" not in ln for ln in task["lines"])
    r = _count_and_finish(w, w["op"], task, 99)
    assert r.status_code == 202 and r.json()["status"] == "queued", r.text
    _drain(w["tenant"])
    assert _stock(w["plant"], mat) == 99
    assert _field(w["tenant"], "SELECT quantity FROM field.bin_stock WHERE site_id = %s", (w["site"],)) == [(Decimal("99.000"),)]
    assert _tasks(w, type="count", status="done")[0]["id"] == task["id"]

    t2 = _count_task(w, "03-05-01")
    r = _count_and_finish(w, w["op"], t2, 80)
    assert r.status_code == 202 and r.json()["status"] == "awaiting_approval", r.text
    assert "value_abs" not in r.json()  # never the difference to the operator
    assert any(e["kind"] == "count.awaiting_approval" for e in _events(w["op"], w["device"]))
    r = api.get("/v1/approval-requests", headers={"Authorization": f"Bearer {w['sup']}"})
    apr = next(a for a in r.json()["items"] if a["task_id"] == t2["id"])
    assert (apr["bin"], apr["material"], apr["book_qty"], apr["counted_qty"], apr["difference_qty"]) == \
        ("03-05-01", mat, 99.0, 80.0, -19.0)
    assert apr["can_decide"] is True and apr["sod_note"] is None and apr["recount_count"] == 0
    op_view = api.get("/v1/approval-requests", headers={"Authorization": f"Bearer {w['op']}"})
    assert op_view.status_code == 403  # operators never see the book

    r = api.post(f"/v1/tasks/{t2['id']}/recount", json={}, headers=_h(w["sup"]))
    assert r.status_code == 201, r.text
    rc = r.json()
    assert rc["count_round"] == 2 and rc["reason"].startswith("Requested by an exception case")
    assert next(a for a in api.get("/v1/approval-requests", params={"status": "cancelled"},
                headers={"Authorization": f"Bearer {w['sup']}"}).json()["items"])["task_id"] == t2["id"]
    recount = next(t for t in _tasks(w, type="count", status="open") if t["id"] == rc["task_id"])
    assert recount["reason"] == rc["reason"] and recount["title"] == "Recount bin 03-05-01"
    r = _count_and_finish(w, w["op"], recount, 80)
    assert r.status_code == 409 and r.json()["code"] == "FIELD-PI-409-RECOUNT-SAME-OPERATOR"
    r = _count_and_finish(w, w["op2"], recount, 80)
    assert r.status_code == 202 and r.json()["status"] == "awaiting_approval", r.text
    apr = next(a for a in api.get("/v1/approval-requests", headers={"Authorization": f"Bearer {w['sup']}"}).json()["items"]
               if a["task_id"] == rc["task_id"])
    assert apr["recount_count"] == 1 and set(apr["excluded_principals"]) == {"op-1", "op-2"}
    r = api.post(f"/v1/approval-requests/{apr['id']}/decide", json={"decision": "approve", "reason": "confirmed"},
                 headers=_h(w["sup"]))
    assert r.status_code == 200 and r.json()["status"] == "approved", r.text
    _drain(w["tenant"])
    assert _stock(w["plant"], mat) == 80  # frozen book 99, counted 80: 702 of 19
    assert next(t for t in _tasks(w, type="count") if t["id"] == rc["task_id"])["status"] == "done"
    r = api.post(f"/v1/tasks/{rc['task_id']}/recount", json={}, headers=_h(w["sup"]))
    assert r.status_code == 409


TOWER_SLOTS = (("A", "S1"), ("A", "S2"), ("A", "S3"), ("B", "S1"))


@pytest.fixture
def tower() -> dict[str, Any]:
    tenant, site = str(uuid.uuid4()), str(uuid.uuid4())
    fl = f"T{uuid.uuid4().hex[:6].upper()}-TWR"
    _erp("INSERT INTO erpsim.functional_location (client, func_loc, description, kind) VALUES ('100', %s, 't', 'tower_site')",
         (fl,))
    serials: dict[str, str] = {}
    for sector in ("A", "B"):
        _erp("INSERT INTO erpsim.functional_location (client, func_loc, description, superior_func_loc, kind, sector_code)"
             " VALUES ('100', %s, 's', %s, 'sector', %s)", (f"{fl}-{sector}", fl, sector))
    for n, (sector, slot) in enumerate(TOWER_SLOTS):
        floc = f"{fl}-{sector}-{slot}"
        _erp("INSERT INTO erpsim.functional_location (client, func_loc, description, superior_func_loc, kind, sector_code)"
             " VALUES ('100', %s, 'slot', %s, 'rack_slot', %s)", (floc, f"{fl}-{sector}", sector))
        serials[floc] = f"RRU-{uuid.uuid4().hex[:8].upper()}"
        _erp("INSERT INTO erpsim.equipment (client, equipment_no, material_no, serial_no, func_loc, status)"
             " VALUES ('100', %s, 'MAT-RRU-01', %s, %s, 'installed')",
             (f"18{random.randint(100000, 999999)}{n}", serials[floc], floc))
    spare = f"RRU-{uuid.uuid4().hex[:8].upper()}"
    _erp("INSERT INTO erpsim.equipment (client, equipment_no, material_no, serial_no, func_loc, status)"
         " VALUES ('100', %s, 'MAT-RRU-01', %s, NULL, 'available')", (f"17{random.randint(1000000, 9999999)}", spare))
    _field(tenant, "INSERT INTO field.site (id, tenant_id, code, name, kind, status) VALUES (%s, %s, %s, 'T', 'tower',"
                   " 'active')", (site, tenant, fl))
    base = create_dev_token("tech-1", tenant, ["field.technician"], site_ids=[site])
    dev = _device(base)
    tech = create_dev_token("tech-1", tenant, ["field.technician", "field.operator"], site_ids=[site], device_id=dev)
    sup = create_dev_token("sup-1", tenant, ["field.supervisor"], site_ids=["*"])
    return {"tenant": tenant, "site": site, "fl": fl, "serials": serials, "spare": spare, "tech": tech, "sup": sup,
            "device": dev}


def test_tower_audit_reconciles_and_swap_posts_through_tower_queue(tower: dict[str, Any]) -> None:
    """T4.005 import, T4.013 sector audit, T4.015 serial_mismatch, T4.017 queue, FR4.031 swap via EQUIP queue (T4.022)."""
    t = tower
    erp = TestClient(erp_app)
    out = sync_tower_installed_base(t["tenant"], t["site"], t["fl"], "http://testserver", ADMIN, client=erp)
    assert out == {"locations": 7, "equipment": 4}
    audit = generate_audit_task(t["tenant"], t["site"], sector_code="A")
    assert audit["title"] == "Sector A audit" and audit["line_count"] == 3

    def tasks(type_: str) -> list[dict[str, Any]]:
        r = api.get("/v1/tasks", params={"site_id": t["site"], "type": type_}, headers={"Authorization": f"Bearer {t['tech']}"})
        assert r.status_code == 200, r.text
        return list(r.json()["items"])

    a = tasks("audit")[0]
    assert [ln["position"] for ln in a["lines"]] == ["Sector A · slot 1", "Sector A · slot 2", "Sector A · slot 3"]
    assert [ln["expected_serial"] for ln in a["lines"]] == [t["serials"][f"{t['fl']}-A-{s}"] for s in ("S1", "S2", "S3")]
    assert a["lines"][0]["material"] == "MAT-RRU-01" and a["lines"][0]["description"] == "RRU"
    l1, l2, l3 = a["lines"]

    def scan(task: dict[str, Any], ln: dict[str, Any], code: str, role: str | None = None) -> httpx.Response:
        body: dict[str, Any] = {"kind": "serial", "code": code}
        if role:
            body["role"] = role
        return api.post(f"/v1/tasks/{task['id']}/lines/{ln['id']}/confirmations", json=body, headers=_h(t["tech"]))

    assert scan(a, l1, l1["expected_serial"].lower()).json() == {"ok": True, "match": True, "line_status": "confirmed"}
    stranger = f"RRU-{uuid.uuid4().hex[:8].upper()}"
    assert scan(a, l2, stranger).json()["match"] is False
    r = api.post(f"/v1/tasks/{a['id']}/post-requests", json={"lines": [ln["id"] for ln in a["lines"]],
                 "staged_hash": _hash([(ln["id"], 0.0) for ln in a["lines"]]), "confirm": {"method": "touch"}},
                 headers=_h(t["tech"]))
    assert r.status_code == 409 and "not checked yet" in r.text
    r = api.post(f"/v1/tasks/{a['id']}/lines/{l3['id']}/flags", json={"flag": "missing", "reason": "inaccessible"},
                 headers=_h(t["tech"]))
    assert r.status_code == 200 and r.json()["status"] == "flagged"
    r = api.post(f"/v1/tasks/{a['id']}/post-requests", json={"lines": [ln["id"] for ln in a["lines"]],
                 "staged_hash": _hash([(ln["id"], 0.0) for ln in a["lines"]]), "confirm": {"method": "touch"}},
                 headers=_h(t["tech"]))
    assert r.status_code == 202, r.text
    rec = r.json()["reconciliation"]
    assert (r.json()["status"], rec["matched"], rec["serial_mismatch"], rec["erp_only"], rec["misplaced"]) == \
        ("completed", 1, 1, 1, 0)
    queue = api.get("/v1/mismatches", params={"site_id": t["site"]}, headers={"Authorization": f"Bearer {t['sup']}"}).json()
    found = {(m["class"], m["expected_serial"], m["found_serial"], m["reason"], m["captured_by"]) for m in queue["items"]}
    assert ("serial_mismatch", l2["expected_serial"], stranger, None, "tech-1") in found
    assert ("erp_only", l3["expected_serial"], None, "inaccessible", None) in found
    progress = api.get(f"/v1/audits/{a['id']}/progress", headers={"Authorization": f"Bearer {t['sup']}"}).json()
    assert progress["expected_count"] == 3 and progress["percent"] == 33.3

    target = f"{t['fl']}-A-S3"
    swap = create_swap_task(t["tenant"], t["site"], t["serials"][target])
    s = next(x for x in tasks("swap") if x["id"] == swap["id"])
    ln = s["lines"][0]
    assert (s["title"], ln["position"], ln["expected_serial"]) == ("Swap RRU at Sector A · slot 3", "Sector A · slot 3",
                                                                    t["serials"][target])
    assert scan(s, ln, t["spare"], "old").json()["title"] == f"That is unit {t['spare']}. The unit to remove is {ln['expected_serial']}."
    assert scan(s, ln, t["spare"], "new").json()["title"].startswith("Scan the unit you remove first")
    assert scan(s, ln, ln["expected_serial"], "old").status_code == 200
    assert scan(s, ln, t["serials"][f"{t['fl']}-A-S1"], "new").json()["title"].startswith("Unit ")  # installed elsewhere
    assert scan(s, ln, t["spare"], "new").json()["line_status"] == "confirmed"
    r = api.post(f"/v1/tasks/{s['id']}/post-requests", json={"lines": [ln["id"]], "staged_hash": _hash([(ln["id"], 0.0)]),
                 "confirm": {"method": "touch"}}, headers=_h(t["tech"]))
    assert r.status_code == 202 and r.json()["queue_key"] == f"EQUIP:{t['fl']}", r.text
    adapter = SAPEquipmentAdapter(base_url="http://testserver", client=erp)
    assert process_next_tower_job(t["tenant"], f"EQUIP:{t['fl']}", adapter=adapter, db_url=ADMIN)["status"] == "completed"
    assert process_next_tower_job(t["tenant"], f"EQUIP:{t['fl']}", adapter=adapter, db_url=ADMIN)["status"] == "completed"
    assert _erp("SELECT func_loc FROM erpsim.equipment WHERE serial_no = %s", (ln["expected_serial"],)) == [(None,)]
    assert _erp("SELECT func_loc FROM erpsim.equipment WHERE serial_no = %s", (t["spare"],)) == [(target,)]
    assert next(x for x in tasks("swap") if x["id"] == s["id"])["status"] == "done"
    eq = _field(t["tenant"], "SELECT serial_no, status FROM field.equipment WHERE serial_no IN (%s, %s) ORDER BY status",
                (ln["expected_serial"], t["spare"]))
    assert eq == [(ln["expected_serial"], "dismantled"), (t["spare"], "installed")]
    ev = [e for e in _events(t["tech"], t["device"]) if e["kind"] == "erp.posted"]
    assert ev and ev[-1]["payload"]["task_id"] == s["id"] and ev[-1]["payload"]["doc_number"]


def test_swap_dismantle_conflict_holds_the_tower_queue(tower: dict[str, Any]) -> None:
    """T4.064 / FR4.060: the unit was moved in SAP after the technician saw it -> queue held, case opened, no post."""
    t = tower
    erp = TestClient(erp_app)
    sync_tower_installed_base(t["tenant"], t["site"], t["fl"], "http://testserver", ADMIN, client=erp)
    target = f"{t['fl']}-A-S2"
    swap = create_swap_task(t["tenant"], t["site"], t["serials"][target])
    line = swap["line_id"]
    for role, code in (("old", t["serials"][target]), ("new", t["spare"])):
        r = api.post(f"/v1/tasks/{swap['id']}/lines/{line}/confirmations", json={"kind": "serial", "code": code, "role": role},
                     headers=_h(t["tech"]))
        assert r.status_code == 200, r.text
    r = api.post(f"/v1/tasks/{swap['id']}/post-requests", json={"lines": [line], "staged_hash": _hash([(str(line), 0.0)]),
                 "confirm": {"method": "touch"}}, headers=_h(t["tech"]))
    assert r.status_code == 202, r.text
    _erp("UPDATE erpsim.equipment SET func_loc = %s WHERE serial_no = %s", (f"{t['fl']}-B-S1", t["serials"][target]))
    adapter = SAPEquipmentAdapter(base_url="http://testserver", client=erp)
    res = process_next_tower_job(t["tenant"], f"EQUIP:{t['fl']}", adapter=adapter, db_url=ADMIN)
    assert res is not None and res["status"] == "held" and "location mismatch" in res["reason"]
    assert process_next_tower_job(t["tenant"], f"EQUIP:{t['fl']}", adapter=adapter, db_url=ADMIN)["status"] == "held"
    jobs = _field(t["tenant"], "SELECT status, last_error FROM field.posting_job WHERE queue_key = %s ORDER BY seq",
                  (f"EQUIP:{t['fl']}",))
    assert jobs[0][0] == "pending" and jobs[0][1].startswith("held:") and jobs[1][0] == "pending"
    cases = _field(t["tenant"], "SELECT type, severity FROM field.exception_case WHERE dedupe_key LIKE %s",
                   (f"conflict:{t['tenant']}:%",))
    assert cases == [("replay_conflict", "S2")]


def test_tower_visit_shapes_the_phone_sends(tower: dict[str, Any]) -> None:
    """Contract §6 (T4.010 / T4.012 / T4.044): check-in by a text principal id ("tech-1"), climb events up and down
    including climb_safe_released, the safety heartbeat, check-out; an unknown event type is 422, not a 500."""
    from datetime import UTC, datetime, timedelta

    t = tower
    now = datetime.now(UTC).astimezone()
    r = api.post(f"/v1/sites/{t['site']}/visits", json={
        "permit_ref": "PTW-0042", "permit_valid_until": now.replace(hour=23, minute=59, second=59).isoformat(),
        "lat": 12.9716, "lon": 77.5946, "accuracy_m": 8.0, "captured_at": now.isoformat()}, headers=_h(t["tech"]))
    assert r.status_code == 201, r.text
    visit = r.json()["id"]
    kinds = [("harness_confirmed", {}), ("climb_safe_activated", {}), ("checkpoint_reached", {"level": 1}),
             ("climb_safe_released", {})]
    r = api.post(f"/v1/climb-sessions/{visit}/events", json={"events": [
        {"device_seq": i, "type": k, "occurred_at": (now + timedelta(seconds=i)).isoformat(), "payload": p}
        for i, (k, p) in enumerate(kinds, start=1)]}, headers=_h(t["tech"]))
    assert r.status_code == 200, r.text
    r = api.post(f"/v1/climb-sessions/{visit}/events", json={"events": [
        {"device_seq": 5, "type": "jumped", "occurred_at": now.isoformat(), "payload": {}}]}, headers=_h(t["tech"]))
    assert r.status_code == 422
    assert api.post(f"/v1/safety/visits/{visit}/check-in", json={}, headers=_h(t["tech"])).status_code == 200
    r = api.patch(f"/v1/visits/{visit}", json={"unsynced_count": 0}, headers={"Authorization": f"Bearer {t['tech']}"})
    assert r.status_code == 200, r.text
