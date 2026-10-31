"""M3 sandbox + barcodes end to end (docs/design/M3_CONTRACT.md sections 2, 3, 7), through field-api, the real
worker code and erp-sim (in-process ASGI, reached through the simulator adapter), on Postgres with RLS.

- barcodes: SAMPLE materials carry barcode = material number in erp-sim; the worker's material sync writes
  field.material_barcode; task lines list them; a product confirmation accepts any of them.
- site mode: GET /v1/sites shows it; only field.admin changes it, audited.
- sandbox receipt: an empty delivery in erp-sim and its task at once; a never-seen barcode becomes HOME-nnnn;
  soft pegging (delivery quantity = counted) then GR 101 marked sandbox; refused on a production site.
- sandbox count: a new box posts 561 (initial entry) for the counted quantity; a box with book stock posts a
  PI difference; production never posts 561.
- the section-7 seams resolve_code / add_item with their exact signatures.
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
from field_api.auth.jwt import Principal, create_dev_token, verify_token
from field_api.codes.resolve import resolve_code
from field_api.errors import FieldError
from field_api.sandbox import erp as sandbox_erp
from field_api.sandbox.service import add_item
from field_sap.sim.adapter import SimAdapter
from field_worker.material_sync import MaterialCacheSynchronizer
from field_worker.posting.queue import PostingQueueWorker
from field_worker.warehouse.ibd_import import poll_and_import_inbound_deliveries

pytestmark = pytest.mark.unit

ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
ERPSIM = ADMIN.rsplit("/", 1)[0] + "/erpsim"
api = TestClient(app)


def _h(token: str, key: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": key or str(uuid.uuid4())}


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


def _drain(tenant: str) -> int:
    worker = PostingQueueWorker(erp_port=SimAdapter(app=erp_app), db_url=ADMIN)

    async def run() -> int:
        n = 0
        while await worker.process_one_job(tenant):
            n += 1
            assert n < 50
        return n

    return asyncio.run(run())


def _doc(doc: str, year: str) -> dict[str, Any]:
    r = TestClient(erp_app).get(
        "/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV/"
        f"A_MaterialDocumentHeader(MaterialDocument='{doc}',MaterialDocumentYear='{year}')",
        params={"$expand": "to_MaterialDocumentItem"})
    assert r.status_code == 200, r.text
    return dict(r.json()["d"])


def _moves(doc: dict[str, Any]) -> list[tuple[str, str, float]]:
    return sorted((i["Material"], i["GoodsMovementType"], float(i["QuantityInEntryUnit"]))
                  for i in doc["to_MaterialDocumentItem"]["results"])


def _code() -> str:
    """A barcode nobody has seen (EAN-13 shaped)."""
    return "29" + "".join(random.choice("0123456789") for _ in range(11))


@pytest.fixture(autouse=True)
def _erp_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """field-api's sandbox reaches erp-sim through the simulator adapter, here in-process (no server)."""
    monkeypatch.setattr(sandbox_erp, "get_sandbox_port", lambda: SimAdapter(app=erp_app))


@pytest.fixture
def home() -> dict[str, Any]:
    tenant = str(uuid.uuid4())
    sbx, prod = str(uuid.uuid4()), str(uuid.uuid4())
    alnum = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    plant, prod_plant = ("".join([p, *random.choices(alnum, k=3)]) for p in ("H", "P"))
    known = f"M3-{uuid.uuid4().hex[:6].upper()}"
    for p in (plant, prod_plant):
        _erp("INSERT INTO erpsim.plant (client, plant, name) VALUES ('100', %s, 'M3 test') ON CONFLICT DO NOTHING", (p,))
    _erp("INSERT INTO erpsim.material (client, material_no, description, base_uom) VALUES ('100', %s, 'Known part', 'EA')",
         (known,))
    _erp("INSERT INTO erpsim.material_barcode (client, material_no, barcode, uom, is_main) VALUES ('100', %s, %s, 'EA', true)",
         (known, known))
    _erp("INSERT INTO erpsim.stock (client, plant, storage_location, material_no, quantity, uom)"
         " VALUES ('100', %s, '0001', %s, 10, 'EA')", (plant, known))
    _field(tenant, "INSERT INTO field.site (id, tenant_id, code, name, kind, erp_plant, erp_storage_locations, status, mode)"
                   " VALUES (%s, %s, %s, 'Home (sandbox)', 'warehouse', %s, '{0001}', 'active', 'sandbox')",
           (sbx, tenant, f"HOME-{plant}", plant))
    _field(tenant, "INSERT INTO field.site (id, tenant_id, code, name, kind, erp_plant, erp_storage_locations, status)"
                   " VALUES (%s, %s, %s, 'M3 DC', 'warehouse', %s, '{0001}', 'active')",
           (prod, tenant, f"DC-{prod_plant}", prod_plant))
    admin = create_dev_token("adm", tenant, ["field.admin"], site_ids=["*"])
    for site in (sbx, prod):
        r = api.post("/v1/locations", json={"site_id": site, "kind": "zone", "code": "Z"}, headers=_h(admin))
        assert r.status_code == 201, r.text
        zone = r.json()["id"]
        for b in ("HOME-A", "HOME-B"):
            r = api.post("/v1/locations", json={"site_id": site, "parent_id": zone, "kind": "position", "code": b,
                                                "erp_ref": f"{site[:8]}/{b}", "erp_ref_type": "storage_bin"},
                         headers=_h(admin))
            assert r.status_code == 201, r.text
    for p in (plant, prod_plant):  # the worker's material sync: materials and their barcodes (contract section 2)
        sync = MaterialCacheSynchronizer(db_url=ADMIN, erp_port=SimAdapter(app=erp_app))
        asyncio.run(sync.sync_plant_materials(tenant_id=tenant, plant=p, page_size=500))
    op = create_dev_token("op-1", tenant, ["field.operator"], site_ids=[sbx, prod])
    op2 = create_dev_token("op-2", tenant, ["field.operator"], site_ids=[sbx, prod])
    sup = create_dev_token("sup-1", tenant, ["field.supervisor"], site_ids=["*"])
    return {"tenant": tenant, "sbx": sbx, "prod": prod, "plant": plant, "prod_plant": prod_plant, "known": known,
            "admin": admin, "op": op, "op2": op2, "sup": sup}


def _tasks(h: dict[str, Any], site: str, **params: str) -> list[dict[str, Any]]:
    r = api.get("/v1/tasks", params={"site_id": site, **params}, headers={"Authorization": f"Bearer {h['op']}"})
    assert r.status_code == 200, r.text
    return list(r.json()["items"])


def _task(h: dict[str, Any], site: str, task_id: str) -> dict[str, Any]:
    return next(t for t in _tasks(h, site) if t["id"] == task_id)


def test_erp_sim_barcodes_read_the_s4_way() -> None:
    """erpsim.material_barcode (MEAN): SAMPLE materials carry barcode = material number, read as
    A_ProductUnitsOfMeasureEAN and as $expand on A_ProductPlant (M3-S01)."""
    erp = TestClient(erp_app)
    r = erp.get("/sap/opu/odata/sap/API_PRODUCT_SRV/A_ProductUnitsOfMeasureEAN",
                params={"$filter": "ProductStandardID eq 'SAMPLE-MAT-0001'"})
    assert r.status_code == 200
    assert [(e["Product"], e["IsMainGlobalTradeItemNumber"]) for e in r.json()["d"]["results"]] == [("SAMPLE-MAT-0001", True)]
    r = erp.get("/sap/opu/odata/sap/API_PRODUCT_SRV/A_ProductPlant",
                params={"$filter": "Plant eq '1010'", "$top": "500", "$expand": "to_ProductUnitsOfMeasureEAN"})
    samples = [p for p in r.json()["d"]["results"] if p["Product"].startswith("SAMPLE-MAT-")]
    assert len(samples) == 50
    assert all([e["ProductStandardID"] for e in p["to_ProductUnitsOfMeasureEAN"]["results"]] == [p["Product"]]
               for p in samples)
    assert not any(p["Product"].startswith("HOME-") for p in r.json()["d"]["results"])  # sandbox plants only
    assert erp.get("/sap/opu/odata/sap/API_PRODUCT_SRV/A_ProductUnitsOfMeasureEAN",
                   params={"$filter": "Description eq 'x'"}).status_code == 400
    # the sandbox admin routes need the simulator admin token
    assert erp.post("/_sim/sandbox/materials", json={"Plant": "1010", "Description": "x", "Barcode": "1"}).status_code == 401


def test_site_mode_is_listed_and_only_an_admin_changes_it(home: dict[str, Any]) -> None:
    """field.site.mode: GET /v1/sites carries it; field.site.edit alone cannot change it; changes are audited (M3-S02)."""
    h = home
    items = api.get("/v1/sites", headers={"Authorization": f"Bearer {h['sup']}"}).json()["items"]
    assert {i["id"]: i["mode"] for i in items} == {h["sbx"]: "sandbox", h["prod"]: "production"}
    site = api.get(f"/v1/sites/{h['prod']}", headers={"Authorization": f"Bearer {h['sup']}"})
    etag = site.headers["ETag"]
    r = api.patch(f"/v1/sites/{h['prod']}", json={"mode": "sandbox"},
                  headers={"Authorization": f"Bearer {h['sup']}", "If-Match": etag})
    assert r.status_code == 403 and r.json()["code"] == "FIELD-AUTH-403-PERMISSION"
    r = api.patch(f"/v1/sites/{h['prod']}", json={"mode": "nonsense"},
                  headers={"Authorization": f"Bearer {h['admin']}", "If-Match": etag})
    assert r.status_code == 422
    r = api.patch(f"/v1/sites/{h['prod']}", json={"mode": "sandbox"},
                  headers={"Authorization": f"Bearer {h['admin']}", "If-Match": etag})
    assert r.status_code == 200 and r.json()["mode"] == "sandbox", r.text
    r = api.patch(f"/v1/sites/{h['prod']}", json={"mode": "production"},
                  headers={"Authorization": f"Bearer {h['admin']}", "If-Match": r.headers["ETag"]})
    assert r.status_code == 200 and r.json()["mode"] == "production"
    audit = _field(h["tenant"], "SELECT payload->>'from', payload->>'to', payload->>'by' FROM field.outbox"
                                " WHERE event_type = 'site.mode_changed' AND aggregate_id = %s ORDER BY created_at",
                   (h["prod"],))
    assert audit == [("production", "sandbox", "adm"), ("sandbox", "production", "adm")]
    r = api.post("/v1/sites", json={"code": f"S-{uuid.uuid4().hex[:6].upper()}", "name": "x", "kind": "warehouse",
                                    "mode": "sandbox"}, headers=_h(h["sup"]))
    assert r.status_code == 403


def test_sandbox_receipt_new_barcode_soft_pegging_gr_101(home: dict[str, Any]) -> None:
    """Contract section 3: empty receipt at once, a never-seen barcode -> HOME-nnnn, soft pegging, GR 101 sandbox;
    the same code refused on the production site (M3-S03, M3-S04)."""
    h = home
    r = api.post("/v1/sandbox/receipts", json={"site_id": h["prod"]}, headers=_h(h["op"]))
    assert r.status_code == 403 and r.json()["code"] == "FIELD-SBX-403-PRODUCTION"
    r = api.post("/v1/sandbox/receipts", json={"site_id": h["sbx"]}, headers=_h(h["op"]))
    assert r.status_code == 201, r.text
    rec = r.json()
    assert set(rec) == {"task_id", "ref_doc_no"}
    task = _task(h, h["sbx"], rec["task_id"])
    assert task["type"] == "receive" and task["lines"] == [] and task["ref_doc_no"] == rec["ref_doc_no"]
    assert len(rec["ref_doc_no"]) == 10 and rec["ref_doc_no"].startswith("19")  # never reused after an erp-sim reset
    assert _erp("SELECT status, header_data->>'sandbox' FROM erpsim.inbound_delivery WHERE delivery_document = %s",
                (rec["ref_doc_no"],)) == [("open", "true")]

    code = _code()
    assert api.get(f"/v1/codes/{code}", params={"site_id": h["sbx"]},
                   headers={"Authorization": f"Bearer {h['op']}"}).json() == {
        "code": code, "kind": "unknown", "material": None, "bin": None, "site_mode": "sandbox"}
    key = str(uuid.uuid4())
    r = api.post(f"/v1/sandbox/tasks/{rec['task_id']}/items", json={"code": code, "description": "Blue shoe box", "qty": 1},
                 headers=_h(h["op"], key))
    assert r.status_code == 201, r.text
    item = r.json()
    assert set(item) == {"line_id", "material", "created_material"}
    assert item["created_material"] is True and item["material"].startswith("HOME-")
    again = add_item(verify_token(h["op"]), rec["task_id"], code, "Blue shoe box", Decimal(1), key)
    assert again == {"line_id": item["line_id"], "material": item["material"], "created_material": False}
    r = api.post(f"/v1/sandbox/tasks/{rec['task_id']}/items", json={"code": code, "description": "same box"},
                 headers=_h(h["op"]))
    assert r.status_code == 201 and r.json()["line_id"] == item["line_id"]  # the same material twice: one line
    known = api.post(f"/v1/sandbox/tasks/{rec['task_id']}/items", json={"code": h["known"].lower()}, headers=_h(h["op"]))
    assert known.status_code == 201 and known.json() == {**known.json(), "material": h["known"], "created_material": False}

    looked = api.get(f"/v1/codes/{code}", params={"site_id": h["sbx"]}, headers={"Authorization": f"Bearer {h['op']}"})
    assert looked.json() == {"code": code, "kind": "material", "site_mode": "sandbox", "bin": None,
                             "material": {"material": item["material"], "description": "Blue shoe box", "uom": "EA"}}
    bin_ = api.get("/v1/codes/home-a", params={"site_id": h["sbx"]}, headers={"Authorization": f"Bearer {h['op']}"})
    assert (bin_.json()["kind"], bin_.json()["bin"]) == ("bin", "HOME-A")
    elsewhere = api.get(f"/v1/codes/{code}", params={"site_id": h["prod"]}, headers={"Authorization": f"Bearer {h['op']}"})
    assert (elsewhere.json()["kind"], elsewhere.json()["site_mode"]) == ("unknown", "production")

    task = _task(h, h["sbx"], rec["task_id"])
    line = next(ln for ln in task["lines"] if ln["id"] == item["line_id"])
    assert line["barcodes"] == [code] and line["expected_qty"] == 1.0 and line["line_no"] == 10
    kline = next(ln for ln in task["lines"] if ln["material"] == h["known"])
    assert kline["barcodes"] == [h["known"]]
    r = api.post(f"/v1/tasks/{rec['task_id']}/lines/{line['id']}/confirmations", json={"kind": "product", "code": code},
                 headers=_h(h["op"]))
    assert r.status_code == 200, r.text
    r = api.post(f"/v1/tasks/{rec['task_id']}/lines/{line['id']}/confirmations", json={"kind": "product", "code": h["known"]},
                 headers=_h(h["op"]))
    assert r.status_code == 409 and r.json()["code"] == "FIELD-TASK-409-WRONG-CODE"

    staged = []
    for ln, qty in ((line, 3.0), (kline, 2.0)):
        r = api.post("/v1/count-records", json={"task_line_id": ln["id"], "value": qty, "unit": "EA", "source": "manual"},
                     headers=_h(h["op"]))
        assert r.status_code == 201, r.text
        staged.append((ln["id"], qty))
    r = api.post(f"/v1/tasks/{rec['task_id']}/post-requests", json={"lines": [s[0] for s in staged],
                 "staged_hash": _hash(staged), "confirm": {"method": "touch"}}, headers=_h(h["op"]))
    assert r.status_code == 202 and r.json()["status"] == "queued", r.text  # 3 counted vs 1 expected: no tolerance stop
    assert _drain(h["tenant"]) == 3
    gr = _field(h["tenant"], "SELECT doc_number, fiscal_year, movement_type, status FROM field.erp_document WHERE id = %s",
                (r.json()["posting_request_id"],))[0]
    assert gr[2:] == ("101", "posted")
    doc = _doc(gr[0], gr[1])
    assert _moves(doc) == sorted([(item["material"], "101", 3.0), (h["known"], "101", 2.0)])
    assert doc["YY1_FieldSandbox"] is True and doc["YY1_FieldSimulated"] is False
    items = _erp("SELECT material_no, delivery_qty, actual_qty FROM erpsim.inbound_delivery_item"
                 " WHERE delivery_document = %s ORDER BY item_no", (rec["ref_doc_no"],))
    assert [(m, float(d), float(a)) for m, d, a in items] == [(item["material"], 3.0, 3.0), (h["known"], 2.0, 2.0)]
    assert next(t for t in _tasks(h, h["sbx"], status="done") if t["id"] == rec["task_id"])["lines"][0]["expected_qty"] == 3.0
    put = [t for t in _tasks(h, h["sbx"], type="putaway") if t["ref_doc_no"] == gr[0]]
    assert len(put) == 1 and {ln["bin"] for ln in put[0]["lines"]} <= {"HOME-A", "HOME-B"}

    # the worker's delivery import never makes a second task for a sandbox receipt
    async def poll() -> tuple[int, int, list[dict[str, Any]]]:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=erp_app), base_url="http://erp") as cl:
            return await poll_and_import_inbound_deliveries(tenant_id=h["tenant"], site_id=h["sbx"], plant=h["plant"],
                                                            erp_url="http://erp", db_url=ADMIN, client=cl)
    created, _lines, conflicts = asyncio.run(poll())
    assert (created, conflicts) == (0, [])
    n = _field(h["tenant"], "SELECT count(*) FROM field.task WHERE ref_doc_no = %s AND type = 'receive'"
                            " AND tenant_id = %s", (rec["ref_doc_no"], h["tenant"]))
    assert n == [(1,)]

    # production: an ERP delivery line refuses the sandbox code, and a production task takes no sandbox items
    deliv = f"18{random.randint(10_000_000, 99_999_999)}"
    _erp("INSERT INTO erpsim.inbound_delivery (client, delivery_document, plant, storage_location, status, header_data)"
         " VALUES ('100', %s, %s, '0001', 'open', '{\"Vendor\": \"V-1\"}')", (deliv, h["prod_plant"]))
    _erp("INSERT INTO erpsim.inbound_delivery_item (client, delivery_document, item_no, material_no, delivery_qty,"
         " actual_qty, uom, status) VALUES ('100', %s, '000010', %s, 4, 0, 'EA', 'open')", (deliv, h["known"]))

    async def poll_prod() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=erp_app), base_url="http://erp") as cl:
            await poll_and_import_inbound_deliveries(tenant_id=h["tenant"], site_id=h["prod"], plant=h["prod_plant"],
                                                     erp_url="http://erp", db_url=ADMIN, client=cl)
    asyncio.run(poll_prod())
    ptask = next(t for t in _tasks(h, h["prod"], type="receive") if t["ref_doc_no"] == deliv)
    pline = ptask["lines"][0]
    assert pline["barcodes"] == [h["known"]]
    r = api.post(f"/v1/tasks/{ptask['id']}/lines/{pline['id']}/confirmations", json={"kind": "product", "code": code},
                 headers=_h(h["op"]))
    assert r.status_code == 409 and r.json()["code"] == "FIELD-TASK-409-WRONG-CODE"
    r = api.post(f"/v1/sandbox/tasks/{ptask['id']}/items", json={"code": code, "description": "box"}, headers=_h(h["op"]))
    assert r.status_code == 403 and r.json()["code"] == "FIELD-SBX-403-PRODUCTION"
    with pytest.raises(FieldError) as refused:
        add_item(verify_token(h["op"]), ptask["id"], code, "box", None, str(uuid.uuid4()))
    assert refused.value.code == "FIELD-SBX-403-PRODUCTION" and refused.value.status == 403


def test_sandbox_count_posts_561_for_new_boxes_and_a_difference_for_known_stock(home: dict[str, Any]) -> None:
    """Contract section 3 opening stock: a counted box with no book stock posts 561; one with book stock a PI
    difference; documents carry sandbox (M3-S05)."""
    h = home
    _field(h["tenant"], "INSERT INTO field.bin_stock (tenant_id, site_id, storage_bin, material_no, quantity)"
                        " VALUES (%s, %s, 'HOME-A', %s, 10)", (h["tenant"], h["sbx"], h["known"]))
    r = api.post("/v1/sandbox/counts", json={"site_id": h["prod"], "bin": "HOME-A"}, headers=_h(h["op"]))
    assert r.status_code == 403 and r.json()["code"] == "FIELD-SBX-403-PRODUCTION"
    r = api.post("/v1/sandbox/counts", json={"site_id": h["sbx"], "bin": "NOPE"}, headers=_h(h["op"]))
    assert r.status_code == 404
    r = api.post("/v1/sandbox/counts", json={"site_id": h["sbx"], "bin": "home-a"}, headers=_h(h["op"]))
    assert r.status_code == 201, r.text
    count = r.json()
    task = _task(h, h["sbx"], count["task_id"])
    assert (task["type"], task["title"], task["lines"]) == ("count", "Count bin HOME-A", [])
    code = _code()
    new = api.post(f"/v1/sandbox/tasks/{count['task_id']}/items", json={"code": code, "description": "Toolbox", "qty": 5},
                   headers=_h(h["op"]))
    assert new.status_code == 201 and new.json()["created_material"] is True, new.text
    old = api.post(f"/v1/sandbox/tasks/{count['task_id']}/items", json={"code": h["known"]}, headers=_h(h["op"]))
    assert old.status_code == 201, old.text
    task = _task(h, h["sbx"], count["task_id"])
    assert all("expected_qty" not in ln and "counted_qty" not in ln for ln in task["lines"])  # still blind
    by_id = {ln["id"]: ln for ln in task["lines"]}
    assert by_id[new.json()["line_id"]]["status"] == "counted" and by_id[old.json()["line_id"]]["status"] == "open"
    assert by_id[new.json()["line_id"]]["bin"] == "HOME-A" and by_id[new.json()["line_id"]]["barcodes"] == [code]
    r = api.post("/v1/count-records", json={"task_line_id": old.json()["line_id"], "value": 10, "unit": "EA",
                                            "source": "manual"}, headers=_h(h["op"]))
    assert r.status_code == 201
    stock_before = _erp("SELECT COALESCE(SUM(quantity), 0) FROM erpsim.stock WHERE plant = %s AND material_no = %s",
                        (h["plant"], h["known"]))[0][0]
    staged = [(new.json()["line_id"], 5.0), (old.json()["line_id"], 10.0)]
    r = api.post(f"/v1/tasks/{count['task_id']}/post-requests", json={"lines": [s[0] for s in staged],
                 "staged_hash": _hash(staged), "confirm": {"method": "touch"}}, headers=_h(h["op"]))
    assert r.status_code == 202 and r.json()["status"] == "queued", r.text
    out = r.json()
    assert out["initial_entry_request_id"] and out["posting_request_id"] != out["initial_entry_request_id"]
    _drain(h["tenant"])
    docs = dict(_field(h["tenant"], "SELECT doc_type, doc_number || '/' || fiscal_year FROM field.erp_document"
                                    " WHERE payload->>'task_id' = %s AND status = 'posted'", (count["task_id"],)))
    assert set(docs) == {"INIT_STOCK", "PI_DIFF"}
    init = _doc(*docs["INIT_STOCK"].split("/"))
    assert _moves(init) == [(new.json()["material"], "561", 5.0)] and init["YY1_FieldSandbox"] is True
    diff = _doc(*docs["PI_DIFF"].split("/"))
    assert _moves(diff) == []  # counted 10 = book 10: SAP posts a document without difference items
    assert _erp("SELECT COALESCE(SUM(quantity), 0) FROM erpsim.stock WHERE plant = %s AND material_no = %s",
                (h["plant"], new.json()["material"])) == [(Decimal("5.000"),)]
    assert _erp("SELECT COALESCE(SUM(quantity), 0) FROM erpsim.stock WHERE plant = %s AND material_no = %s",
                (h["plant"], h["known"])) == [(stock_before,)]
    bins = _field(h["tenant"], "SELECT material_no, quantity FROM field.bin_stock WHERE site_id = %s AND storage_bin = 'HOME-A'"
                               " ORDER BY material_no", (h["sbx"],))
    assert sorted((m, float(q)) for m, q in bins) == sorted([(new.json()["material"], 5.0), (h["known"], 10.0)])
    assert next(t for t in _tasks(h, h["sbx"], type="count", status="done") if t["id"] == count["task_id"])

    # only new boxes: one 561 document finishes the count
    c2 = api.post("/v1/sandbox/counts", json={"site_id": h["sbx"], "bin": "HOME-B"}, headers=_h(h["op"])).json()
    a = add_item(verify_token(h["op"]), c2["task_id"], _code(), "Lamp", Decimal(2), str(uuid.uuid4()))
    r = api.post(f"/v1/tasks/{c2['task_id']}/post-requests", json={"lines": [a["line_id"]],
                 "staged_hash": _hash([(a["line_id"], 2.0)]), "confirm": {"method": "touch"}}, headers=_h(h["op"]))
    assert r.status_code == 202 and r.json()["posting_request_id"] == r.json()["initial_entry_request_id"], r.text
    _drain(h["tenant"])
    assert next(t for t in _tasks(h, h["sbx"], type="count", status="done") if t["id"] == c2["task_id"])
    assert _field(h["tenant"], "SELECT status FROM field.pi_document WHERE task_id = %s", (c2["task_id"],)) == [("posted",)]


def test_production_count_never_posts_561(home: dict[str, Any]) -> None:
    """A production count of an item with no book stock is a difference beyond tolerance, never an initial entry."""
    h = home
    planner = create_dev_token("plan-1", h["tenant"], ["inventory.controller"], site_ids=[h["prod"]])
    r = api.post("/v1/pi-documents", json={"site_id": h["prod"], "plant": h["prod_plant"], "storage_location": "0001",
                                           "items": [{"bin": "HOME-A", "material": h["known"]}]}, headers=_h(planner))
    assert r.status_code == 201, r.text
    task = _task(h, h["prod"], r.json()["task_id"])
    ln = task["lines"][0]
    assert api.post("/v1/count-records", json={"task_line_id": ln["id"], "value": 5, "unit": "EA", "source": "manual"},
                    headers=_h(h["op"])).status_code == 201
    r = api.post(f"/v1/tasks/{task['id']}/post-requests", json={"lines": [ln["id"]], "staged_hash": _hash([(ln["id"], 5.0)]),
                 "confirm": {"method": "touch"}}, headers=_h(h["op"]))
    assert r.status_code == 202 and r.json()["status"] == "awaiting_approval" and "initial_entry_request_id" not in r.json()
    assert _field(h["tenant"], "SELECT count(*) FROM field.erp_document WHERE doc_type = 'INIT_STOCK' AND tenant_id = %s",
                  (h["tenant"],)) == [(0,)]


def test_section_7_seams_have_the_contract_signatures(home: dict[str, Any]) -> None:
    """resolve_code(principal, site_id, code) -> CodeLookup and add_item(principal, task_id, code, description, qty,
    idempotency_key) -> SandboxItemResult, as track A's Protocols declare them (M3-S06)."""
    import inspect

    from field_api.codes.resolve import CodeLookup
    from field_api.sandbox.service import SandboxItemResult

    assert list(inspect.signature(resolve_code).parameters) == ["principal", "site_id", "code"]
    assert list(inspect.signature(add_item).parameters) == ["principal", "task_id", "code", "description", "qty",
                                                            "idempotency_key"]
    assert set(CodeLookup.__annotations__) == {"code", "kind", "material", "bin", "site_mode"}
    assert set(SandboxItemResult.__annotations__) == {"line_id", "material", "created_material"}
    h = home
    p: Principal = verify_token(h["op"])
    assert resolve_code(p, h["sbx"], f"  {h['known'].lower()} ")["material"] == {
        "material": h["known"], "description": "Known part", "uom": "EA"}
    with pytest.raises(FieldError) as e:
        resolve_code(verify_token(create_dev_token("x", h["tenant"], ["field.operator"], site_ids=[h["prod"]])),
                     h["sbx"], "x")
    assert e.value.status == 403
    sup = verify_token(h["sup"])  # supervisors manage, they do not execute field work
    with pytest.raises(FieldError) as e:
        add_item(sup, str(uuid.uuid4()), "x", "x", None, "k")
    assert e.value.code == "FIELD-AUTH-403-PERMISSION"
