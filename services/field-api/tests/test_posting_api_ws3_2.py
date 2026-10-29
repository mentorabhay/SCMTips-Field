"""API Tests for Posting Queues Management (Task T3.013 / FR3.045 / BR3.14)."""

import uuid
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth.jwt import create_dev_token
from field_worker.posting import DATABASE_URL, enqueue_posting_job

client = TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, Any]:
    tenant_id = str(uuid.uuid4())
    token = create_dev_token(
        principal_id="test-supervisor-01",
        tenant_id=tenant_id,
        roles=["field.supervisor", "field.integration", "field.admin"],
        site_ids=["*"],
    )
    return {
        "Authorization": f"Bearer {token}",
        "X-Request-Id": "test-req-00123456",
        "tenant_id": tenant_id,
    }


@pytest.mark.unit
def test_t3_013_list_posting_queues(auth_headers):
    """T3.013 / FR3.045: GET /v1/posting-queues returns aggregated status."""
    t_id = auth_headers["tenant_id"]
    headers = {"Authorization": auth_headers["Authorization"]}
    q1 = f"IBD:Q1_{uuid.uuid4().hex[:6]}"
    q2 = f"OBD:Q2_{uuid.uuid4().hex[:6]}"

    enqueue_posting_job(
        tenant_id=t_id,
        queue_key=q1,
        doc_family="GoodsReceipt",
        site_id="WH1",
        plant="1010",
        header_data={},
        items=[],
        seq=1,
    )
    enqueue_posting_job(
        tenant_id=t_id,
        queue_key=q2,
        doc_family="GoodsIssue",
        site_id="WH1",
        plant="1010",
        header_data={},
        items=[],
        seq=1,
    )

    res = client.get("/v1/posting-queues", headers=headers)
    assert res.status_code == 200, res.text
    queues = res.json()
    keys = [q["queue_key"] for q in queues]
    assert q1 in keys
    assert q2 in keys


@pytest.mark.unit
def test_t3_013_list_queue_jobs_order(auth_headers):
    """T3.013 / FR3.045: GET /v1/posting-queues/{queue_key}/jobs returns ordered jobs."""
    t_id = auth_headers["tenant_id"]
    headers = {"Authorization": auth_headers["Authorization"]}
    q = f"PID:Q_{uuid.uuid4().hex[:6]}"

    enqueue_posting_job(
        tenant_id=t_id,
        queue_key=q,
        doc_family="PhysicalInventory",
        site_id="WH1",
        plant="1010",
        header_data={},
        items=[],
        seq=2,
    )
    enqueue_posting_job(
        tenant_id=t_id,
        queue_key=q,
        doc_family="PhysicalInventory",
        site_id="WH1",
        plant="1010",
        header_data={},
        items=[],
        seq=1,
    )

    res = client.get(f"/v1/posting-queues/{q}/jobs", headers=headers)
    assert res.status_code == 200, res.text
    jobs = res.json()
    assert len(jobs) == 2
    # Verify ordered by seq ASC
    assert jobs[0]["seq"] == 1
    assert jobs[1]["seq"] == 2


@pytest.mark.unit
def test_t3_013_retry_posting_job(auth_headers):
    """T3.013 / FR3.045: POST /v1/posting-jobs/{id}/retry unblocks a failed job."""
    t_id = auth_headers["tenant_id"]
    headers = {"Authorization": auth_headers["Authorization"]}
    q = f"IBD:RETRY_{uuid.uuid4().hex[:6]}"
    job_id = enqueue_posting_job(
        tenant_id=t_id,
        queue_key=q,
        doc_family="GoodsReceipt",
        site_id="WH1",
        plant="1010",
        header_data={},
        items=[],
    )

    # Set to failed
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f"SET app.tenant_id = '{t_id}';")
        cur.execute("UPDATE field.posting_job SET status = 'failed' WHERE id = %s;", (job_id,))

    res = client.post(f"/v1/posting-jobs/{job_id}/retry", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "pending"

    # Verify status in database
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f"SET app.tenant_id = '{t_id}';")
        cur.execute("SELECT status FROM field.posting_job WHERE id = %s;", (job_id,))
        assert cur.fetchone()[0] == "pending"


@pytest.mark.unit
def test_t3_013_cancel_posting_job_and_cascade_dependent_jobs(auth_headers):
    """T3.013 / BR3.14: POST /v1/posting-jobs/{id}/cancel marks dependent successors cancelled."""
    t_id = auth_headers["tenant_id"]
    headers = {"Authorization": auth_headers["Authorization"]}
    q = f"OBD:CANCEL_{uuid.uuid4().hex[:6]}"
    ref_doc = "800099999"

    # Enqueue 3 jobs: j1 (seq 1, ref 800099999), j2 (seq 2, ref 800099999 - dependent), j3 (seq 3, ref 700011111 - independent)
    j1 = enqueue_posting_job(
        tenant_id=t_id,
        queue_key=q,
        doc_family="GoodsIssue",
        site_id="WH1",
        plant="1010",
        header_data={},
        items=[],
        seq=1,
        ref_doc_no=ref_doc,
    )
    j2 = enqueue_posting_job(
        tenant_id=t_id,
        queue_key=q,
        doc_family="GoodsIssue",
        site_id="WH1",
        plant="1010",
        header_data={},
        items=[],
        seq=2,
        ref_doc_no=ref_doc,
    )
    j3 = enqueue_posting_job(
        tenant_id=t_id,
        queue_key=q,
        doc_family="GoodsIssue",
        site_id="WH1",
        plant="1010",
        header_data={},
        items=[],
        seq=3,
        ref_doc_no="700011111",
    )

    # Cancel j1
    res = client.post(f"/v1/posting-jobs/{j1}/cancel", headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["cancelled"] is True
    assert data["dependent_cancelled_count"] == 1
    assert j2 in data["dependent_cancelled_ids"]

    # Verify database statuses
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f"SET app.tenant_id = '{t_id}';")
        cur.execute(
            "SELECT id, status FROM field.posting_job WHERE tenant_id = %s AND queue_key = %s ORDER BY seq ASC;",
            (t_id, q),
        )
        rows = dict(cur.fetchall())
        assert rows[uuid.UUID(j1)] == "cancelled"
        assert rows[uuid.UUID(j2)] == "cancelled"  # Cascaded per BR3.14!
        assert rows[uuid.UUID(j3)] == "pending"  # Independent remains pending!
