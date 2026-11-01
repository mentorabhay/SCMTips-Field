"""M5 on the dev stack (docs/design/M5_CONTRACT.md §1, §2): the two test cases and their smoke (stream V).

    uv run python -m tools.dev_stack.stack m5-cases [--reset]   # C1 grocery + C2 pharmacy on "Home (sandbox)",
                                                                 # var/m5_cases.html with their QR labels
    uv run python -m tools.dev_stack.stack up --model-standin   # field-api talks to the local model stand-in
    uv run python -m tools.dev_stack.stack smoke --m5-look      # both cases: look -> proposal -> post good + flagged
                                                                 # -> 101A and 101Q in erp-sim -> the look linked
    uv run python -m tools.dev_stack.stack smoke --m5           # both cases end to end (integrator): the look smoke,
                                                                 # then claim -> supervisor decision (If-Match) ->
                                                                 # confirm -> approved -> evidence link -> signed
                                                                 # page and JSON pack

``m5-cases`` is idempotent: an open case receipt of each kind is reused; ``--reset`` cancels the open ones (their
field tasks; the sandbox deliveries stay open in erp-sim, unused) and makes new ones. Plant HOME gets storage
locations 101A (unrestricted) and 101Q (quality area) in erp-sim and on the home site, so good units go to 101A and
flagged ones to 101Q (FIELD_CASE_SLOC / FIELD_QUALITY_SLOC).

``smoke --m5-look`` needs a field-api started with ``up --model-standin`` (the stand-in answers SAM 3.1 and the
label reads from a scene the smoke sets; tools/dev_stack/model_standin.py): no real model, no key, no spend. It
makes fresh case receipts, draws a synthetic photo of the scene, uploads it through the captures API (consent and
blur gates as the app meets them) and checks every step through the real API and erp-sim.

``smoke --m5`` runs the same two cases along the phone app's own paths (C1 started by the Today starter
``POST /v1/sandbox/receipts {site_id, case}``, C2 photo sent through the upload session the app uses) and then the
claim and evidence steps of contract section 3: the operator makes the claim, a supervisor (another principal)
approves it with If-Match from the draft list item's etag and confirms within 10 s, the phone's evidence link
(``POST /v1/evidence/documents/{doc}/link?year=`` with erp.posted's doc_year) opens the signed page (SAMPLE banner,
the outlines SVG, the photo and pack hashes) and the JSON pack holds the look, the model calls, the confirm and the
approved claim.
"""

from __future__ import annotations

import io
import json
import time
import uuid
from datetime import date, timedelta
from typing import Any

import httpx

CASE_SLOCS = (("101A", "Home shelf (unrestricted)"), ("101Q", "Home quality area"))
CASE_LABELS = {"grocery": ("M5-C1-PACK", "product label · biscuit pack"),
               "pharmacy": ("M5-C2-BOX", "product label · tablet box")}


def _stack() -> Any:
    from tools.dev_stack import stack

    return stack


# --------------------------------------------------------------------------- setup
def ensure_case_slocs(state: dict[str, Any]) -> list[str]:
    """101A and 101Q in erp-sim's plant HOME and on the home site's storage locations; returns what was added."""
    import psycopg

    s = _stack()
    with psycopg.connect(s._admin_url("erpsim"), autocommit=True) as c, c.cursor() as cur:
        for sloc, name in CASE_SLOCS:
            cur.execute("INSERT INTO erpsim.storage_location (client, plant, storage_location, name)"
                        " VALUES ('100', %s, %s, %s) ON CONFLICT DO NOTHING", (s.HOME_PLANT, sloc, name))
    h = {"Authorization": f"Bearer {s._admin(state['tenant'])}"}
    r = httpx.get(s.local("field-api") + f"/v1/sites/{state['home_site']}", headers=h, timeout=10)
    r.raise_for_status()
    have = list(r.json().get("erp_storage_locations") or [])
    missing = [sl for sl, _ in CASE_SLOCS if sl not in have]
    if missing:
        r2 = httpx.patch(s.local("field-api") + f"/v1/sites/{state['home_site']}",
                         json={"erp_storage_locations": have + missing},
                         headers={**h, "If-Match": r.headers["ETag"]}, timeout=10)
        if r2.status_code != 200:
            raise SystemExit(f"could not add {missing} to the home site: HTTP {r2.status_code} {r2.text[:200]}")
    return missing


def open_cases(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The newest open (pending / in progress) case receipt of each kind on the home site."""
    import psycopg

    s = _stack()
    out: dict[str, dict[str, Any]] = {}
    with psycopg.connect(s._admin_url("field")) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, true), set_config('app.site_ids', '*', true)",
                    (state["tenant"],))
        cur.execute(
            """
            SELECT v."case", t.id, t.ref_doc_no, v.task_line_id, l.expected_qty, v.expected_pieces_per_unit,
                   v.expiry_window_days, v.object
              FROM field.vision_case_line v JOIN field.task t ON t.id = v.task_id
              JOIN field.task_line l ON l.id = v.task_line_id
             WHERE v.site_id = %s AND t.status IN ('pending', 'in_progress') ORDER BY v.created_at
            """, (state["home_site"],))
        for row in cur.fetchall():
            out[str(row[0])] = {"task_id": str(row[1]), "ref_doc_no": str(row[2]), "line_id": str(row[3]),
                                "case": str(row[0]), "expected_units": int(row[4]),
                                "expected_pieces_per_unit": row[5], "expiry_window_days": row[6], "object": row[7]}
    return out


def cancel_open_cases(state: dict[str, Any]) -> int:
    import psycopg

    s = _stack()
    with psycopg.connect(s._admin_url("field")) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, true), set_config('app.site_ids', '*', true)",
                    (state["tenant"],))
        cur.execute(
            """
            UPDATE field.task t SET status = 'cancelled', version = version + 1, updated_at = NOW()
              FROM field.vision_case_line v
             WHERE v.task_id = t.id AND v.site_id = %s AND t.status IN ('pending', 'in_progress') RETURNING t.id
            """, (state["home_site"],))
        ids = [str(r[0]) for r in cur.fetchall()]
        if ids:
            cur.execute("UPDATE field.task_line SET status = 'cancelled' WHERE task_id = ANY(%s::uuid[])"
                        " AND status NOT IN ('posted', 'cancelled')", (ids,))
        c.commit()
    return len(ids)


def create_case(token: str, site: str, case: str, **extra: Any) -> dict[str, Any]:
    s = _stack()
    r = s._sandbox_post(token, "/v1/sandbox/cases", {"site_id": site, "case": case, **extra})
    if r.status_code != 201:
        raise SystemExit(f"could not create the {case} case: HTTP {r.status_code} {r.text[:300]}")
    return dict(r.json())


def case_sections(cases: dict[str, dict[str, Any]]) -> list[tuple[str, list[tuple[str, str]]]]:
    """Label sections for render_labels: the delivery number and the product label of each case."""
    out: list[tuple[str, list[tuple[str, str]]]] = []
    for case in ("grocery", "pharmacy"):
        c = cases.get(case)
        if not c:
            continue
        if case == "grocery":
            what = f"C1 grocery delivery {c['ref_doc_no']}: {c['expected_units']} packs, " \
                   f"{c['expected_pieces_per_unit']} pieces each"
        else:
            what = f"C2 pharmacy delivery {c['ref_doc_no']}: {c['expected_units']} boxes, expiry window " \
                   f"{c['expiry_window_days']} days"
        code, caption = CASE_LABELS[case]
        out.append((what, [(c["ref_doc_no"], "delivery number (open the receipt)"), (code, caption)]))
    return out


def cmd_m5_cases(a: Any) -> int:
    s = _stack()
    s.load_env()
    s.apply_ports()
    state = s.ensure_home(json.loads(s.STATE.read_text(encoding="utf-8")) if s.STATE.exists() else {})
    added = ensure_case_slocs(state)
    if added:
        print(f"home site: storage locations {', '.join(added)} added (plant {s.HOME_PLANT} in erp-sim too)")
    if a.reset:
        print(f"reset: {cancel_open_cases(state)} open case receipt(s) cancelled")
    cases = open_cases(state)
    token = s._operator(state, state["home_site"])
    for case in ("grocery", "pharmacy"):
        if case in cases:
            print(f"{case}: open receipt {cases[case]['ref_doc_no']} reused (--reset makes a new one)")
            continue
        cases[case] = create_case(token, state["home_site"], case)
        print(f"{case}: receipt {cases[case]['ref_doc_no']} created")
    from field_api.vision.reconcile import plural

    for c in cases.values():
        extra = (f", {c['expected_pieces_per_unit']} pieces each" if c.get("expected_pieces_per_unit")
                 else f", expiry window {c.get('expiry_window_days')} days")
        print(f"  {c['case']}: delivery {c['ref_doc_no']} (task {c['task_id']}): {c['expected_units']}"
              f" {plural(str(c.get('object') or 'item'), int(c['expected_units']))}{extra}")
    state["m5_cases"] = cases
    s.STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    out = s.ROOT / "var" / "m5_cases.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(s.render_labels(case_sections(cases), time.strftime("%Y-%m-%d %H:%M")), encoding="utf-8")
    print(f"labels: {out}")
    print("On the phone (paired with `stack pair --home`): say \"new grocery delivery\" / \"new pharmacy delivery\" for"
          " another one, or open these receipts; lay the items out in one layer and say look.")
    return 0


# --------------------------------------------------------------------------- smoke
W, H = 1000, 800


def grid(n: int, cols: int) -> list[list[int]]:
    rows = (n + cols - 1) // cols
    cw, ch = W // cols, H // rows
    return [[c * cw + 12, r * ch + 12, (c + 1) * cw - 12, (r + 1) * ch - 12]
            for r in range(rows) for c in range(cols)][:n]


def draw(boxes: list[list[int]], noun: str) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), (236, 232, 222))
    d = ImageDraw.Draw(img)
    for n, b in enumerate(boxes, start=1):
        d.rectangle((b[0], b[1], b[2] - 1, b[3] - 1), fill=(170, 80 + (n * 9) % 120, 50), outline=(30, 30, 30))
        d.text((b[0] + 6, b[1] + 6), f"{noun} {n}", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def standin_url() -> str:
    import os

    return os.environ.get("FIELD_STACK_MODEL_URL", "").strip().rstrip("/") or \
        f"http://127.0.0.1:{os.environ.get('FIELD_STACK_MODEL_PORT') or 8430}"


def scenes(today: date) -> dict[str, dict[str, Any]]:
    """C1: 20 packs, 2 damaged, 2 hold 10 not 12 -> receive 18, flag 2. C2: 10 boxes, one expired, one expiring
    within 90 days, one damaged, two batches -> receive 7, flag 3."""
    groc: dict[str, dict[str, Any]] = {str(n): {"pieces_per_unit": 12, "label_text": "12 x 25 g"} for n in range(1, 21)}
    groc.update({"7": {"pieces_per_unit": 10}, "12": {"pieces_per_unit": 10},
                 "3": {"pieces_per_unit": 12, "damaged": True, "damage_note": "crushed"},
                 "18": {"pieces_per_unit": 12, "damaged": True, "damage_note": "torn"}})
    far = (today + timedelta(days=400)).strftime("%Y-%m")
    pharm: dict[str, dict[str, Any]] = {str(n): {"batch": "B2411", "expiry": far} for n in range(1, 11)}
    pharm["2"] = {"batch": "B2411", "expiry": (today - timedelta(days=40)).strftime("%Y-%m")}
    pharm["5"] = {"batch": "B2502", "expiry": (today + timedelta(days=30)).isoformat()}
    pharm["9"] = {"batch": "B2411", "expiry": far, "damaged": True, "damage_note": "dented"}
    return {"grocery": {"n": 20, "cols": 5, "labels": groc, "receive": 18, "flag": 2},
            "pharmacy": {"n": 10, "cols": 5, "labels": pharm, "receive": 7, "flag": 3}}


def start_case_as_the_app(phone: Any, site: str, case: str) -> dict[str, Any]:
    """The phone's Today starter: POST /v1/sandbox/receipts {site_id, case} -> {task_id, ref_doc_no}, then the
    line from the task list as the app reads it (default units of the case)."""
    s = _stack()
    made = s._accepted(httpx.post(f"{phone.api}/v1/sandbox/receipts", json={"site_id": site, "case": case},
                                  headers=phone._h(True), timeout=15), f"{case} starter", 201)
    task = next((t for t in phone.tasks(site, "receive") if t["id"] == made["task_id"]), None)
    s._expect(task is not None and len(task["lines"]) == 1, f"{case} starter task {made['task_id']} not listed")
    line = task["lines"][0] if task else {}
    return {"task_id": made["task_id"], "ref_doc_no": made["ref_doc_no"], "line_id": line["id"],
            "object": "pack" if case == "grocery" else "box", "expected_units": int(line["expected_qty"])}


def upload_as_the_app(phone: Any, site: str, task_id: str, jpeg: bytes, noun: str) -> str:
    """The phone's capture path (LookClient.upload): upload session -> PUT bytes -> POST /v1/captures (JSON)."""
    import hashlib

    s = _stack()
    sess = s._accepted(httpx.post(f"{phone.api}/v1/captures/uploads", json={
        "device_id": phone.device_id, "sha256": hashlib.sha256(jpeg).hexdigest(), "bytes": len(jpeg),
        "content_type": "image/jpeg"}, headers=phone._h(True), timeout=10), "upload session", 201)
    put = httpx.put(f"{phone.api}/v1/captures/uploads/{sess['upload_id']}", content=jpeg,
                    headers={**phone._h(), "Content-Type": "image/jpeg"}, timeout=15)
    s._expect(put.status_code == 204, f"upload PUT: HTTP {put.status_code} {put.text[:200]}")
    key = str(uuid.uuid4())
    cap = s._accepted(httpx.post(f"{phone.api}/v1/captures", json={
        "device_id": phone.device_id, "task_id": task_id, "site_id": site, "shutter_timestamp": int(time.time()),
        "blur_applied": True, "bystander_count": 0, "code_type": "look", "code_value": f"look-{key}",
        "object_class": noun, "crop_upload_id": sess["upload_id"]}, headers=phone._h(True), timeout=15),
        "capture (app path)", 201)
    return str(cap["id"])


def smoke_case(phone: Any, state: dict[str, Any], case: str, scene: dict[str, Any], wait: float,
               sup: Any = None) -> None:
    """One case; with ``sup`` (smoke --m5) along the app's paths and on to the claim and the evidence."""
    s = _stack()
    api, site = phone.api, state["home_site"]
    full = sup is not None
    if full and case == "grocery":
        c = start_case_as_the_app(phone, site, case)
        s._expect(c["expected_units"] == scene["n"], f"{case} starter expects {c['expected_units']}, not {scene['n']}")
    else:
        c = create_case(s._operator(state, site), site, case, units=scene["n"])
    boxes = grid(scene["n"], scene["cols"])
    r = httpx.post(standin_url() + "/_standin/scene", json={"boxes": boxes, "width": W, "height": H,
                                                            "labels": scene["labels"]}, timeout=10)
    s._expect(r.status_code == 200, f"model stand-in: HTTP {r.status_code}; start the stack with `up --model-standin`")
    before = httpx.get(standin_url() + "/_standin/requests", timeout=10).json()
    photo = draw(boxes, c["object"])
    if full and case == "pharmacy":
        capture = upload_as_the_app(phone, site, c["task_id"], photo, c["object"])
    else:
        cap = httpx.post(f"{api}/v1/captures", data={"metadata": json.dumps({
            "device_id": phone.device_id, "task_id": c["task_id"], "site_id": site,
            "shutter_timestamp": int(time.time()), "blur_applied": True, "code_type": "photo",
            "code_value": f"look-{uuid.uuid4()}", "readability": 0.9})},
            files={"crop": ("look.jpg", photo, "image/jpeg")}, headers=phone._h(True), timeout=15)
        capture = s._accepted(cap, "capture upload", 201)["id"]
    look = s._accepted(httpx.post(f"{api}/v1/vision/looks", json={
        "task_id": c["task_id"], "line_id": c["line_id"], "capture_id": capture, "case": case},
        headers=phone._h(True), timeout=30), "look")
    after = httpx.get(standin_url() + "/_standin/requests", timeout=10).json()
    s._expect(look["source"] == "model", f"{case} look source {look['source']} {look['reasons']}: is field-api"
                                         " running with `up --model-standin`?")
    s._expect(after["responses"] > before["responses"] and after["chat"] > before["chat"], "the stand-in saw no call")
    s._expect(look["counts"]["seen"] == scene["n"] and look["proposal"]["receive"] == scene["receive"]
              and look["proposal"]["flag"] == scene["flag"], f"{case} proposal {look['proposal']}")
    print(f"m5 {case:8s} delivery {c['ref_doc_no']}: look {look['look_id']} {look['counts']} -> {look['say']!r}")
    good, flag = look["proposal"]["receive"], look["proposal"]["flag"]
    total = float(good + flag)
    said = f"receive {good}, flag {flag}"
    count_turn = phone.voice(c["task_id"], "count", said)
    s._accepted(httpx.post(f"{api}/v1/count-records", json={  # the app's count after a look (stream B)
        "task_line_id": c["line_id"], "value": total, "unit": "EA", "source": "voice", "voice_event_id": count_turn,
        "flag_qty": flag, "look_id": look["look_id"], "capture_id": capture}, headers=phone._h(True), timeout=10),
        "count with flag", 201)
    post_id, conf_id = phone.voice(c["task_id"], "post", "post"), phone.voice(c["task_id"], "confirm", "confirm")
    body = {"operation": "post", "lines": [c["line_id"]], "staged_hash": phone.staged_hash([(c["line_id"], total)]),
            "confirm": {"method": "voice", "post_voice_event_id": post_id, "confirm_voice_event_id": conf_id},
            "look_id": look["look_id"]}  # the app sends the look; the flag was recorded with the count
    out = s._accepted(httpx.post(f"{api}/v1/tasks/{c['task_id']}/post-requests", json=body, headers=phone._h(True),
                                 timeout=15), "post with the look", 202)
    ev = phone.wait_event(("erp.posted",), c["task_id"], wait)
    s._expect(ev["kind"] == "erp.posted", f"{case}: {ev}")
    items = s.erp_document(ev["doc_number"], ev["doc_year"])["to_MaterialDocumentItem"]["results"]
    moves = sorted((i["StorageLocation"], i["GoodsMovementType"], float(i["QuantityInEntryUnit"])) for i in items)
    want = sorted([("101A", "101", float(good))] + ([("101Q", "101", float(flag))] if flag else []))
    s._expect(moves == want, f"erp-sim GR {ev['doc_number']} has {moves}, expected {want}")
    linked = s._accepted(httpx.get(f"{api}/v1/vision/looks/{look['look_id']}", headers=phone._h(), timeout=10),
                         "look read")
    s._expect(linked["erp_document_id"] == out["posting_request_id"], f"look not linked: {linked['erp_document_id']}")
    print(f"         {said}, post, confirm -> GR {ev['doc_number']}/{ev['doc_year']} {moves}, look linked")
    if full:
        claim_and_evidence(phone, sup, case, look, scene, photo, ev)


CLAIM_REASONS = {"grocery": {"damaged", "pack_size"}, "pharmacy": {"damaged", "expired", "near_expiry"}}
FLAG_REASONS = {"damaged", "expired", "near_expiry"}


def claim_and_evidence(phone: Any, sup: Any, case: str, look: dict[str, Any], scene: dict[str, Any], photo: bytes,
                       ev: dict[str, Any]) -> None:
    """Contract section 3 after the posting: claim (operator) -> decision + confirm (supervisor, If-Match) ->
    evidence link (the phone) -> signed page and JSON pack."""
    import hashlib

    s = _stack()
    api = phone.api
    made = httpx.post(f"{api}/v1/claims", json={"look_id": look["look_id"]}, headers=phone._h(True), timeout=20)
    claim = s._accepted(made, f"{case} claim", 201)
    cid = claim["claim_id"]
    reasons = {ln["reason"] for ln in claim["lines"]}
    flagged_units = sum(ln["units"] for ln in claim["lines"] if ln["reason"] in FLAG_REASONS)
    s._expect(claim["status"] == "draft" and reasons == CLAIM_REASONS[case] and flagged_units == scene["flag"],
              f"{case} claim lines {claim['lines']}")
    s._expect(claim["source"] == "model" and not claim["reasons"],  # the stand-in drafts; the number check passes
              f"{case} claim text from {claim['source']}: {claim['reasons']}")
    s._expect(claim.get("etag") == made.headers.get("ETag"), f"claim etag {claim.get('etag')} vs header")
    print(f"         claim {cid} draft ({claim['source']}): {claim['lines']}")
    drafts = sup.get("/v1/claims", status="draft")["items"]
    item = next((x for x in drafts if x["claim_id"] == cid), None)
    s._expect(item is not None and bool(item.get("etag")), f"claim {cid} not in the supervisor's drafts with an etag")
    url = f"{api}/v1/claims/{cid}"
    dec = httpx.post(f"{url}/decision", json={"decision": "approve"},
                     headers={**sup._h(True), "If-Match": str(item["etag"] if item else "")}, timeout=10)
    d = s._accepted(dec, "supervisor decision", 200)
    s._expect(d["status"] == "pending_confirm" and "confirm" in d["say"].lower(), f"decision answer {d}")
    conf = httpx.post(f"{url}/confirm", json={"words": "confirm"},
                      headers={**sup._h(True), "If-Match": dec.headers["ETag"]}, timeout=10)
    done = s._accepted(conf, "supervisor confirm", 200)
    got = sup.get(f"/v1/claims/{cid}")
    s._expect(done["status"] == "approved" and got["status"] == "approved" and got["sent"] is True
              and got["decided_by"] == got["confirmed_by"] == sup.principal and got["created_by"] != sup.principal,
              f"claim after confirm {got['status']} sent={got['sent']} by {got['decided_by']}/{got['confirmed_by']}")
    print(f"         supervisor {sup.principal}: approve -> {d['say']!r} -> confirm -> {done['status']}"
          f" ({done['say']!r})")
    doc, year = str(ev["doc_number"]), str(ev["doc_year"])
    link = s._accepted(httpx.post(f"{api}/v1/evidence/documents/{doc}/link", params={"year": year}, json={},
                                  headers=phone._h(True), timeout=10), "evidence link", 200)
    s._expect(link["url"].endswith(link["path"]) and link["path"].startswith("/evidence/"), f"evidence link {link}")
    page = httpx.get(api + link["path"], timeout=15)
    s._expect(page.status_code == 200 and page.headers.get("content-type", "").startswith("text/html"),
              f"evidence page: HTTP {page.status_code}")
    sha = hashlib.sha256(photo).hexdigest()
    pack = s._accepted(httpx.get(f"{api}/v1/evidence/documents/{doc}", params={"year": year}, headers=phone._h(),
                                 timeout=15), "evidence pack")
    html = page.text
    s._expect("SAMPLE" in html and "<svg" in html and html.count("<rect") >= scene["n"] and sha in html
              and pack["hashes"]["pack_sha256"] in html, "evidence page lacks the SAMPLE banner, the outlines SVG"
                                                          " or the hashes")
    models = {m["model"] for m in pack["models"]}
    s._expect(pack["look"]["look_id"] == look["look_id"] and pack["look"]["counts"] == look["counts"]
              and len(pack["look"]["instances"]) == scene["n"], f"pack look {pack['look'].get('look_id')}")
    s._expect(bool(models) and any("sam" in m for m in models), f"pack model calls {pack['models']}")
    s._expect(pack["confirm"]["method"] == "voice" and pack["confirm"]["words"] == ["post", "confirm"],
              f"pack confirm {pack['confirm']}")
    s._expect(pack["claim"] is not None and pack["claim"]["claim_id"] == cid and pack["claim"]["status"] == "approved"
              and pack["claim"]["sent_simulated"] is True, f"pack claim {pack['claim']}")
    s._expect(pack["hashes"]["photo_sha256"] == sha and pack["hashes"]["photo_sha256_verified"] is True,
              f"pack photo hash {pack['hashes']}")
    s._expect(pack["document"]["number"] == doc and str(pack["document"]["year"]) == year, "pack document")
    print(f"         evidence {link['path'][:24]}...: page 200 (SAMPLE, SVG outlines, hashes), pack: look,"
          f" {len(pack['models'])} model call(s) {sorted(models)}, voice confirm, claim approved;"
          f" photo sha256 {sha[:12]}..., pack sha256 {pack['hashes']['pack_sha256'][:12]}...")


def smoke_m5_look(api: str, state: dict[str, Any], wait: float, full: bool = False) -> int:
    s = _stack()
    state = s.ensure_home(state)
    ensure_case_slocs(state)
    try:
        httpx.get(standin_url() + "/_standin/requests", timeout=5).raise_for_status()
    except httpx.HTTPError:
        print(f"FAIL: no model stand-in at {standin_url()}: start the stack with `up --model-standin`")
        return 1
    phone = s.Phone(api, s._core_token("smoke-m5", state["tenant"], state["home_site"], 1800)).pair(
        f"smoke-{uuid.uuid4().hex[:8]}")
    r = httpx.post(f"{api}/v1/consents", json={"site_id": state["home_site"], "device_id": phone.device_id},
                   headers=phone._h(True), timeout=10)
    if r.status_code != 201:
        print(f"FAIL: consent: HTTP {r.status_code} {r.text[:200]}")
        return 1
    print(f"paired: device {phone.device_id} (home), consent recorded")
    sup = None
    if full:
        sup = s.Console(api, state["tenant"], "smoke-m5-sup")
    done = 0
    try:
        for case, scene in scenes(date.today()).items():
            smoke_case(phone, state, case, scene, wait, sup)
            done += 1
    except s.SmokeFailure as e:
        print(f"FAIL after {done} case(s): {e}")
        return 1
    if full:
        print("PASS: M5 end to end, 2 cases (C1 grocery: starter -> look -> receive 18 flag 2 -> 101A 18 + 101Q 2 ->"
              " claim damaged + pack size -> supervisor approve + confirm -> evidence page and pack; C2 pharmacy:"
              " app upload path -> look -> receive 7 flag 3 -> 101A 7 + 101Q 3 -> claim expired + near expiry +"
              " damaged -> approved -> evidence); models: the dev stack's model stand-in, not Meta")
        return 0
    print("PASS: M5 look, 2 cases (C1 grocery: receive 18 flag 2 -> 101A 18 + 101Q 2; C2 pharmacy: receive 7 flag 3"
          " -> 101A 7 + 101Q 3), each look linked to its GR; models: the dev stack's model stand-in, not Meta")
    return 0
