"""Evidence pack and page (M5 contract section 3, ledger M5-X04..X05): the JSON pack assembled from what Field
records, its hashes (photo sha256 from the crop store, the pack's own sha256 over canonical JSON), the signed link
(HMAC bound to tenant, document and expiry; tamper and expiry refused) and the self-contained HTML page."""

from __future__ import annotations

import hashlib
import os
import re
import time
import uuid
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from field_api.evidence import signing
from field_api.evidence.pack import canonical_json, pack_sha256
from field_api.evidence.page import render


def _pack(client: TestClient, h: SimpleNamespace, token: str, doc: dict[str, Any]) -> Any:
    return client.get(f"/v1/evidence/documents/{doc['doc_number']}", params={"year": doc["year"]},
                      headers=h.auth(token))


def _claim(client: TestClient, h: SimpleNamespace, env: dict[str, Any]) -> dict[str, Any]:
    r = client.post("/v1/claims", json={"look_id": env["look"]}, headers=h.auth(env["op"]))
    assert r.status_code == 201, r.text
    out: dict[str, Any] = r.json()
    return out


def test_pack_holds_document_look_models_check_confirm_claim_and_hashes(
        client: TestClient, env: dict[str, Any], h: SimpleNamespace, ai_off: None) -> None:
    doc = h.post_document(env)
    claim = _claim(client, h, env)
    assert claim["evidence_url"] == f"/v1/evidence/documents/{doc['doc_number']}?year={doc['year']}"
    r = _pack(client, h, env["op"], doc)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["sample"] is True and p["site_mode"] == "sandbox"
    d = p["document"]
    assert (d["number"], d["year"], d["type"], d["movement_type"]) == (doc["doc_number"], "2026", "GR", "101")
    assert [m["family"] for m in d["movements"]] == ["InboundDeliveryItem", "GoodsReceipt"]
    assert d["events"][0]["type"] == "erp.posted" and d["events"][0]["movement_types"] == ["101"]
    assert d["posted_lines"][0]["material"] == "SBX-000123" and d["posted_lines"][0]["counted_qty"] == "20"
    look = p["look"]
    assert look["look_id"] == env["look"] and look["capture_id"] == env["capture"] and len(look["instances"]) == 20
    assert "raw" not in look["instances"][0]["label"] and "BRANDX" not in r.text  # no label raw text (section 6)
    assert [m["purpose"] for m in p["models"]] == ["instances", "claim"]
    assert p["models"][1]["outcome"].startswith("meta:AI_CLOUD_DISABLED")
    assert p["check"]["claim_lines"] == claim["lines"]
    assert p["check"]["flagged"] == [{"n": 3, "reason": "damaged"}, {"n": 9, "reason": "damaged"}]
    assert p["check"]["short_packs"] == [{"n": 7, "pieces_short": 2}, {"n": 11, "pieces_short": 2}]
    c = p["confirm"]
    assert c["method"] == "voice" and c["by"] == "op-x" and c["words"] == ["post", "confirm"]
    assert p["claim"]["claim_id"] == claim["claim_id"] and p["claim"]["status"] == "draft"
    hs = p["hashes"]
    assert hs["photo_sha256"] == hashlib.sha256(h.PHOTO).hexdigest() and hs["photo_sha256_verified"] is True
    assert hs["pack_sha256"] == pack_sha256(p) and r.headers["ETag"] == f'"{hs["pack_sha256"]}"'


def test_pack_hash_is_stable_and_follows_the_content(client: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                                     ai_off: None) -> None:
    doc = h.post_document(env)
    claim = _claim(client, h, env)
    first = _pack(client, h, env["op"], doc).json()["hashes"]["pack_sha256"]
    time.sleep(1.1)
    assert _pack(client, h, env["sup"], doc).json()["hashes"]["pack_sha256"] == first  # same records, same hash
    tag = client.get(f"/v1/claims/{claim['claim_id']}", headers=h.auth(env["sup"])).headers["ETag"]
    r = client.post(f"/v1/claims/{claim['claim_id']}/decision", json={"decision": "approve"},
                    headers=h.auth(env["sup"], **{"If-Match": tag}))
    client.post(f"/v1/claims/{claim['claim_id']}/confirm", headers=h.auth(env["sup"], **{"If-Match": r.headers["ETag"]}))
    after = _pack(client, h, env["op"], doc).json()
    assert after["claim"]["status"] == "approved" and after["claim"]["sent_simulated"] is True
    assert after["hashes"]["pack_sha256"] != first


def test_canonical_json_ignores_key_order() -> None:
    a = {"b": [1, {"y": 2, "x": "é"}], "a": None, "hashes": {"photo_sha256": "ab", "pack_sha256": "zz"}}
    b = {"hashes": {"pack_sha256": "other", "photo_sha256": "ab"}, "a": None, "b": [1, {"x": "é", "y": 2}]}
    assert canonical_json({k: v for k, v in a.items() if k != "hashes"}) == canonical_json(
        {k: v for k, v in b.items() if k != "hashes"})
    assert pack_sha256(a) == pack_sha256(b)  # the pack hash never covers itself


def test_pack_roles_tenants_and_unknown_documents(client: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                                  ai_off: None) -> None:
    doc = h.post_document(env)
    for who in ("op", "tech", "sup", "viewer"):
        assert _pack(client, h, env[who], doc).status_code == 200, who
    assert _pack(client, h, env["integration"], doc).status_code == 403
    assert _pack(client, h, env["other_sup"], doc).status_code == 404
    assert client.get(f"/v1/evidence/documents/{doc['doc_number']}").status_code == 401
    assert client.get("/v1/evidence/documents/4999999999", headers=h.auth(env["op"])).status_code == 404
    assert client.get("/v1/evidence/documents/bad%20doc", headers=h.auth(env["op"])).status_code == 422
    h.post_document(env, doc_number=doc["doc_number"], year="2027")
    r = client.get(f"/v1/evidence/documents/{doc['doc_number']}", headers=h.auth(env["op"]))
    assert r.status_code == 409 and r.json()["code"] == "FIELD-EVD-409-YEAR"


def test_pack_without_a_look_still_shows_the_document(client: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                                      ai_off: None) -> None:
    doc = h.post_document(env, with_look=False)
    p = _pack(client, h, env["op"], doc).json()
    assert p["look"] is None and p["check"] is None and p["claim"] is None
    assert p["hashes"]["photo"] == "none" and p["hashes"]["photo_sha256"] is None
    assert p["confirm"]["words"] == ["post", "confirm"]


def test_signed_link_opens_a_self_contained_page(client: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                                 ai_off: None) -> None:
    doc = h.post_document(env)
    _claim(client, h, env)
    r = client.post(f"/v1/evidence/documents/{doc['doc_number']}/link", params={"year": doc["year"]},
                    headers=h.auth(env["op"]))
    assert r.status_code == 200, r.text
    link = r.json()
    assert link["url"].endswith(link["path"]) and link["path"].startswith("/evidence/")
    page = client.get(link["path"])  # no Authorization: the token is the credential
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    html = page.text
    assert "SAMPLE" in html and 'role="note"' in html and '<html lang="en">' in html and "<main>" in html
    assert "data:image/jpeg;base64," in html and "<svg viewBox=\"0 0 1920 1440\"" in html
    assert html.count("<rect") >= 40 and "#b3261e" in html and "#1b7a3a" in html  # outlines + number tags
    assert "Model calls" in html and "sam-3.1" in html and "The confirm" in html and "post / confirm" in html
    assert doc["doc_number"] in html and hashlib.sha256(h.PHOTO).hexdigest() in html
    assert re.search(r"(src|href)=\"(https?:)?//", html) is None and "<script" not in html and "<link" not in html
    secret = os.environ["FIELD_EVIDENCE_SECRET"]
    token = link["path"].removeprefix("/evidence/")
    for leak in (secret, token, h.FAKE_KEY, os.environ.get("FIELD_JWT_SECRET", "x" * 40), "BRANDX"):
        assert leak not in html
    csp = page.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "img-src data:" in csp and page.headers["cache-control"] == "private, no-store"


def test_link_tamper_expiry_and_other_tenant(client: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                             ai_off: None) -> None:
    doc = h.post_document(env)
    token, _exp = signing.sign(env["tenant"], doc["doc_number"], doc["year"])
    assert client.get(f"/evidence/{token}").status_code == 200
    payload, sig = token.split(".")
    flipped = payload[:-2] + ("A" if payload[-2] != "A" else "B") + payload[-1]
    for bad in (f"{flipped}.{sig}", f"{payload}.{'0' * 64}", f"{payload}.{sig[:-1]}", payload, "x.y.z", ""):
        r = client.get(f"/evidence/{bad}")
        assert r.status_code in (401, 404), bad
        if bad:
            assert r.status_code == 401 and r.json()["code"] == "FIELD-EVD-401-INVALID-TOKEN"
    old, _ = signing.sign(env["tenant"], doc["doc_number"], doc["year"], ttl_s=60, now=time.time() - 120)
    assert client.get(f"/evidence/{old}").status_code == 401
    # a valid link of another tenant never shows this tenant's document
    other, _ = signing.sign(env["other"]["tenant"], doc["doc_number"], doc["year"])
    assert client.get(f"/evidence/{other}").status_code == 404
    # the other tenant cannot get a link to it either
    r = client.post(f"/v1/evidence/documents/{doc['doc_number']}/link", headers=h.auth(env["other_sup"]))
    assert r.status_code == 404


def test_signing_round_trip_and_key(monkeypatch: Any) -> None:
    t = str(uuid.uuid4())
    token, exp = signing.sign(t, "5000000123", "2026", ttl_s=300, now=1_000_000.0)
    link = signing.verify(token, now=1_000_100.0)
    assert (link.tenant_id, link.doc_number, link.fiscal_year, link.expires_at) == (t, "5000000123", "2026", exp)
    assert exp == 1_000_300
    try:
        signing.verify(token, now=1_000_301.0)
        raise AssertionError("expired token accepted")
    except signing.BadToken as e:
        assert e.reason == "expired"
    monkeypatch.setenv("FIELD_EVIDENCE_SECRET", "z" * 40)  # another key: the old signature no longer verifies
    try:
        signing.verify(token, now=1_000_100.0)
        raise AssertionError("token accepted under another key")
    except signing.BadToken as e:
        assert e.reason == "signature"


def test_page_escapes_every_value() -> None:
    pack = {"site_mode": "sandbox", "erp": "erp-sim", "document": {"number": "5000000001", "year": "2026",
            "posted_lines": [{"line_no": 10, "description": "<script>alert(1)</script>"}]},
            "claim": {"status": "draft", "text": "\"><img src=x onerror=alert(1)>", "lines": []},
            "look": {"look_id": "l", "image": {"width": 100, "height": 50}, "source": "model",
                     "instances": [{"n": 1, "box": [1, 2, 30, 40], "damaged": True, "damage_note": "<b>torn</b>"}]},
            "check": {"flagged": [{"n": 1, "reason": "damaged"}], "claim_lines": []}, "hashes": {"pack_sha256": "ab"}}
    html = render(pack, b"\xff\xd8\xff\xd9")
    assert "<script>alert" not in html and "<img src=x" not in html and "<b>torn" not in html
    assert "&lt;script&gt;" in html and 'stroke="#b3261e"' in html
