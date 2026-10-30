"""M2 jobs contract: pure rules and small DB rules (docs/design/M2_JOBS_CONTRACT.md).

- PR4.11 (position form): classify_positions reports every expected and every captured unit
- contract §2 state words round-trip to the stored states; blind count subtitles carry no quantities
- bin proposal rules fixed / empty / shared on field.bin_stock (FR3.013)
- CORS allow-list never contains '*'; a console preflight is answered before auth
- POST /v1/safety/visits/{id}/ack needs field.visit.ack (supervisors hold it)
"""

from __future__ import annotations

import os
import uuid
from decimal import Decimal

import psycopg
import pytest
from fastapi.testclient import TestClient
from field_api.app import app, console_origins
from field_api.audit.reconcile import PositionCheck, classify_positions
from field_api.auth.jwt import create_dev_token
from field_api.auth.permissions import ROLE_PERMISSIONS
from field_api.jobs.status import (
    LINE_STATE_OUT,
    TASK_STATE_OUT,
    compose_subtitle,
    hash_quantity_column,
    split_list,
    to_db_task_states,
)
from field_api.jobs.tower_tasks import position_label
from field_common.bin_stock import change_stock, propose_bin
from hypothesis import given, settings
from hypothesis import strategies as st

ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
SERIALS = st.sampled_from([f"RRU-{i:04d}" for i in range(12)])


@pytest.mark.property
@settings(max_examples=300, deadline=None)
@given(
    positions=st.lists(st.tuples(SERIALS, st.one_of(st.none(), SERIALS)), min_size=0, max_size=8,
                       unique_by=lambda p: p[0]),
    elsewhere=st.sets(SERIALS, max_size=6),
)
def test_pr4_11_position_reconciliation_reports_both_sides(
    positions: list[tuple[str, str | None]], elsewhere: set[str]
) -> None:
    """PR4.11: every expected unit and every captured unit appears in a finding; matched iff C == E;
    a different serial is misplaced only when the installed base has it at another position."""
    checks = [PositionCheck(f"l{i}", e, c, f"loc{i}") for i, (e, c) in enumerate(positions)]
    installed = {e: f"loc{i}" for i, (e, _c) in enumerate(positions)}
    installed.update({s: "far" for s in elsewhere if s not in installed})
    out = classify_positions(checks, installed)
    expected_seen = {e for cls, e, _f, _l in out if e}
    found_seen = {f for _cls, _e, f, _l in out if f}
    # an expected unit found at another position is reported there, as the found serial
    assert {e for e, _c in positions} <= expected_seen | found_seen
    assert {c for _e, c in positions if c} <= found_seen
    assert sum(1 for cls, *_ in out if cls == "matched") == sum(1 for e, c in positions if c == e)
    for cls, e, f, line in out:
        if cls == "serial_mismatch":
            assert f != e and (f not in installed or installed[f] == f"loc{line[1:]}")
        if cls == "misplaced":
            assert f in installed and installed[f] != f"loc{line[1:]}"
    for e, c in positions:  # an unknown serial at a position is one finding, not two
        if c and c != e and c not in installed:
            assert [x for x in out if x[1] == e and x[0] == "erp_only"] == []


@pytest.mark.unit
def test_classify_positions_examples() -> None:
    checks = [PositionCheck("a", "S1", "S1", "p1"), PositionCheck("b", "S2", "X9", "p2"),
              PositionCheck("c", "S3", None, "p3"), PositionCheck("d", "S4", "S5", "p4")]
    out = classify_positions(checks, {"S1": "p1", "S2": "p2", "S3": "p3", "S4": "p4", "S5": "p9"})
    assert out == [("matched", "S1", "S1", "a"), ("serial_mismatch", "S2", "X9", "b"), ("erp_only", "S3", None, "c"),
                   ("misplaced", "S4", "S5", "d"), ("erp_only", "S4", None, "d")]


@pytest.mark.property
@given(st.lists(st.sampled_from(sorted(TASK_STATE_OUT)), min_size=1, max_size=5))
def test_contract_task_states_round_trip(states: list[str]) -> None:
    """Contract §2: a client filter in contract words maps back to exactly the stored states."""
    out = [TASK_STATE_OUT[s] for s in states]
    assert to_db_task_states(out) == states
    assert to_db_task_states(states) == states  # stored words stay accepted (older clients)
    assert to_db_task_states([*out, "bogus"]) is None
    assert split_list(",".join(out) + ", ,") == out


@pytest.mark.unit
def test_line_states_are_contract_words() -> None:
    assert set(LINE_STATE_OUT.values()) <= {"open", "counted", "confirmed", "flagged", "done"}
    assert set(TASK_STATE_OUT.values()) <= {"open", "in_progress", "awaiting_posting", "awaiting_approval", "done",
                                            "failed", "cancelled"}


@pytest.mark.property
@given(st.sampled_from(["receive", "putaway", "pick", "count", "audit", "swap"]), st.integers(0, 40),
       st.decimals(min_value=0, max_value=10_000, places=3), st.one_of(st.none(), st.text(min_size=1, max_size=12)))
def test_subtitle_is_blind_for_counts(task_type: str, n: int, pieces: Decimal, context: str | None) -> None:
    """FR3.029: a count task's subtitle never carries a quantity; others carry their line totals."""
    sub = compose_subtitle(task_type, context, n, pieces)
    if task_type == "count":
        assert "piece" not in sub and sub.endswith("blind count")
    elif task_type in ("receive", "putaway", "pick"):
        assert "piece" in sub
    if context:
        assert sub.startswith(context)


@pytest.mark.unit
def test_staged_hash_quantity_per_type() -> None:
    assert [hash_quantity_column(t) for t in ("receive", "count", "pick", "putaway", "audit", "swap")] == [
        "counted_qty", "counted_qty", "picked_qty", "counted_qty", "counted_qty", "counted_qty"]


@pytest.mark.unit
def test_position_labels() -> None:
    assert position_label("A", "S2") == "Sector A · slot 2"
    assert position_label("B", "P10") == "Sector B · slot 10"
    assert position_label("A", "MW") == "Sector A · MW"
    assert position_label(None, "3") == "slot 3"
    assert position_label("A", None) is None


@pytest.mark.unit
def test_bin_proposal_fixed_empty_shared() -> None:
    """FR3.013 on field.bin_stock: the material's own bin, else the first empty bin, else the least filled."""
    tenant, site = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(ADMIN) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, true), set_config('app.site_ids', '*', true)", (tenant,))
        cur.execute("INSERT INTO field.site (id, tenant_id, code, name, kind) VALUES (%s, %s, %s, 'b', 'warehouse')",
                    (site, tenant, f"B-{site[:8].upper()}"))
        for code in ("03-01-01", "02-01-02", "02-01-01"):
            cur.execute("INSERT INTO field.location (tenant_id, site_id, kind, code, path, depth, erp_ref, erp_ref_type)"
                        " VALUES (%s, %s, 'position', %s, %s, 1, %s, 'storage_bin')",
                        (tenant, site, code, code, f"{site}/{code}"))
        assert propose_bin(cur, site, "M-1") == ("02-01-01", "empty")
        assert propose_bin(cur, site, "M-1", reserved={"02-01-01"}) == ("02-01-02", "empty")
        change_stock(cur, tenant_id=tenant, site_id=site, storage_bin="02-01-02", material_no="M-1", delta=Decimal(5))
        assert propose_bin(cur, site, "M-1") == ("02-01-02", "fixed")
        change_stock(cur, tenant_id=tenant, site_id=site, storage_bin="02-01-01", material_no="M-2", delta=Decimal(9))
        change_stock(cur, tenant_id=tenant, site_id=site, storage_bin="03-01-01", material_no="M-3", delta=Decimal(2))
        assert propose_bin(cur, site, "M-4") == ("03-01-01", "shared")  # no empty bin left: least filled
        assert change_stock(cur, tenant_id=tenant, site_id=site, storage_bin="02-01-02", material_no="M-1",
                            delta=Decimal(-8)) == 0  # never below zero
        with pytest.raises(ValueError):
            change_stock(cur, tenant_id=tenant, site_id=site, storage_bin="x", material_no="y")
        c.rollback()


@pytest.mark.unit
def test_cors_allow_list(monkeypatch: pytest.MonkeyPatch) -> None:
    api = TestClient(app)
    pre = {"Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"}
    r = api.options("/v1/tasks", headers={"Origin": "http://localhost:3000", **pre})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "http://localhost:3000"
    r = api.options("/v1/tasks", headers={"Origin": "https://evil.example", **pre})
    assert "access-control-allow-origin" not in r.headers
    monkeypatch.setenv("FIELD_CONSOLE_ORIGINS", "http://console.local:3000/, http://10.0.0.5:3000")
    assert console_origins() == ["http://console.local:3000", "http://10.0.0.5:3000"]
    monkeypatch.setenv("FIELD_CONSOLE_ORIGINS", "*")
    with pytest.raises(RuntimeError):
        console_origins()


@pytest.mark.unit
def test_safety_ack_needs_visit_ack() -> None:
    assert "field.visit.ack" in ROLE_PERMISSIONS["field.supervisor"]
    tenant = str(uuid.uuid4())
    api = TestClient(app)
    viewer = create_dev_token("v-1", tenant, ["field.viewer"])
    r = api.post(f"/v1/safety/visits/{uuid.uuid4()}/ack", json={},
                 headers={"Authorization": f"Bearer {viewer}", "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 403
    sup = create_dev_token("s-1", tenant, ["field.supervisor"])
    r = api.post(f"/v1/safety/visits/{uuid.uuid4()}/ack", json={},
                 headers={"Authorization": f"Bearer {sup}", "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 404  # allowed through; the visit does not exist
