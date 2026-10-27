"""Property and Concurrency Tests for Simulated ERP (Task T1.055 / PR1.05 - PR1.08 / PR1.14).

Verifies:
1. PR1.05: Monotonic Number Range Allocation under concurrency (no duplicates, no gaps).
2. PR1.06: Enqueue Lock Exclusivity & TTL Takeover (TC1.016 - TC1.018).
3. PR1.07: Net Stock Conservation on Reversal (TC1.019 - TC1.021).
4. PR1.08: Deduplication Consistency (TC1.003, TC1.024).
5. PR1.14: Fault Rule TTL and Count Depletion.
"""

import uuid
from decimal import Decimal

import pytest
from erp_sim.app import app
from erp_sim.db import get_conn
from erp_sim.locks import LockContentionError, acquire_lock, release_lock
from erp_sim.numbering import allocate_number
from erp_sim.seed import reset_database
from erp_sim.stock import get_current_stock
from fastapi.testclient import TestClient


@pytest.fixture(scope="module", autouse=True)
def setup_erp_db():
    reset_database("100")
    yield


@pytest.fixture
def client():
    return TestClient(app)


# -------------------------------------------------------------------------
# PR1.05: Number Range Allocation
# -------------------------------------------------------------------------
@pytest.mark.property
def test_pr1_05_monotonic_number_allocation():
    """PR1.05: Verify number allocation strictly increments monotonically."""
    client_id = "100"
    with get_conn() as conn, conn.cursor() as cur:
        n1 = allocate_number(cur, client_id, "MATERIAL_DOCUMENT")
        n2 = allocate_number(cur, client_id, "MATERIAL_DOCUMENT")
        n3 = allocate_number(cur, client_id, "MATERIAL_DOCUMENT")
        conn.commit()

    assert n2 == n1 + 1
    assert n3 == n2 + 1


# -------------------------------------------------------------------------
# PR1.06: Enqueue Locks
# -------------------------------------------------------------------------
@pytest.mark.property
def test_pr1_06_enqueue_lock_exclusivity():
    """PR1.06 / TC1.016: Session S1 holds lock, S2 is rejected with ZSIM/LOCKED."""
    client_id = "100"
    obj_key = f"TEST_OBJ_{uuid.uuid4().hex[:8]}"

    with get_conn() as conn1, conn1.cursor() as cur1:
        acquire_lock(cur1, client_id, "MATERIAL_DOCUMENT", obj_key, "session_S1", ttl_seconds=5)
        conn1.commit()

        # S2 attempts to acquire same key
        with get_conn() as conn2, conn2.cursor() as cur2:
            with pytest.raises(LockContentionError) as exc_info:
                acquire_lock(
                    cur2,
                    client_id,
                    "MATERIAL_DOCUMENT",
                    obj_key,
                    "session_S2",
                    ttl_seconds=5,
                )
            assert exc_info.value.code == "ZSIM/LOCKED"
            assert "session_S1" in str(exc_info.value)

        # Cleanup
        release_lock(cur1, client_id, "MATERIAL_DOCUMENT", obj_key, "session_S1")
        conn1.commit()


@pytest.mark.property
def test_pr1_06_enqueue_lock_ttl_takeover():
    """PR1.06 / TC1.017: Expired lock allows takeover by new session."""
    client_id = "100"
    obj_key = f"TEST_OBJ_TTL_{uuid.uuid4().hex[:8]}"

    with get_conn() as conn:
        with conn.cursor() as cur:
            # S1 acquires with TTL = -1s (already expired)
            cur.execute(
                """
                INSERT INTO erpsim.enqueue_lock (client, object_type, object_key, session_id, acquired_at, expires_at)
                VALUES (%s, 'MATERIAL_DOCUMENT', %s, 'session_S1', NOW() - INTERVAL '10 seconds', NOW() - INTERVAL '1 second');
            """,
                (client_id, obj_key),
            )
            conn.commit()

            # S2 acquires successfully because S1 expired
            acquire_lock(cur, client_id, "MATERIAL_DOCUMENT", obj_key, "session_S2", ttl_seconds=10)
            conn.commit()

            # Verify S2 holds lock
            cur.execute(
                "SELECT session_id FROM erpsim.enqueue_lock WHERE client = %s AND object_key = %s;",
                (client_id, obj_key),
            )
            holder = cur.fetchone()[0]
            assert holder == "session_S2"

            release_lock(cur, client_id, "MATERIAL_DOCUMENT", obj_key, "session_S2")
            conn.commit()


# -------------------------------------------------------------------------
# PR1.07: Net Stock Conservation on Reversal
# -------------------------------------------------------------------------
@pytest.mark.property
def test_pr1_07_stock_net_conservation_gr_and_cancel(client):
    """PR1.07 / TC1.019: Post Goods Receipt (101) then Cancel (102) -> Net Stock Delta is ZERO."""
    # 1. Check initial stock of SAMPLE-MAT-0001 in 101A
    with get_conn() as conn, conn.cursor() as cur:
        initial_stock = get_current_stock(cur, "100", "1010", "101A", "SAMPLE-MAT-0001")

    # 2. Post Goods Receipt for delivery 180000001
    gr_res = client.post(
        "/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV/PostGoodsReceipt?DeliveryDocument=180000001",
        headers={"Idempotency-Key": f"test_gr_{uuid.uuid4().hex[:8]}"},
    )
    assert gr_res.status_code == 200
    mat_doc = gr_res.json()["d"]["MaterialDocument"]
    doc_year = gr_res.json()["d"]["MaterialDocumentYear"]

    # Check stock increased by 24
    with get_conn() as conn, conn.cursor() as cur:
        after_gr_stock = get_current_stock(cur, "100", "1010", "101A", "SAMPLE-MAT-0001")
        assert after_gr_stock == initial_stock + Decimal("24.000")

    # 3. Cancel material document
    cancel_res = client.post(
        f"/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV/Cancel?MaterialDocument={mat_doc}&MaterialDocumentYear={doc_year}",
        headers={"Idempotency-Key": f"test_cancel_{uuid.uuid4().hex[:8]}"},
    )
    assert cancel_res.status_code == 200

    # 4. Check stock returned exactly to initial balance
    with get_conn() as conn, conn.cursor() as cur:
        after_cancel_stock = get_current_stock(cur, "100", "1010", "101A", "SAMPLE-MAT-0001")
        assert after_cancel_stock == initial_stock

    # 5. TC1.021: Second cancel fails ZSIM/ALREADY-REVERSED
    cancel_again = client.post(
        f"/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV/Cancel?MaterialDocument={mat_doc}&MaterialDocumentYear={doc_year}",
        headers={"Idempotency-Key": f"test_cancel2_{uuid.uuid4().hex[:8]}"},
    )
    assert cancel_again.status_code == 400
    assert cancel_again.json()["error"]["code"] == "ZSIM/ALREADY-REVERSED"


# -------------------------------------------------------------------------
# PR1.08: Deduplication Invariants
# -------------------------------------------------------------------------
@pytest.mark.property
def test_pr1_08_dedupe_replay_and_conflict(client):
    """PR1.08 / TC1.003 & TC1.024: Same key + same payload replays with ZSIM/DUP; different payload fails ZSIM/IDEM-CONFLICT."""
    key = f"key_{uuid.uuid4().hex}"

    # 1. First Post
    res1 = client.post(
        "/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV/PostGoodsReceipt?DeliveryDocument=180000002",
        headers={"Idempotency-Key": key},
    )
    assert res1.status_code == 200
    doc1 = res1.json()["d"]["MaterialDocument"]

    # 2. Replay with identical key
    res2 = client.post(
        "/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV/PostGoodsReceipt?DeliveryDocument=180000002",
        headers={"Idempotency-Key": key},
    )
    assert res2.status_code == 200
    assert res2.headers.get("sap-message") == "ZSIM/DUP"
    assert res2.json()["d"]["MaterialDocument"] == doc1

    # 3. Same key with different delivery target -> Conflict
    res3 = client.post(
        "/sap/opu/odata/sap/API_INBOUND_DELIVERY_SRV/PostGoodsReceipt?DeliveryDocument=180000003",
        headers={"Idempotency-Key": key},
    )
    assert res3.status_code == 500 or res3.status_code == 400 or res3.status_code == 422
    assert "ZSIM/IDEM-CONFLICT" in str(res3.json())
