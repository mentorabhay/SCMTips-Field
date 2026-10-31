"""ERP-sim admin pages (T1.054) and fault-rule count depletion (PR1.14).

Owner report 2026-10-31: Documents, a document, Locks & Ranges and Fault Rules linked from the
simulator's overview returned 404 (only Overview and Stock existed). While building the Faults page,
a rule armed for one failure was found to fail every call: the count was decremented in the request's
transaction, which the injected error rolled back.
"""

import asyncio
import uuid

import pytest
from erp_sim.admin_ui import is_local_request
from erp_sim.app import app
from erp_sim.db import get_conn
from erp_sim.faults import evaluate_faults
from erp_sim.seed import reset_database
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

SVC, OP = "API_TEST_SRV", "PostSomething"


@pytest.fixture(scope="module", autouse=True)
def _seeded() -> None:
    reset_database("100")


def local_client() -> TestClient:
    return TestClient(app, base_url="http://127.0.0.1:8002", client=("127.0.0.1", 50000))


def _post_doc() -> tuple[str, str, str]:
    """A 101 document with one item and its 102 reversal, straight in the tables."""
    doc, rev, year = f"49{uuid.uuid4().int % 10**8:08d}", f"49{uuid.uuid4().int % 10**8:08d}", "2026"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO erpsim.document (client, doc_number, fiscal_year, doc_type, movement_type, status, header_data)"
            " VALUES ('100', %s, %s, 'WE', '101', 'reversed', '{\"delivery\": \"<b>1800</b>\"}')",
            (doc, year),
        )
        cur.execute(
            "INSERT INTO erpsim.document_item (client, doc_number, fiscal_year, line_no, material_no, plant,"
            " storage_location, quantity, uom, movement_type) VALUES ('100', %s, %s, 1, 'SAMPLE-MAT-0001', '1000',"
            " '101A', 7, 'EA', '101')",
            (doc, year),
        )
        cur.execute(
            "INSERT INTO erpsim.document (client, doc_number, fiscal_year, doc_type, movement_type, reversal_of, status)"
            " VALUES ('100', %s, %s, 'WE', '102', %s, 'posted')",
            (rev, year, doc),
        )
        conn.commit()
    return doc, rev, year


@pytest.mark.parametrize("path", ["", "/documents", "/documents?movement=101", "/stock", "/locks", "/faults"])
def test_every_nav_page_answers(path: str) -> None:
    r = local_client().get(f"/_sim/ui{path}")
    assert r.status_code == 200, r.text[:300]
    for href in ("/_sim/ui/documents", "/_sim/ui/stock", "/_sim/ui/locks", "/_sim/ui/faults"):
        assert f'href="{href}"' in r.text


def test_document_page_shows_items_and_reversal_chain_escaped() -> None:
    doc, rev, year = _post_doc()
    c = local_client()
    r = c.get(f"/_sim/ui/documents/{doc}/{year}")
    assert r.status_code == 200
    assert "SAMPLE-MAT-0001" in r.text and f"/_sim/ui/documents/{rev}/{year}" in r.text
    assert "<b>1800</b>" not in r.text and "&lt;b&gt;1800&lt;/b&gt;" in r.text
    listing = c.get("/_sim/ui/documents").text
    assert doc in listing and rev in listing
    assert c.get(f"/_sim/ui/documents/{rev}/{year}").text.count(f"/_sim/ui/documents/{doc}/{year}") >= 1
    missing = c.get("/_sim/ui/documents/0000000000/2026")
    assert missing.status_code == 404 and "not found" in missing.text


def test_fault_form_arms_a_rule_and_switches_it_off() -> None:
    c = local_client()
    r = c.post(
        "/_sim/ui/faults",
        data={"target": "API_OUTBOUND_DELIVERY_SRV|PostGoodsIssue", "kind": "http_5xx", "count": "2", "minutes": "5"},
        headers={"Origin": "http://127.0.0.1:8002"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, count, ttl_s, active FROM erpsim.fault_rule WHERE operation = 'PostGoodsIssue'"
            " ORDER BY created_at DESC LIMIT 1"
        )
        row = cur.fetchone()
    assert row is not None and (row[1], row[2], row[3]) == (2, 300, True)
    assert c.post(f"/_sim/ui/faults/{row[0]}/off", follow_redirects=False).status_code == 303
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT active FROM erpsim.fault_rule WHERE id = %s", (row[0],))
        off = cur.fetchone()
    assert off is not None and off[0] is False


def test_fault_form_refuses_unknown_targets() -> None:
    r = local_client().post("/_sim/ui/faults", data={"target": "X|Y", "kind": "http_5xx", "count": "1", "minutes": "1"})
    assert r.status_code == 422


def _req(host: str, origin: str | None, port: int = 8002) -> Request:
    headers = [(b"host", f"127.0.0.1:{port}".encode())]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers, "client": (host, 1),
                    "server": ("127.0.0.1", port), "scheme": "http", "query_string": b""})


@pytest.mark.parametrize(
    "host, origin, ok",
    [
        ("127.0.0.1", None, True),
        ("127.0.0.1", "http://127.0.0.1:8002", True),
        ("127.0.0.1", "http://localhost:8002", True),
        ("::1", None, True),
        ("192.168.29.50", None, False),  # another device on the Wi-Fi
        ("127.0.0.1", "https://evil.example", False),  # a web page in the same browser
        ("127.0.0.1", "http://127.0.0.1:3000", False),  # another local app
        ("testclient", None, False),
    ],
)
def test_actions_only_from_this_pc_and_this_page(host: str, origin: str | None, ok: bool) -> None:
    assert is_local_request(_req(host, origin)) is ok


def test_reset_from_another_device_is_refused() -> None:
    remote = TestClient(app, base_url="http://127.0.0.1:8002", client=("192.168.29.50", 50000))
    assert remote.post("/_sim/ui/reset", follow_redirects=False).status_code == 403


def _arm(count: int) -> uuid.UUID:
    rule = uuid.uuid4()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE erpsim.fault_rule SET active = false WHERE service = %s", (SVC,))
        cur.execute(
            "INSERT INTO erpsim.fault_rule (id, client, kind, service, operation, doc_key, probability, count, ttl_s,"
            " seed, active) VALUES (%s, '100', 'http_5xx', %s, %s, NULL, 1.0, %s, 300, NULL, true)",
            (rule, SVC, OP, count),
        )
        conn.commit()
    return rule


def _call_in_rolled_back_txn() -> bool:
    """One SAP call as the services make it: evaluate faults on the request's cursor, then roll back on error."""
    with get_conn() as conn, conn.cursor() as cur:
        try:
            asyncio.run(evaluate_faults(cur, "100", SVC, OP, "DOC-1"))
        except HTTPException as exc:
            conn.rollback()
            assert exc.status_code == 500
            return True
        conn.commit()
        return False


@pytest.mark.property
@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(count=st.integers(min_value=1, max_value=4), extra=st.integers(min_value=1, max_value=3))
def test_pr1_14_fault_rule_count_depletes_even_though_the_failed_call_rolls_back(count: int, extra: int) -> None:
    """PR1.14: a rule armed for N failures fails exactly the next N matching calls, then switches itself off."""
    rule = _arm(count)
    outcomes = [_call_in_rolled_back_txn() for _ in range(count + extra)]
    assert outcomes == [True] * count + [False] * extra
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count, active FROM erpsim.fault_rule WHERE id = %s", (rule,))
        row = cur.fetchone()
    assert row is not None and (row[0], row[1]) == (0, False)


@pytest.mark.property
def test_pr1_14_expired_rule_never_fires() -> None:
    rule = _arm(3)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE erpsim.fault_rule SET created_at = now() - interval '10 minutes' WHERE id = %s", (rule,))
        conn.commit()
    assert _call_in_rolled_back_txn() is False
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT active FROM erpsim.fault_rule WHERE id = %s", (rule,))
        row = cur.fetchone()
    assert row is not None and row[0] is False
