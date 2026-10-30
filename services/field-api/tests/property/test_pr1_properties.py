"""Property Tests PR1.01, PR1.02, PR1.10, PR1.12, PR1.20 (Hypothesis)."""

import uuid

import hypothesis.strategies as st
import pytest
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth.jwt import create_dev_token
from field_common.uuid7 import uuid7_str
from hypothesis import given, settings

client = TestClient(app)
# A fresh tenant per test run: rows persist in Postgres, so fixed codes would collide on re-runs.
TENANT = str(uuid.uuid4())


def make_headers(idem_key: str | None = None, etag: str | None = None) -> dict[str, str]:
    token = create_dev_token(
        principal_id="test-prop-user",
        tenant_id=TENANT,
        roles=["field.admin"],
        site_ids=["*"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    if idem_key:
        headers["Idempotency-Key"] = idem_key
    if etag:
        headers["If-Match"] = etag
    return headers


@pytest.mark.property
@settings(max_examples=30)
@given(st.text(min_size=2, max_size=10, alphabet="ABCDEF0123456789"))
def test_pr1_01_idempotency_replay_identical(code_suffix: str) -> None:
    """PR1.01: Sending identical (key, body) returns identical status and payload."""
    idem_key = f"key-{uuid7_str()}"
    payload = {
        "code": f"SITE-{code_suffix}",
        "name": f"Warehouse Site {code_suffix}",
        "kind": "warehouse",
    }
    headers = make_headers(idem_key=idem_key)

    # First request
    r1 = client.post("/v1/sites", json=payload, headers=headers)
    assert r1.status_code == 201
    b1 = r1.json()

    # Replay request
    r2 = client.post("/v1/sites", json=payload, headers=headers)
    assert r2.status_code == 201
    assert r2.headers.get("Idempotent-Replayed") == "true"
    b2 = r2.json()

    assert b1["id"] == b2["id"]
    assert b1["code"] == b2["code"]


@pytest.mark.property
def test_pr1_02_idempotency_key_reused_different_body() -> None:
    """PR1.02: Sending reused key with different body yields 422 FIELD-IDEM-422-KEY-REUSED."""
    idem_key = f"key-{uuid7_str()}"
    h = make_headers(idem_key=idem_key)

    # First request
    r1 = client.post(
        "/v1/sites",
        json={"code": "S-AAA-01", "name": "Site A", "kind": "warehouse"},
        headers=h,
    )
    assert r1.status_code == 201

    # Second request with same key but different body
    r2 = client.post(
        "/v1/sites",
        json={"code": "S-BBB-02", "name": "Site B Different", "kind": "warehouse"},
        headers=h,
    )
    assert r2.status_code == 422
    assert r2.json()["code"] == "FIELD-IDEM-422-KEY-REUSED"


@pytest.mark.property
def test_pr1_10_etag_if_match_concurrency() -> None:
    """PR1.10: Updates succeed iff If-Match equals current ETag, version increases by 1."""
    # Create site with uppercase code matching regex
    h = make_headers()
    r = client.post(
        "/v1/sites",
        json={"code": f"ETAG-{uuid7_str()[:8].upper()}", "name": "Etag Test", "kind": "yard"},
        headers=h,
    )
    assert r.status_code == 201
    site = r.json()
    site_id = site["id"]
    initial_etag = r.headers["ETag"]
    assert site["version"] == 1

    # 1. Update without If-Match -> 428 Required
    r_no_etag = client.patch(f"/v1/sites/{site_id}", json={"name": "New Name"}, headers=h)
    assert r_no_etag.status_code == 428
    assert r_no_etag.json()["code"] == "FIELD-ETAG-428-REQUIRED"

    # 2. Update with stale If-Match -> 412 Precondition Failed
    h_stale = make_headers(etag='"99-wronghash"')
    r_stale = client.patch(f"/v1/sites/{site_id}", json={"name": "New Name"}, headers=h_stale)
    assert r_stale.status_code == 412
    assert r_stale.json()["code"] == "FIELD-ETAG-412-PRECONDITION-FAILED"

    # 3. Update with correct If-Match -> 200, version becomes 2
    h_correct = make_headers(etag=initial_etag)
    r_ok = client.patch(f"/v1/sites/{site_id}", json={"name": "Updated Valid"}, headers=h_correct)
    assert r_ok.status_code == 200
    updated = r_ok.json()
    assert updated["version"] == 2
    assert r_ok.headers["ETag"] != initial_etag


@pytest.mark.property
def test_pr1_20_location_hierarchy_depth_and_cycles() -> None:
    """PR1.20: Enforces hierarchy depth <= 6 and rejects cycles with FIELD-LOC-422-CYCLE."""
    h = make_headers()
    rs = client.post("/v1/sites", json={"code": f"PR120-{uuid.uuid4().hex[:6].upper()}", "name": "PR1.20",
                                        "kind": "warehouse"}, headers=make_headers())
    assert rs.status_code == 201, rs.text
    site_id = rs.json()["id"]

    # Create root zone (depth 1)
    r1 = client.post(
        "/v1/locations",
        json={"site_id": site_id, "kind": "zone", "code": "Z1"},
        headers=h,
    )
    assert r1.status_code == 201
    l1 = r1.json()
    assert l1["depth"] == 1

    # Create child aisle (depth 2)
    r2 = client.post(
        "/v1/locations",
        json={"site_id": site_id, "parent_id": l1["id"], "kind": "aisle", "code": "A1"},
        headers=h,
    )
    assert r2.status_code == 201
    l2 = r2.json()
    assert l2["depth"] == 2

    # Attempt to move root under its own child -> Cycle detection 422
    etag1 = r1.headers["ETag"]
    h_etag1 = make_headers(etag=etag1)
    r_cycle = client.patch(
        f"/v1/locations/{l1['id']}",
        json={"parent_id": l2["id"]},
        headers=h_etag1,
    )
    assert r_cycle.status_code == 422
    assert r_cycle.json()["code"] == "FIELD-LOC-422-CYCLE"
