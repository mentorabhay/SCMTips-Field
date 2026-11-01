"""M5 case C3 on the dev stack (docs/design/M5_C3_CONTRACT.md section 6): the seal-label scenarios and their smoke.

    uv run python -m tools.dev_stack.stack c3            # the five scenarios in the OEM simulator (erp-sim /_oem),
                                                         # var/c3_labels.html to print and tape onto boxes
    uv run python -m tools.dev_stack.stack up --model-standin
    uv run python -m tools.dev_stack.stack smoke --c3    # every scenario through the real field-api and erp-sim

``c3`` seeds through ``field_api.tools.seed_c3`` (the OEM port's seed capability, the simulator's admin API) and is
idempotent: a re-run keeps every printed label valid and resets the first checks, so the cloned label starts over.

``smoke --c3`` needs a field-api started with ``up --model-standin`` for the visual part (the stand-in answers SAM 3.1
with the seal box and the seal check with "tape over the seal"; no real model, no key, no spend). It seeds the
scenarios, pairs two phones (two checkers) on the home sandbox site and checks: L1 genuine new; L2 returned and
resold (the contract's spoken example); L3 counterfeit; L4 the cloned code: the first phone claims it, the second
phone hears "first checked on <today>"; L5 with a photo uploaded through the app's capture path: the first answer
before the seal is read (two steps), then tamper true and "The seal shows tape over the original."; then a claim
from L2 approved by a supervisor (If-Match, confirm within 10 s) and the check's signed evidence page and JSON pack.
"""

from __future__ import annotations

import hashlib
import io
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import httpx

LABELS_OUT = Path("var") / "c3_labels.html"
W, H = 1000, 700
SEAL_BOX = [300, 200, 700, 420]
DELAY_S = 2.0  # the stand-in holds the seal answer this long: the check must answer before it (two steps)


def _stack() -> Any:
    from tools.dev_stack import stack

    return stack


def seed(labels_out: Path | None) -> dict[str, str]:
    from field_api.tools import seed_c3
    from field_oem.sim.adapter import SimOemAdapter

    s = _stack()
    port = SimOemAdapter(s.local("erp-sim") + "/_oem")
    codes = seed_c3.seed(port).codes
    if labels_out is not None:
        path = s.ROOT / labels_out
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(port.labels_html(), encoding="utf-8")
    return codes


def cmd_c3(_a: Any) -> int:
    s = _stack()
    s.load_env()
    s.apply_ports()
    try:
        codes = seed(LABELS_OUT)
    except Exception as e:  # the OEM port's errors and the HTTP layer's: say what failed, exit 1
        print(f"FAIL c3: {type(e).__name__}: {e} (is the stack up? `stack up`)")
        return 1
    for sc, expect in (("L1", "GENUINE_NEW"), ("L2", "RETURNED_REFURBISHED"), ("L3", "LIKELY_COUNTERFEIT"),
                       ("L4", "GENUINE_NEW, then CANNOT_VERIFY for a second checker"),
                       ("L5", "GENUINE_NEW, tamper true with a photo")):
        print(f"{sc}: {expect} ({len(codes[sc])}-character signed code)")
    print(f"labels: {s.ROOT / LABELS_OUT} (print at 100 %, tape onto boxes; also at {s.local('erp-sim')}/_oem/labels)")
    print(f"registry: {s.local('erp-sim')}/_oem/ui")
    return 0


def seal_jpeg() -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), (214, 196, 160))
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = SEAL_BOX
    d.rectangle((x0, y0, x1 - 1, y1 - 1), fill=(31, 58, 95), outline=(10, 10, 10))
    d.rectangle((x0 - 20, y0 + 80, x1 + 20, y0 + 130), fill=(233, 223, 180))  # a strip of tape across it
    d.text((x0 + 12, y0 + 12), "SAMPLE SEAL", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def upload_photo(phone: Any, site: str, jpeg: bytes) -> str:
    """The app's capture path without a task (contract section 7): upload session -> PUT -> POST /v1/captures."""
    s = _stack()
    sess = s._accepted(httpx.post(f"{phone.api}/v1/captures/uploads", json={
        "device_id": phone.device_id, "sha256": hashlib.sha256(jpeg).hexdigest(), "bytes": len(jpeg),
        "content_type": "image/jpeg"}, headers=phone._h(True), timeout=10), "upload session", 201)
    put = httpx.put(f"{phone.api}/v1/captures/uploads/{sess['upload_id']}", content=jpeg,
                    headers={**phone._h(), "Content-Type": "image/jpeg"}, timeout=15)
    s._expect(put.status_code == 204, f"upload PUT: HTTP {put.status_code} {put.text[:200]}")
    cap = s._accepted(httpx.post(f"{phone.api}/v1/captures", json={
        "device_id": phone.device_id, "task_id": None, "site_id": site, "shutter_timestamp": int(time.time()),
        "blur_applied": True, "bystander_count": 0, "code_type": "seal_photo", "code_value": "authenticity",
        "crop_upload_id": sess["upload_id"]}, headers=phone._h(True), timeout=15), "seal photo capture", 201)
    return str(cap["id"])


def check(phone: Any, code: str, **extra: Any) -> dict[str, Any]:
    s = _stack()
    out: dict[str, Any] = s._accepted(httpx.post(f"{phone.api}/v1/authenticity/checks",
                                                 json={"code": code, **extra}, headers=phone._h(True), timeout=30),
                                      "authenticity check")
    return out


def poll(phone: Any, check_id: str) -> dict[str, Any]:
    s = _stack()
    for _ in range(45):  # as the app polls: every 1 s, up to 45 s
        got: dict[str, Any] = s._accepted(httpx.get(f"{phone.api}/v1/authenticity/checks/{check_id}", headers=phone._h(), timeout=10),
                          "check read")
        if got["final"]:
            return got
        time.sleep(1.0)
    raise s.SmokeFailure(f"check {check_id} not final after 45 s")


def _pair(s: Any, api: str, state: dict[str, Any], who: str) -> Any:
    phone = s.Phone(api, s._core_token(who, state["tenant"], state["home_site"], 1800)).pair(
        f"smoke-{uuid.uuid4().hex[:8]}")
    s._accepted(httpx.post(f"{api}/v1/consents", json={"site_id": state["home_site"], "device_id": phone.device_id},
                           headers=phone._h(True), timeout=10), "consent", 201)
    return phone


def run_smoke(api: str, state: dict[str, Any]) -> None:
    from tools.dev_stack.m5 import standin_url

    s = _stack()
    codes = seed(None)
    a, b = _pair(s, api, state, "smoke-c3-a"), _pair(s, api, state, "smoke-c3-b")
    site = state["home_site"]
    print(f"seeded L1-L5; paired two checkers on the home site ({a.device_id}, {b.device_id})")
    l1 = check(a, codes["L1"])
    s._expect(l1["verdict"] == "GENUINE_NEW" and l1["signals"]["first_check"]["status"] == "first", f"L1 {l1}")
    l2 = check(a, codes["L2"])
    s._expect(l2["verdict"] == "RETURNED_REFURBISHED" and l2["say"].startswith(
        "Code is genuine. But this unit was activated on 12 October and returned on 20 October."), f"L2 {l2['say']}")
    l3 = check(a, codes["L3"])
    s._expect(l3["verdict"] == "LIKELY_COUNTERFEIT" and l3["rule"] == "R6", f"L3 {l3['verdict']} {l3['reasons']}")
    l4a, l4b = check(a, codes["L4"]), check(b, codes["L4"])
    today = date.today()
    s._expect(l4a["verdict"] == "GENUINE_NEW" and l4b["verdict"] == "CANNOT_VERIFY" and l4b["rule"] == "R13"
              and f"first checked on {today.day} {today.strftime('%B')}" in l4b["say"], f"L4 {l4b['say']}")
    for name, c in (("L1", l1), ("L2", l2), ("L3", l3), ("L4 copy b", l4b)):
        print(f"  {name}: {c['verdict']} ({c['rule']}) -> {c['say']!r}")
    r = httpx.post(standin_url() + "/_standin/scene", json={
        "boxes": [SEAL_BOX], "width": W, "height": H, "labels": {}, "label_delay_s": DELAY_S,
        "seal": {"seal_visible": True, "signs": ["tape_over_seal"]}}, timeout=10)
    s._expect(r.status_code == 200, f"model stand-in: HTTP {r.status_code}; start the stack with `up --model-standin`")
    photo = seal_jpeg()
    capture = upload_photo(a, site, photo)
    t0 = time.monotonic()
    first = check(a, codes["L5"], capture_id=capture)
    answered = time.monotonic() - t0
    s._expect(first["final"] is False and first["say"].endswith("Checking the seal.") and answered < DELAY_S,
              f"L5 first answer final={first['final']} after {answered:.1f} s: {first['say']!r}")
    l5 = poll(a, first["check_id"])
    s._expect(l5["verdict"] == "GENUINE_NEW" and l5["tamper"] is True
              and l5["say_next"] == "The seal shows tape over the original." and l5["signals"]["visual"]["box"],
              f"L5 final tamper={l5['tamper']} {l5['reasons']} {l5['say']!r}")
    print(f"  L5: first answer in {answered:.1f} s ({first['say']!r}), then tamper true -> {l5['say_next']!r}")
    claim = s._accepted(httpx.post(f"{api}/v1/claims", json={"check_id": l2["check_id"]}, headers=a._h(True),
                                   timeout=20), "authenticity claim", 201)
    s._expect(claim["kind"] == "authenticity" and [ln["reason"] for ln in claim["lines"]] == ["not_new"],
              f"claim {claim}")
    sup = s.Console(api, state["tenant"], "smoke-c3-sup")
    url = f"{api}/v1/claims/{claim['claim_id']}"
    dec = httpx.post(f"{url}/decision", json={"decision": "approve"},
                     headers={**sup._h(True), "If-Match": claim["etag"]}, timeout=10)
    s._accepted(dec, "supervisor decision")
    done = s._accepted(httpx.post(f"{url}/confirm", json={"words": "confirm"},
                                  headers={**sup._h(True), "If-Match": dec.headers["ETag"]}, timeout=10), "confirm")
    s._expect(done["status"] == "approved", f"claim {done}")
    print(f"  claim {claim['claim_id']} ({claim['lines']}) -> supervisor approve + confirm -> {done['status']}")
    link = s._accepted(httpx.post(f"{api}/v1/authenticity/checks/{l5['check_id']}/link", json={},
                                  headers=a._h(True), timeout=10), "evidence link")
    page = httpx.get(api + link["path"], timeout=15)
    pack = s._accepted(httpx.get(f"{api}/v1/authenticity/checks/{l5['check_id']}/evidence", headers=a._h(),
                                 timeout=15), "evidence pack")
    sha = hashlib.sha256(photo).hexdigest()
    s._expect(page.status_code == 200 and "SAMPLE" in page.text and "<svg" in page.text
              and pack["hashes"]["pack_sha256"] in page.text and pack["hashes"]["photo_sha256"] == sha
              and pack["hashes"]["photo_sha256_verified"] is True, "check evidence page or pack")
    print(f"  evidence {link['path'][:28]}...: page 200 (SAMPLE, seal outline SVG), pack sha256"
          f" {pack['hashes']['pack_sha256'][:12]}..., photo sha256 {sha[:12]}...")


def smoke_c3(api: str, state: dict[str, Any]) -> int:
    from tools.dev_stack.m5 import standin_url

    s = _stack()
    state = s.ensure_home(state)
    try:
        httpx.get(standin_url() + "/_standin/requests", timeout=5).raise_for_status()
    except httpx.HTTPError:
        print(f"FAIL: no model stand-in at {standin_url()}: start the stack with `up --model-standin`")
        return 1
    try:
        run_smoke(api, state)
    except s.SmokeFailure as e:
        print(f"FAIL c3: {e}")
        return 1
    print("PASS: C3 authenticity, 5 scenarios (L1 genuine new; L2 returned -> not new; L3 counterfeit; L4 cloned code"
          " caught by the second checker; L5 two-step seal check -> tamper) -> claim approved -> evidence page and"
          " pack; maker: the OEM simulator (SAMPLE); models: the dev stack's model stand-in, not Meta")
    return 0
