"""M5 receipts with a vision look (docs/design/M5_CONTRACT.md §1, §2; M5-V06, M5-V07) end to end: the test cases on a
sandbox site, a look over the test double of the Meta API (test code only), "receive 18, flag 2" posted as one
material document with 101 to 101A and 101 to 101Q in erp-sim (in-process ASGI, through the simulator adapter and
the real worker code), the look linked, the put-away of the good units only; on Postgres with RLS."""

from __future__ import annotations

import asyncio
import hashlib
import json
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
from field_api.ai.budget import BudgetGuard, Price
from field_api.app import app
from field_api.assistant.model import ChatModel, ProviderConfig
from field_api.auth.jwt import create_dev_token
from field_api.sandbox import erp as sandbox_erp
from field_api.vision.labels import ChatLabelReader
from field_api.vision.ports import VisionPorts
from field_api.vision.sam import Sam31Instances
from field_api.vision.service import get_vision_ports
from field_sap.sim.adapter import SimAdapter
from field_worker.posting.queue import PostingQueueWorker
from PIL import Image, ImageDraw

pytestmark = pytest.mark.unit

ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
ERPSIM = ADMIN.rsplit("/", 1)[0] + "/erpsim"
api = TestClient(app)
W, H = 1000, 800


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}


def _hash(lines: list[tuple[str, float]]) -> str:
    return hashlib.sha256("|".join(sorted(f"{lid}:{q:.3f}" for lid, q in lines)).encode()).hexdigest()


def _sql(db: str, sql: str, params: tuple[Any, ...] = (), tenant: str | None = None) -> list[tuple[Any, ...]]:
    with psycopg.connect(db, autocommit=True) as c, c.cursor() as cur:
        if tenant:
            cur.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)",
                        (tenant,))
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


def _boxes(n: int, cols: int = 5) -> list[tuple[int, int, int, int]]:
    rows = (n + cols - 1) // cols
    cw, ch = W // cols, H // rows
    return [(c * cw + 10, r * ch + 10, (c + 1) * cw - 10, (r + 1) * ch - 10) for r in range(rows) for c in range(cols)][:n]


def _photo(boxes: list[tuple[int, int, int, int]]) -> bytes:
    import io

    img = Image.new("RGB", (W, H), (230, 230, 225))
    d = ImageDraw.Draw(img)
    for b in boxes:
        d.rectangle((b[0], b[1], b[2] - 1, b[3] - 1), fill=(180, 90, 40))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def _double(boxes: list[tuple[int, int, int, int]], labels: dict[int, dict[str, Any]]) -> httpx.MockTransport:
    """The Meta API for one look (test code only): SAM boxes as SSE, Muse label JSON for the crops asked."""
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        if req.url.path.endswith("/responses"):
            recs = ",".join(f"{i}<|box;x1={b[0]};y1={b[1]};x2={b[2] - 1};y2={b[3] - 1};w={W};h={H};c=0.9|>"
                            for i, b in enumerate(boxes))
            ev = [{"type": "response.output_text.delta", "delta": "<0f>" + recs},
                  {"type": "response.completed", "response": {"usage": {"input_tokens": 0, "output_tokens": 0}}}]
            return httpx.Response(200, content="".join(f"data: {json.dumps(e)}\n\n" for e in ev).encode(),
                                  headers={"content-type": "text/event-stream"})
        wanted = [int(p["text"].split()[-1].rstrip(":")) for p in body["messages"][-1]["content"] if p["type"] == "text"]
        items = [{"n": n, "label_readable": True, "pieces_per_unit": None, "batch": None, "expiry": None,
                  "damaged": False, "damage_note": None, "label_text": None, **labels.get(n, {})} for n in wanted]
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": json.dumps({"items": items})}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 200}})

    return httpx.MockTransport(handler)


def _ports(transport: httpx.MockTransport) -> VisionPorts:
    guard = BudgetGuard(prices={"llama": {}, "baseten": {}, "meta": {
        "sam-3.1": Price(Decimal(0), Decimal(0), per_image_usd=Decimal("0.005")),
        "muse-spark-1.3": Price(Decimal("1.25"), Decimal("4.25"), Decimal("0.15"))}})
    return VisionPorts(Sam31Instances("https://api.meta.ai/v1", "sam-3.1", guard, transport),
                       (ChatLabelReader(ChatModel(ProviderConfig("meta", "https://api.meta.ai/v1", "muse-spark-1.3",
                                                                 "MODEL_API_KEY"), guard, transport)),))


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(sandbox_erp, "get_sandbox_port", lambda: SimAdapter(app=erp_app))
    monkeypatch.setenv("FIELD_CROP_DIR", str(tmp_path / "crops"))
    usage = BudgetGuard(prices={}).usage()
    monkeypatch.setenv("AI_CLOUD_ENABLED", "true")
    monkeypatch.setenv("AI_BUDGET_META_USD", str(Decimal(usage["providers"]["meta"]["spent_usd"]) + 5))
    monkeypatch.setenv("AI_DAILY_CAP_USD", str(Decimal(usage["today_usd"]) + 5))
    monkeypatch.setenv("MODEL_API_KEY", "test-key-" + "e" * 16)


@pytest.fixture
def home() -> dict[str, Any]:
    """A sandbox site on a fresh plant with storage locations HM01, 101A and 101Q (field and erp-sim), a phone with
    consent, and an operator."""
    tenant, site = str(uuid.uuid4()), str(uuid.uuid4())
    plant = "M" + "".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", k=3))
    _sql(ERPSIM, "INSERT INTO erpsim.plant (client, plant, name) VALUES ('100', %s, 'M5 test') ON CONFLICT DO NOTHING",
         (plant,))
    for sloc, name in (("HM01", "Home shelf"), ("101A", "Unrestricted"), ("101Q", "Quality area")):
        _sql(ERPSIM, "INSERT INTO erpsim.storage_location (client, plant, storage_location, name)"
                     " VALUES ('100', %s, %s, %s) ON CONFLICT DO NOTHING", (plant, sloc, name))
    _sql(ADMIN, "INSERT INTO field.site (id, tenant_id, code, name, kind, erp_plant, erp_storage_locations, status, mode)"
                " VALUES (%s, %s, %s, 'Home (sandbox)', 'warehouse', %s, '{HM01,101A,101Q}', 'active', 'sandbox')",
         (site, tenant, f"HOME-{plant}", plant), tenant)
    admin = create_dev_token("adm", tenant, ["field.admin"], site_ids=["*"])
    zone = api.post("/v1/locations", json={"site_id": site, "kind": "zone", "code": "Z"}, headers=_h(admin)).json()["id"]
    r = api.post("/v1/locations", json={"site_id": site, "parent_id": zone, "kind": "position", "code": "HOME-A",
                                        "erp_ref": f"{plant}/HOME-A", "erp_ref_type": "storage_bin"}, headers=_h(admin))
    assert r.status_code == 201, r.text
    op = create_dev_token("op-m5", tenant, ["field.operator"], site_ids=[site])
    phone = api.post("/v1/devices", json={"kind": "phone", "serial_no": f"P-{uuid.uuid4()}", "model": "Pixel"},
                     headers=_h(op)).json()["id"]
    dev = create_dev_token("op-m5", tenant, ["field.operator"], site_ids=[site], device_id=phone)
    assert api.post("/v1/consents", json={"site_id": site, "device_id": phone}, headers=_h(dev)).status_code == 201
    return {"tenant": tenant, "site": site, "plant": plant, "op": op, "dev": dev, "phone": phone}


def _capture(h: dict[str, Any], task: str, jpeg: bytes) -> str:
    r = api.post("/v1/captures", data={"metadata": json.dumps({
        "device_id": h["phone"], "task_id": task, "site_id": h["site"], "shutter_timestamp": 1, "blur_applied": True,
        "code_type": "photo", "code_value": f"look-{uuid.uuid4()}", "readability": 0.9})},
        files={"crop": ("look.jpg", jpeg, "image/jpeg")}, headers=_h(h["dev"]))
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def _look(h: dict[str, Any], case: dict[str, Any], kind: str, labels: dict[int, dict[str, Any]], n: int) -> dict[str, Any]:
    boxes = _boxes(n)
    app.dependency_overrides[get_vision_ports] = lambda: _ports(_double(boxes, labels))
    try:
        cap = _capture(h, case["task_id"], _photo(boxes))
        r = api.post("/v1/vision/looks", json={"task_id": case["task_id"], "line_id": case["line_id"],
                                                "capture_id": cap, "case": kind}, headers=_h(h["dev"]))
        assert r.status_code == 200, r.text
        first = dict(r.json())
        # M5-S01: POST answers once SAM's instances are counted; the label read runs after the response (the test
        # client runs it before returning), so GET answers the final look the checks below are about.
        assert first["final"] is False and first["source"] == "partial" and first["proposal"]["receive"] is None, first
        g = api.get(f"/v1/vision/looks/{first['look_id']}", headers=_h(h["dev"]))
    finally:
        app.dependency_overrides.pop(get_vision_ports, None)
    assert g.status_code == 200, g.text
    look = dict(g.json())
    assert look["final"] is True and look["look_id"] == first["look_id"], look
    return look


def _count(h: dict[str, Any], line: str, qty: float) -> None:
    r = api.post("/v1/count-records", json={"task_line_id": line, "value": qty, "unit": "EA", "source": "manual"},
                 headers=_h(h["dev"]))
    assert r.status_code == 201, r.text


def _post(h: dict[str, Any], task: str, line: str, qty: float, **extra: Any) -> httpx.Response:
    return api.post(f"/v1/tasks/{task}/post-requests", json={"lines": [line], "staged_hash": _hash([(line, qty)]),
                                                            "confirm": {"method": "touch"}, **extra},
                    headers=_h(h["dev"]))


def test_m5_v06_grocery_case_look_post_18_good_2_flagged(home: dict[str, Any]) -> None:
    """C1 end to end: the case receipt (20 packs, 12 pieces each) -> a look (20 seen, 2 damaged, 2 packs hold 10) ->
    "receive 18, flag 2" -> one GR: 101 18 to 101A, 101 2 to 101Q -> the look linked -> put-away of 18 only."""
    h = home
    r = api.post("/v1/sandbox/cases", json={"site_id": h["site"], "case": "grocery"}, headers=_h(h["op"]))
    assert r.status_code == 201, r.text
    case = r.json()
    assert case | {"task_id": "", "ref_doc_no": "", "line_id": "", "material": ""} == {
        "task_id": "", "ref_doc_no": "", "line_id": "", "material": "", "case": "grocery", "object": "pack",
        "expected_units": 20, "expected_pieces_per_unit": 12, "expiry_window_days": None}
    assert case["material"].startswith("HOME-")
    assert _sql(ERPSIM, "SELECT storage_location FROM erpsim.inbound_delivery WHERE delivery_document = %s",
                (case["ref_doc_no"],)) == [("101A",)]
    labels = {n: {"pieces_per_unit": 12} for n in range(1, 21)}
    labels.update({7: {"pieces_per_unit": 10}, 12: {"pieces_per_unit": 10}, 3: {"pieces_per_unit": 12, "damaged": True},
                   18: {"pieces_per_unit": 12, "damaged": True}})
    look = _look(h, case, "grocery", labels, 20)
    assert look["source"] == "model" and look["proposal"] == {
        "receive": 18, "flag": 2, "reasons": ["2 damaged", "2 packs hold 10, not 12: 4 pieces short"]}
    assert look["erp_document_id"] is None

    # the app's count after a look: value = good + flagged, flag_qty, look_id, capture_id (stream B)
    count = {"task_line_id": case["line_id"], "value": 20, "unit": "EA", "source": "manual", "flag_qty": 21,
             "look_id": look["look_id"], "capture_id": look["capture_id"]}
    bad = api.post("/v1/count-records", json=count, headers=_h(h["dev"]))
    assert bad.status_code == 422 and bad.json()["code"] == "FIELD-POST-422-FLAG-QTY"
    bad = api.post("/v1/count-records", json={**count, "flag_qty": 2, "look_id": str(uuid.uuid4())},
                   headers=_h(h["dev"]))
    assert bad.status_code == 404 and bad.json()["code"] == "FIELD-VIS-404-LOOK"
    r = api.post("/v1/count-records", json={**count, "flag_qty": 2}, headers=_h(h["dev"]))
    assert r.status_code == 201 and r.json()["flag_qty"] == 2.0, r.text
    bad = _post(h, case["task_id"], case["line_id"], 20, look_id=str(uuid.uuid4()))
    assert bad.status_code == 404 and bad.json()["code"] == "FIELD-VIS-404-LOOK"
    bad = _post(h, case["task_id"], case["line_id"], 20, look_id=look["look_id"], flag_qty={case["line_id"]: 21})
    assert bad.status_code == 422 and bad.json()["code"] == "FIELD-POST-422-FLAG-QTY"
    r = _post(h, case["task_id"], case["line_id"], 20, look_id=look["look_id"])  # the app: top-level look_id only
    assert r.status_code == 202 and r.json()["status"] == "queued", r.text
    erp_doc = r.json()["posting_request_id"]
    payload = _sql(ADMIN, "SELECT payload FROM field.erp_document WHERE id = %s", (erp_doc,), h["tenant"])[0][0]
    assert payload["look_id"] == look["look_id"] and payload["flag_qty"] == {case["line_id"]: "2.000"}
    assert _drain(h["tenant"]) == 2
    doc_no, year, status = _sql(ADMIN, "SELECT doc_number, fiscal_year, status FROM field.erp_document WHERE id = %s",
                                (erp_doc,), h["tenant"])[0]
    assert status == "posted"
    items = _sql(ERPSIM, "SELECT material_no, storage_location, quantity, movement_type, item_data FROM"
                         " erpsim.document_item WHERE doc_number = %s AND fiscal_year = %s ORDER BY line_no",
                 (doc_no, year))
    assert [(m, s, float(q), t) for m, s, q, t, _d in items] == [(case["material"], "101A", 18.0, "101"),
                                                                (case["material"], "101Q", 2.0, "101")]
    assert items[1][4].get("YY1_FieldQuality") is True and "YY1_FieldQuality" not in items[0][4]
    stock = dict(_sql(ERPSIM, "SELECT storage_location, quantity FROM erpsim.stock WHERE plant = %s AND material_no = %s",
                      (h["plant"], case["material"])))
    assert float(stock["101A"]) == 18.0 and float(stock["101Q"]) == 2.0
    got = api.get(f"/v1/vision/looks/{look['look_id']}", headers={"Authorization": f"Bearer {h['op']}"}).json()
    assert got["erp_document_id"] == erp_doc
    put = _sql(ADMIN, "SELECT l.expected_qty FROM field.task t JOIN field.task_line l ON l.task_id = t.id"
                      " WHERE t.type = 'putaway' AND t.ref_doc_no = %s AND t.site_id = %s", (doc_no, h["site"]),
               h["tenant"])
    assert [float(q) for (q,) in put] == [18.0]  # the 2 flagged packs stay in the quality area
    assert _sql(ADMIN, "SELECT flag_qty FROM field.task_line WHERE id = %s", (case["line_id"],), h["tenant"]) == [
        (Decimal("2.000"),)]


def test_m5_v06_pharmacy_case_and_a_look_is_posted_once(home: dict[str, Any]) -> None:
    """C2: 10 boxes, window 90 days; no flags -> everything to 101A; the look of another task is refused, and a look
    already posted is refused for a second receipt."""
    h = home
    r = api.post("/v1/sandbox/cases", json={"site_id": h["site"], "case": "pharmacy", "units": 4}, headers=_h(h["op"]))
    assert r.status_code == 201, r.text
    case = r.json()
    assert (case["object"], case["expected_units"], case["expiry_window_days"]) == ("box", 4, 90)
    other = api.post("/v1/sandbox/cases", json={"site_id": h["site"], "case": "pharmacy", "units": 4},
                     headers=_h(h["op"])).json()
    look = _look(h, case, "pharmacy", {n: {"batch": "B1", "expiry": "2031-01"} for n in range(1, 5)}, 4)
    assert look["proposal"] == {"receive": 4, "flag": 0, "reasons": []}
    _count(h, other["line_id"], 4)
    wrong = _post(h, other["task_id"], other["line_id"], 4, look_id=look["look_id"])
    assert wrong.status_code == 422 and wrong.json()["code"] == "FIELD-VIS-422-TASK"
    _count(h, case["line_id"], 4)
    r = _post(h, case["task_id"], case["line_id"], 4, look_id=look["look_id"])
    assert r.status_code == 202, r.text
    assert _drain(h["tenant"]) == 2
    doc_no, year = _sql(ADMIN, "SELECT doc_number, fiscal_year FROM field.erp_document WHERE id = %s",
                        (r.json()["posting_request_id"],), h["tenant"])[0]
    moves = _sql(ERPSIM, "SELECT storage_location, quantity FROM erpsim.document_item WHERE doc_number = %s"
                         " AND fiscal_year = %s", (doc_no, year))
    assert [(s, float(q)) for s, q in moves] == [("101A", 4.0)]
    # the same look on the other receipt is still refused: it is the other task's look
    again = _post(h, other["task_id"], other["line_id"], 4, look_id=look["look_id"])
    assert again.status_code == 422
    r = api.post("/v1/sandbox/cases", json={"site_id": h["site"], "case": "grocery", "units": 0}, headers=_h(h["op"]))
    assert r.status_code == 422


def test_m5_v06_spoken_flag_without_a_look_and_the_today_starter(home: dict[str, Any]) -> None:
    """The Today starter is POST /v1/sandbox/receipts {site_id, case} (the app); a spoken "flag 1" recorded with the
    count posts 1 to 101Q without a look; flag_qty on the post overrides the counted flag; a later count without a
    flag clears it."""
    h = home
    r = api.post("/v1/sandbox/receipts", json={"site_id": h["site"], "case": "pharmacy"}, headers=_h(h["op"]))
    assert r.status_code == 201 and set(r.json()) == {"task_id", "ref_doc_no"}, r.text
    task = r.json()["task_id"]
    line = _sql(ADMIN, "SELECT l.id::text, l.expected_qty, v.expiry_window_days FROM field.task_line l"
                       " JOIN field.vision_case_line v ON v.task_line_id = l.id WHERE l.task_id = %s", (task,),
                h["tenant"])
    assert [(float(q), w) for _i, q, w in line] == [(10.0, 90)]
    lid = line[0][0]
    body = {"task_line_id": lid, "value": 10, "unit": "EA", "source": "manual"}
    assert api.post("/v1/count-records", json={**body, "flag_qty": 3}, headers=_h(h["dev"])).status_code == 201
    assert api.post("/v1/count-records", json=body, headers=_h(h["dev"])).status_code == 201  # M4 body: flag cleared
    assert _sql(ADMIN, "SELECT flag_qty FROM field.task_line WHERE id = %s", (lid,), h["tenant"]) == [(Decimal(0),)]
    assert api.post("/v1/count-records", json={**body, "flag_qty": 3}, headers=_h(h["dev"])).status_code == 201
    r = _post(h, task, lid, 10, flag_qty={lid: 1})  # the post's flag wins over the counted 3
    assert r.status_code == 202, r.text
    assert _drain(h["tenant"]) == 2
    doc_no, year, payload = _sql(ADMIN, "SELECT doc_number, fiscal_year, payload FROM field.erp_document WHERE id = %s",
                                 (r.json()["posting_request_id"],), h["tenant"])[0]
    assert payload["look_id"] is None and payload["flag_qty"] == {lid: "1.000"}
    moves = _sql(ERPSIM, "SELECT storage_location, quantity FROM erpsim.document_item WHERE doc_number = %s"
                         " AND fiscal_year = %s ORDER BY line_no", (doc_no, year))
    assert [(s, float(q)) for s, q in moves] == [("101A", 9.0), ("101Q", 1.0)]


def test_m5_v06_erp_sim_refuses_an_unknown_quality_location(home: dict[str, Any]) -> None:
    """erp-sim: YY1_QualityStorageLocation must exist in the delivery's plant; the flag is at most the actual qty."""
    h = home
    case = api.post("/v1/sandbox/cases", json={"site_id": h["site"], "case": "grocery", "units": 3},
                    headers=_h(h["op"])).json()
    erp = TestClient(erp_app)
    url = (f"/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV/A_InbDeliveryItem(DeliveryDocument='{case['ref_doc_no']}',"
           "DeliveryDocumentItem='000010')")
    r = erp.patch(url, json={"ActualDeliveryQuantity": "3", "YY1_QualityQuantity": "1",
                             "YY1_QualityStorageLocation": "NOPE"}, headers={"If-Match": "*"})
    assert r.status_code == 400 and "ZSIM/SLOC-NOT-FOUND" in r.text
    r = erp.patch(url, json={"ActualDeliveryQuantity": "3", "YY1_QualityQuantity": "4",
                             "YY1_QualityStorageLocation": "101Q"}, headers={"If-Match": "*"})
    assert r.status_code == 400 and "ZSIM/QUALITY-QTY" in r.text
