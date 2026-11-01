"""Supplier claims API (M5 contract section 3, ledger M5-X01..X03): lines by rules, text by Muse or the template
with the local number check, one claim per look, roles, ETag / If-Match, the 10 s confirm, the simulated send, and
tenant isolation under forced RLS."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any

import psycopg
from fastapi.testclient import TestClient

DAMAGED_AND_PACK = [{"reason": "damaged", "units": 2, "pieces": 24}, {"reason": "pack_size", "units": 2, "pieces": 4}]


def _create(client: TestClient, h: SimpleNamespace, token: str, look_id: str, key: str | None = None) -> Any:
    headers = h.auth(token)
    if key:
        headers["Idempotency-Key"] = key
    return client.post("/v1/claims", json={"look_id": look_id}, headers=headers)


def _etag(client: TestClient, h: SimpleNamespace, token: str, claim_id: str) -> str:
    r = client.get(f"/v1/claims/{claim_id}", headers=h.auth(token))
    assert r.status_code == 200, r.text
    return r.headers["ETag"]


def test_operator_creates_a_claim_with_lines_from_the_look_and_the_template_without_ai(
        client: TestClient, env: dict[str, Any], h: SimpleNamespace, ai_off: None, recorded_api: Any) -> None:
    r = _create(client, h, env["op"], env["look"])
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["status"] == "draft" and c["lines"] == DAMAGED_AND_PACK
    assert c["source"] == "template" and c["reasons"] == ["model:meta:AI_CLOUD_DISABLED"]
    assert c["text"] == ("We claim for this delivery: 2 damaged units (24 pieces); 2 packs hold fewer pieces than 12: "
                         "4 pieces short. The photo and the posting record are attached.")
    assert c["evidence_url"] == "" and c["look_id"] == env["look"] and c["task_id"] == env["task"]
    assert c["site_id"] == env["site"] and r.headers["ETag"].startswith('"1-')
    assert recorded_api.requests == []  # AI off: no call left the server
    assert "BRANDX" not in r.text  # label raw text never reaches a claim


def test_one_claim_per_look_and_idempotent_replay(client: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                                  ai_off: None, looks: Any) -> None:
    key = f"claim-{uuid.uuid4()}"
    first = _create(client, h, env["op"], env["look"], key)
    replay = _create(client, h, env["op"], env["look"], key)
    assert first.status_code == 201 and replay.status_code == 201
    assert replay.headers.get("Idempotent-Replayed") == "true" and replay.json() == first.json()
    calls = looks.calls
    again = _create(client, h, env["sup"], env["look"])  # another person, another key: the same claim, no new draft
    assert again.status_code == 200 and again.json()["claim_id"] == first.json()["claim_id"]
    assert looks.calls == calls  # the existing claim is returned before the look is even read
    n = h.admin_sql(env["tenant"], "SELECT count(*) FROM field.supplier_claim WHERE look_id = %s", (env["look"],))
    assert n[0][0] == 1


def test_muse_draft_is_used_when_every_number_matches(client: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                                      ai_on: None, recorded_api: Any) -> None:
    draft = ("Please note that 2 units arrived damaged, 24 pieces in all, and 2 packs hold fewer pieces than 12, "
             "so 4 pieces are short.")
    recorded_api.script = [h.answer(draft)]
    r = _create(client, h, env["op"], env["look"])
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["source"] == "model" and c["text"] == draft and c["reasons"] == []
    sent = json.dumps(recorded_api.requests)
    assert "BRANDX" not in sent and env["look"] not in sent and env["capture"] not in sent  # template text only
    assert recorded_api.requests[0]["model"] == "muse-spark-1.3"
    rows = h.admin_sql(env["tenant"], "SELECT purpose, status, provider FROM ops.ai_usage WHERE tenant_id = %s",
                       (env["tenant"],))
    assert rows == [("claim", "settled", "meta")]
    stored = h.admin_sql(env["tenant"], "SELECT model_calls FROM field.supplier_claim WHERE id = %s", (c["claim_id"],))
    calls = stored[0][0]
    assert calls[0]["purpose"] == "claim" and calls[0]["outcome"] == "ok" and calls[0]["model"] == "muse-spark-1.3"
    assert h.FAKE_KEY not in r.text and h.FAKE_KEY not in json.dumps(calls)


def test_number_check_refuses_a_changed_number_and_the_template_is_used(
        client: TestClient, env: dict[str, Any], h: SimpleNamespace, ai_on: None, recorded_api: Any) -> None:
    recorded_api.script = [h.answer("2 units arrived damaged (24 pieces) and 2 packs hold fewer pieces than 12: "
                                    "5 pieces short.")]
    c = _create(client, h, env["op"], env["look"]).json()
    assert c["source"] == "template" and c["text"].startswith("We claim for this delivery: 2 damaged units")
    assert c["reasons"] == ["local:number_not_in_template:5", "local:number_dropped:4"]


def test_number_check_refuses_an_added_number(client: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                              ai_on: None, recorded_api: Any) -> None:
    recorded_api.script = [h.answer("2 units arrived damaged (24 pieces) and 2 packs hold fewer pieces than 12: "
                                    "4 pieces short; please credit 150 rupees.")]
    c = _create(client, h, env["op"], env["look"]).json()
    assert c["source"] == "template" and c["reasons"] == ["local:number_not_in_template:150"]


def test_model_failure_falls_back_to_the_template(client: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                                  ai_on: None, recorded_api: Any) -> None:
    recorded_api.script = [500]
    c = _create(client, h, env["op"], env["look"]).json()
    assert c["source"] == "template" and c["reasons"] == ["model:meta:AI_HTTP_500"]


def test_unknown_look_and_nothing_to_claim(client: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                           ai_off: None, looks: Any) -> None:
    r = _create(client, h, env["op"], str(uuid.uuid4()))
    assert r.status_code == 404 and r.json()["code"] == "FIELD-CLM-404-LOOK"
    clean = looks.add(env["tenant"], h.make_look(str(uuid.uuid4()), env["capture"], env["task"], damaged=(),
                                                 mismatches={}))
    r = _create(client, h, env["op"], clean)
    assert r.status_code == 422 and r.json()["code"] == "FIELD-CLM-422-NOTHING-TO-CLAIM"
    rules_only = looks.add(env["tenant"], h.make_look(str(uuid.uuid4()), env["capture"], env["task"], seen=None,
                                                      damaged=(), mismatches={}))
    assert _create(client, h, env["op"], rules_only).status_code == 422  # no count seen: no short line is guessed
    r = client.post("/v1/claims", json={"look_id": "not-a-uuid-not-a-uuid-not-a-uuid-123"}, headers=h.auth(env["op"]))
    assert r.status_code == 422


def test_pharmacy_look_claims_expired_and_near_expiry_boxes(client: TestClient, env: dict[str, Any],
                                                            h: SimpleNamespace, ai_off: None, looks: Any) -> None:
    look = looks.add(env["tenant"], h.make_look(str(uuid.uuid4()), env["capture"], env["task"], expected=12, seen=10,
                                                damaged=(4,), ppu=None, expiry=[(2, "expired"), (4, "near"),
                                                                                (6, "near")]))
    c = _create(client, h, env["op"], look).json()
    assert c["lines"] == [{"reason": "damaged", "units": 1, "pieces": 0}, {"reason": "expired", "units": 1, "pieces": 0},
                          {"reason": "near_expiry", "units": 1, "pieces": 0}, {"reason": "short", "units": 2, "pieces": 0}]
    assert "1 unit expiring within 90 days" in c["text"] and "2 units short" in c["text"]


def test_roles(client: TestClient, env: dict[str, Any], h: SimpleNamespace, ai_off: None) -> None:
    for who in ("viewer", "tech", "integration"):
        assert _create(client, h, env[who], env["look"]).status_code == 403, who
    c = _create(client, h, env["op"], env["look"]).json()
    tag = _etag(client, h, env["op"], c["claim_id"])
    r = client.post(f"/v1/claims/{c['claim_id']}/decision", json={"decision": "approve"},
                    headers=h.auth(env["op"], **{"If-Match": tag}))
    assert r.status_code == 403  # an operator never approves a claim
    assert client.get("/v1/claims", headers=h.auth(env["viewer"])).status_code == 403
    assert client.get("/v1/claims", headers=h.auth(env["op"])).status_code == 200
    assert client.get("/v1/claims").status_code == 401


def test_approve_read_back_confirm_within_10_s_and_simulated_send(
        client: TestClient, env: dict[str, Any], h: SimpleNamespace, ai_off: None) -> None:
    c = _create(client, h, env["op"], env["look"]).json()
    cid = c["claim_id"]
    url = f"/v1/claims/{cid}"
    assert client.post(f"{url}/decision", json={"decision": "approve"}, headers=h.auth(env["sup"])).status_code == 428
    bad = client.post(f"{url}/decision", json={"decision": "approve"}, headers=h.auth(env["sup"], **{"If-Match": '"9-x"'}))
    assert bad.status_code == 412
    tag = _etag(client, h, env["sup"], cid)
    r = client.post(f"{url}/decision", json={"decision": "approve"}, headers=h.auth(env["sup"], **{"If-Match": tag}))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "pending_confirm" and d["confirm_by"]
    assert d["say"] == ("Approve the claim for 2 damaged units (24 pieces); 2 packs hold fewer pieces: "
                        "4 pieces short? Say confirm within 10 seconds.")
    window = h.admin_sql(env["tenant"], "SELECT extract(epoch FROM confirm_by - decided_at) FROM field.supplier_claim"
                                        " WHERE id = %s", (cid,))[0][0]
    assert float(window) == 10.0  # the posting rule (FIELD_CONFIRM_TIMEOUT_S), on the database clock
    new_tag = r.headers["ETag"]
    assert client.post(f"{url}/confirm", headers=h.auth(env["sup"], **{"If-Match": tag})).status_code == 412  # stale
    other = client.post(f"{url}/confirm", headers=h.auth(env["sup2"], **{"If-Match": new_tag}))
    assert other.status_code == 403 and other.json()["code"] == "FIELD-CLM-403-NOT-DECIDER"
    ok = client.post(f"{url}/confirm", json={"words": "confirm"}, headers=h.auth(env["sup"], **{"If-Match": new_tag}))
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"status": "approved",
                         "say": "Claim approved. Sending it to the supplier is simulated in this build."}
    got = client.get(url, headers=h.auth(env["sup"])).json()
    assert got["status"] == "approved" and got["sent"] is True and got["confirmed_by"] == "sup-x"
    assert got["decided_by"] == "sup-x" and got["confirm_words"] == "confirm"
    sent = h.admin_sql(env["tenant"], "SELECT payload FROM field.outbox WHERE event_type = 'claim.sent'"
                                      " AND aggregate_id = %s", (cid,))
    assert len(sent) == 1 and sent[0][0]["simulated"] is True and sent[0][0]["channel"] == "none"
    assert sent[0][0]["data"]["lines"] == DAMAGED_AND_PACK
    listed = client.get("/v1/claims", params={"status": "approved"}, headers=h.auth(env["sup"])).json()
    assert [x["claim_id"] for x in listed["items"]] == [cid]
    assert client.get("/v1/claims", params={"status": "draft"}, headers=h.auth(env["sup"])).json()["items"] == []
    again = client.post(f"{url}/decision", json={"decision": "reject"},
                        headers=h.auth(env["sup"], **{"If-Match": client.get(url, headers=h.auth(env["sup"])).headers["ETag"]}))
    assert again.status_code == 409  # approved is final


def test_confirm_after_10_s_is_refused_and_the_claim_is_a_draft_again(
        client: TestClient, env: dict[str, Any], h: SimpleNamespace, ai_off: None) -> None:
    cid = _create(client, h, env["op"], env["look"]).json()["claim_id"]
    url = f"/v1/claims/{cid}"
    r = client.post(f"{url}/decision", json={"decision": "approve"},
                    headers=h.auth(env["sup"], **{"If-Match": _etag(client, h, env["sup"], cid)}))
    assert r.status_code == 200
    listed = client.get("/v1/claims", params={"status": "pending"}, headers=h.auth(env["sup"])).json()
    assert [x["claim_id"] for x in listed["items"]] == [cid]
    # 11 s later, on the server's clock (the decision is moved back instead of the test sleeping)
    h.admin_sql(env["tenant"], "UPDATE field.supplier_claim SET decided_at = decided_at - interval '11 seconds',"
                               " confirm_by = confirm_by - interval '11 seconds' WHERE id = %s", (cid,))
    late = client.post(f"{url}/confirm", headers=h.auth(env["sup"], **{"If-Match": r.headers["ETag"]}))
    assert late.status_code == 422 and late.json()["code"] == "FIELD-CLM-422-CONFIRM-EXPIRED"
    got = client.get(url, headers=h.auth(env["sup"])).json()
    assert got["status"] == "draft" and got["decision"] is None and got["confirm_by"] is None
    assert h.admin_sql(env["tenant"], "SELECT count(*) FROM field.outbox WHERE aggregate_id = %s", (cid,))[0][0] == 0


def test_reject_with_reason_sends_nothing(client: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                          ai_off: None) -> None:
    cid = _create(client, h, env["op"], env["look"]).json()["claim_id"]
    url = f"/v1/claims/{cid}"
    assert client.post(f"{url}/confirm", headers=h.auth(env["sup"], **{"If-Match": _etag(client, h, env["sup"], cid)})
                       ).status_code == 409  # nothing to confirm on a draft
    r = client.post(f"{url}/decision", json={"decision": "reject", "reason": "the photo is too dark"},
                    headers=h.auth(env["sup"], **{"If-Match": _etag(client, h, env["sup"], cid)}))
    assert r.json()["say"].startswith("Reject the claim for 2 damaged units") and "reason the photo is too dark" in r.json()["say"]
    ok = client.post(f"{url}/confirm", headers=h.auth(env["sup"], **{"If-Match": r.headers["ETag"]}))
    assert ok.json() == {"status": "rejected", "say": "Claim rejected. Nothing is sent to the supplier."}
    assert h.admin_sql(env["tenant"], "SELECT count(*) FROM field.outbox WHERE aggregate_id = %s", (cid,))[0][0] == 0


def test_rls_isolates_tenants_and_sites(client: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                        ai_off: None) -> None:
    cid = _create(client, h, env["op"], env["look"]).json()["claim_id"]
    assert client.get(f"/v1/claims/{cid}", headers=h.auth(env["other_sup"])).status_code == 404
    assert client.get("/v1/claims", headers=h.auth(env["other_sup"])).json()["items"] == []
    assert client.get(f"/v1/claims/{cid}", headers=h.auth(env["op_elsewhere"])).status_code == 404
    # the other tenant cannot even create a claim from this tenant's look (its look port sees no such look)
    assert _create(client, h, env["other_sup"], env["look"]).status_code == 404
    forced = h.admin_sql(env["tenant"], "SELECT relrowsecurity, relforcerowsecurity FROM pg_class"
                                        " WHERE oid = 'field.supplier_claim'::regclass")
    assert forced == [(True, True)]
    import os
    with psycopg.connect(os.environ["FIELD_DATABASE_URL"]) as conn, conn.cursor() as cur:  # the app role, NOBYPASSRLS
        cur.execute("SELECT set_config('app.tenant_id', %s, true), set_config('app.site_ids', '*', true)",
                    (env["other"]["tenant"],))
        cur.execute("SELECT count(*) FROM field.supplier_claim WHERE id = %s", (cid,))
        assert (cur.fetchone() or [None])[0] == 0
        cur.execute("SELECT set_config('app.tenant_id', '', true)")
        cur.execute("SELECT count(*) FROM field.supplier_claim")
        assert (cur.fetchone() or [None])[0] == 0


def test_an_unconfirmed_decision_is_void_when_read_after_10_s(client: TestClient, env: dict[str, Any],
                                                              h: SimpleNamespace, ai_off: None) -> None:
    cid = _create(client, h, env["op"], env["look"]).json()["claim_id"]
    r = client.post(f"/v1/claims/{cid}/decision", json={"decision": "reject"},
                    headers=h.auth(env["sup"], **{"If-Match": _etag(client, h, env["sup"], cid)}))
    assert client.get(f"/v1/claims/{cid}", headers=h.auth(env["sup"])).json()["status"] == "pending_confirm"
    h.admin_sql(env["tenant"], "UPDATE field.supplier_claim SET decided_at = decided_at - interval '11 seconds',"
                               " confirm_by = confirm_by - interval '11 seconds' WHERE id = %s", (cid,))
    got = client.get(f"/v1/claims/{cid}", headers=h.auth(env["sup"]))
    assert got.json()["status"] == "draft" and got.headers["ETag"] != r.headers["ETag"]
    assert client.post(f"/v1/claims/{cid}/confirm", headers=h.auth(env["sup"], **{"If-Match": r.headers["ETag"]})
                       ).status_code == 412  # the old decision's ETag is stale


def test_list_items_carry_the_etag_the_decision_accepts(client: TestClient, env: dict[str, Any], h: SimpleNamespace,
                                                         ai_off: None) -> None:
    """The phone (stream B) takes If-Match from the draft list item's ``etag`` (additive, integrator 2026-11-01)."""
    created = _create(client, h, env["op"], env["look"])
    cid = created.json()["claim_id"]
    assert created.json()["etag"] == created.headers["ETag"]
    drafts = client.get("/v1/claims", params={"status": "draft"}, headers=h.auth(env["sup"])).json()["items"]
    item = next(x for x in drafts if x["claim_id"] == cid)
    assert item["etag"] == _etag(client, h, env["sup"], cid)
    r = client.post(f"/v1/claims/{cid}/decision", json={"decision": "approve"},
                    headers=h.auth(env["sup"], **{"If-Match": item["etag"]}))
    assert r.status_code == 200, r.text
    pending = client.get(f"/v1/claims/{cid}", headers=h.auth(env["sup"]))
    assert pending.json()["etag"] == r.headers["ETag"] == pending.headers["ETag"] != item["etag"]
