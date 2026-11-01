"""Evidence pack, signed page and authenticity claims of a C3 check (M5-T04): M5_C3_CONTRACT.md sections 4.3, 4.4."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from field_api.auth.jwt import Principal
from field_api.authenticity.service import CheckIn, create_check
from field_api.evidence import signing
from field_api.evidence.pack import pack_sha256


def _done(client: TestClient, h: SimpleNamespace, token: str, check_id: str) -> dict[str, Any]:
    r = client.get(f"/v1/authenticity/checks/{check_id}", headers=h.auth(token))
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_m5_t04_evidence_pack_hashes_and_the_signed_page(client: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                                         seal: Any, ai_on: None) -> None:
    seal.seal = {"seal_visible": True, "signs": ["tape_over_seal"]}
    cid = h.check(client, env["op"], env["returned"], capture_id=env["capture"]).json()["check_id"]
    r = client.get(f"/v1/authenticity/checks/{cid}/evidence", headers=h.auth(env["viewer"]))
    assert r.status_code == 200, r.text
    pack = r.json()
    assert pack["kind"] == "scmtips-field.authenticity-evidence" and pack["sample"] is True
    assert pack["rule"] == "R11" and pack["code"] == env["returned"] and pack["check"]["tamper"] is True
    assert pack["hashes"]["photo_sha256_verified"] is True and pack["hashes"]["photo"] == "stored"
    assert pack["hashes"]["pack_sha256"] == pack_sha256(pack) and r.headers["ETag"] == f'"{pack_sha256(pack)}"'
    link = client.post(f"/v1/authenticity/checks/{cid}/link", headers=h.auth(env["op"])).json()
    assert link["path"].startswith("/evidence/check/") and link["url"].endswith(link["path"])
    page = client.get(link["path"])
    assert page.status_code == 200 and "RETURNED_REFURBISHED" in page.text and "SAMPLE" in page.text
    assert "seal flagged as tampered" in page.text and "data:image/jpeg;base64," in page.text
    assert "<script" not in page.text and page.headers["Cache-Control"] == "private, no-store"
    assert link["path"].split("/")[-1] not in page.text
    token = link["path"].split("/")[-1]
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert client.get(f"/evidence/check/{tampered}").status_code == 401
    doc_token, _ = signing.sign(env["tenant"], "5000000001", "2026")
    assert client.get(f"/evidence/check/{doc_token}").status_code == 401  # a document link never opens a check page
    check_token, _ = signing.sign_check(env["tenant"], cid)
    assert client.get(f"/evidence/{check_token}").status_code == 401  # and the reverse
    expired, _ = signing.sign_check(env["tenant"], cid, ttl_s=-5)
    assert client.get(f"/evidence/check/{expired}").status_code == 401
    assert client.get(f"/v1/authenticity/checks/{cid}/evidence", headers=h.auth(env["other_op"])).status_code == 404


def test_m5_t04_claim_from_a_check_lines_one_per_check_and_voice_approval(
        client: TestClient, env: dict[str, Any], h: SimpleNamespace, seal: Any, ai_on: None) -> None:
    seal.seal = {"seal_visible": True, "signs": ["tape_over_seal"]}
    cid = h.check(client, env["op"], env["returned"], capture_id=env["capture"]).json()["check_id"]
    r = client.post("/v1/claims", json={"check_id": cid}, headers=h.auth(env["op"]))
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["kind"] == "authenticity" and c["check_id"] == cid and c["look_id"] is None
    assert c["lines"] == [{"reason": "not_new", "units": 1, "pieces": 0},
                          {"reason": "tampered_seal", "units": 1, "pieces": 0}]
    assert c["source"] == "template" and c["text"] == (
        "We claim for this unit: 1 unit sold as new but not a new unit by the maker's records; 1 unit with a "
        "tampered seal. The authenticity check record is attached.")
    assert c["evidence_url"] == f"/v1/authenticity/checks/{cid}/evidence" and c["status"] == "draft"
    again = client.post("/v1/claims", json={"check_id": cid}, headers=h.auth(env["op"]))
    assert again.status_code == 200 and again.json()["claim_id"] == c["claim_id"]
    assert _done(client, h, env["op"], cid)["claim_id"] == c["claim_id"]
    etag = client.get(f"/v1/claims/{c['claim_id']}", headers=h.auth(env["sup"])).headers["ETag"]
    d = client.post(f"/v1/claims/{c['claim_id']}/decision", json={"decision": "approve"},
                    headers={**h.auth(env["sup"]), "If-Match": etag})
    assert d.status_code == 200 and d.json()["say"].startswith("Approve the claim for 1 unit sold as new")
    etag = d.headers["ETag"]
    ok = client.post(f"/v1/claims/{c['claim_id']}/confirm", json={"words": "confirm"},
                     headers={**h.auth(env["sup"]), "If-Match": etag})
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    listed = client.get("/v1/claims?status=approved", headers=h.auth(env["sup"])).json()["items"]
    assert any(i["claim_id"] == c["claim_id"] and i["kind"] == "authenticity" for i in listed)
    pack = client.get(f"/v1/authenticity/checks/{cid}/evidence", headers=h.auth(env["op"])).json()
    assert pack["claim"]["status"] == "approved" and pack["claim"]["sent"] is True
    sent = h.admin_sql(env["tenant"], "SELECT payload->'data'->>'kind', payload->'data'->>'check_id' FROM field.outbox"
                                      " WHERE event_type = 'claim.sent' AND aggregate_id = %s", (c["claim_id"],))
    assert sent == [("authenticity", cid)]


def test_m5_t04_claim_refusals(client: TestClient, env: dict[str, Any], h: SimpleNamespace, oem: Any,
                               ai_off: None) -> None:
    new = h.check(client, env["op"], env["new"]).json()["check_id"]
    r = client.post("/v1/claims", json={"check_id": new}, headers=h.auth(env["op"]))
    assert r.status_code == 422 and r.json()["code"] == "FIELD-CLM-422-NOTHING-TO-CLAIM"
    for body in ({}, {"check_id": new, "look_id": str(uuid.uuid4())}):
        assert client.post("/v1/claims", json=body, headers=h.auth(env["op"])).status_code == 422
    r = client.post("/v1/claims", json={"check_id": str(uuid.uuid4())}, headers=h.auth(env["op"]))
    assert r.status_code == 404 and r.json()["code"] == "FIELD-AUT-404-CHECK"
    forged = h.check(client, env["op"], env["forged"]).json()["check_id"]
    f = client.post("/v1/claims", json={"check_id": forged}, headers=h.auth(env["op"])).json()
    assert f["lines"] == [{"reason": "counterfeit", "units": 1, "pieces": 0}]
    h.check(client, env["op"], env["activated"])
    copied = h.check(client, env["op2"], env["new"]).json()
    assert copied["rule"] == "R13"
    cc = client.post("/v1/claims", json={"check_id": copied["check_id"]}, headers=h.auth(env["op2"])).json()
    assert cc["lines"] == [{"reason": "copied_code", "units": 1, "pieces": 0}]
    assert client.post("/v1/claims", json={"check_id": new}, headers=h.auth(env["viewer"])).status_code == 403


def test_m5_t04_claim_on_a_pending_check_is_refused(client: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                                   oem: Any, seal: Any, ai_on: None) -> None:
    p = Principal(id="op-c3", tenant_id=env["tenant"], roles=["field.operator"], permissions=[],
                  site_ids=[env["site"]])
    out = create_check(p, CheckIn(code=env["returned"], capture_id=env["capture"]), str(uuid.uuid4()), oem,
                       seal.ports(), defer=lambda _task: None)
    r = client.post("/v1/claims", json={"check_id": out["check_id"]}, headers=h.auth(env["op"]))
    assert r.status_code == 409 and r.json()["code"] == "FIELD-CLM-409-CHECK-PENDING"
