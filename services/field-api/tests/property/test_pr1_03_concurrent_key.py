"""Property Test PR1.03: Concurrent Same Key Invariants (Hypothesis)."""

import uuid
from concurrent.futures import ThreadPoolExecutor

import hypothesis.strategies as st
import pytest
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth.jwt import create_dev_token
from field_common.uuid7 import uuid7_str
from hypothesis import given, settings

TENANT = str(uuid.uuid4())  # fresh per run: rows persist in Postgres

client = TestClient(app)


def make_headers(idem_key: str) -> dict[str, str]:
    token = create_dev_token(
        principal_id="test-concurrent-user",
        tenant_id=TENANT,
        roles=["field.admin"],
        site_ids=["*"],
    )
    return {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": idem_key,
    }


@pytest.mark.property
@settings(max_examples=25)
@given(
    st.integers(min_value=2, max_value=8),
    st.text(min_size=4, max_size=8, alphabet="0123456789ABCDEF"),
)
def test_pr1_03_concurrent_same_key(concurrency: int, key_suffix: str) -> None:
    """PR1.03: For concurrent requests with the same key and body, responses are only 201 or 409 in-progress or replayed 201."""
    idem_key = f"concurrent-{key_suffix}-{uuid7_str()}"
    headers = make_headers(idem_key)
    payload = {
        "code": f"SITE-CONC-{key_suffix}-{uuid.uuid4().hex[:6].upper()}",  # unique per example
        "name": f"Concurrent Site {key_suffix}",
        "kind": "warehouse",
    }

    def send_request() -> int:
        res = client.post("/v1/sites", json=payload, headers=headers)
        return res.status_code

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        status_codes = list(executor.map(lambda _: send_request(), range(concurrency)))

    # Verification 1: At least one request succeeded (201)
    assert 201 in status_codes, f"Expected at least one 201 Created, got {status_codes}"

    # Verification 2: Every other response is either 201 (replayed) or 409 (FIELD-IDEM-409-IN-PROGRESS)
    for code in status_codes:
        assert code in (201, 409), f"Unexpected status code {code} in concurrent run {status_codes}"
