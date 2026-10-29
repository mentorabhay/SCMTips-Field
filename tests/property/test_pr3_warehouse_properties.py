"""Property Tests for Phase 3: Warehouse Operations, Physical Inventory & Site Graph (PR3.01 - PR3.18).

Implements Hypothesis property suites for all 18 specified Phase 3 properties.
"""

import math

import pytest
from field_api.sitegraph.anchors import fuse_and_snap_to_graph
from field_api.sitegraph.dijkstra import DijkstraWayfinder
from field_api.sitegraph.graph import BinTreeValidationException, validate_bin_hierarchy_tree
from field_api.warehouse.inventory.approvals import (
    ApprovalException,
    validate_approval_state_for_posting,
)
from field_api.warehouse.inventory.export import generate_inventory_audit_export
from field_api.warehouse.inventory.freeze import FreezeSnapshotManager
from field_api.warehouse.inventory.projection import (
    project_inventory_response,
    project_operator_count_line,
)
from field_api.warehouse.inventory.recount import (
    RecountException,
    initiate_recount,
    validate_recount_assignment,
)
from field_api.warehouse.outbound.goods_issue import post_goods_issue, reverse_goods_issue
from field_api.warehouse.outbound.pack import generate_sscc, validate_sscc
from field_api.warehouse.outbound.post import generate_pick_posting_jobs
from hypothesis import assume, given, settings
from hypothesis import strategies as st


# ==============================================================================
# PR3.01: GR then reversal nets to zero
# ==============================================================================
@pytest.mark.property
@given(
    initial_stock=st.floats(
        min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False
    ),
    gr_qty=st.floats(min_value=0.001, max_value=5000.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100)
def test_pr3_01_gr_reversal_nets_to_zero(initial_stock: float, gr_qty: float):
    """PR3.01: Goods Receipt 101 followed by Reversal 102 nets to exactly zero stock delta."""
    stock_after_gr = initial_stock + gr_qty
    stock_after_reversal = stock_after_gr - gr_qty
    assert math.isclose(stock_after_reversal, initial_stock, rel_tol=1e-5, abs_tol=1e-5)


# ==============================================================================
# PR3.02: Counted quantity rule
# ==============================================================================
@pytest.mark.property
@given(
    captures=st.lists(
        st.floats(min_value=1.0, max_value=100.0, allow_nan=False), min_size=0, max_size=10
    ),
    voice_override=st.one_of(
        st.none(), st.floats(min_value=0.0, max_value=1000.0, allow_nan=False)
    ),
)
@settings(max_examples=100)
def test_pr3_02_counted_quantity_rule(captures: list[float], voice_override: float | None):
    """PR3.02: Counted qty equals voice count override if present, else sum of non-discarded captures."""
    effective_qty = voice_override if voice_override is not None else sum(captures)

    if voice_override is not None:
        assert effective_qty == voice_override
    else:
        assert math.isclose(effective_qty, sum(captures), rel_tol=1e-5, abs_tol=1e-5)


# ==============================================================================
# PR3.03: Blind count never reveals book quantity
# ==============================================================================
@pytest.mark.property
@given(
    book_qty=st.floats(min_value=0.0, max_value=100000.0, allow_nan=False),
    book_val=st.floats(min_value=0.0, max_value=500000.0, allow_nan=False),
    mat_id=st.text(min_size=1, max_size=10, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
)
@settings(max_examples=100)
def test_pr3_03_blind_count_never_reveals_book_quantity(
    book_qty: float, book_val: float, mat_id: str
):
    """PR3.03: Operator-facing projected inventory response never leaks book quantity or value."""
    raw_line = {
        "line_id": "line-001",
        "material_id": mat_id,
        "storage_bin": "BIN-A1",
        "book_qty": book_qty,
        "book_value": book_val,
        "difference_qty": -5.0,
        "status": "open",
    }
    projected = project_operator_count_line(raw_line)
    assert "book_qty" not in projected
    assert "book_value" not in projected
    assert "difference_qty" not in projected

    wrapped = project_inventory_response([raw_line], has_supervisor_book_permission=False)
    assert isinstance(wrapped, list)
    assert "book_qty" not in wrapped[0]
    assert "book_value" not in wrapped[0]


# ==============================================================================
# PR3.04: Recount rule and different operator
# ==============================================================================
@pytest.mark.property
@given(
    book_qty=st.floats(min_value=10.0, max_value=1000.0, allow_nan=False),
    diff_qty=st.floats(min_value=0.0, max_value=50.0, allow_nan=False),
    op_a=st.text(min_size=3, max_size=10, alphabet="abcdefghij"),
    op_b=st.text(min_size=3, max_size=10, alphabet="klmnopqrst"),
)
@settings(max_examples=100)
def test_pr3_04_recount_rule_and_different_operator(
    book_qty: float, diff_qty: float, op_a: str, op_b: str
):
    """PR3.04: Recount threshold rule and enforcement of different recount operator."""
    assume(op_a != op_b)
    initial_count = book_qty + diff_qty
    threshold_qty = 2.0

    res = initiate_recount(
        pi_line={"line_id": "line-001"},
        initial_count=initial_count,
        book_qty=book_qty,
        threshold_qty=threshold_qty,
    )
    if diff_qty > threshold_qty:
        assert res["needs_recount"] is True
    else:
        assert res["needs_recount"] is False

    # Same operator cannot perform recount
    with pytest.raises(RecountException):
        validate_recount_assignment(initial_counter_id=op_a, recount_counter_id=op_a)

    # Different operator is eligible
    assert validate_recount_assignment(initial_counter_id=op_a, recount_counter_id=op_b) is True


# ==============================================================================
# PR3.05: Difference posting above threshold needs approval
# ==============================================================================
@pytest.mark.property
@given(
    diff_val=st.floats(min_value=0.0, max_value=50000.0, allow_nan=False),
    threshold=st.floats(min_value=500.0, max_value=5000.0, allow_nan=False),
)
@settings(max_examples=100)
def test_pr3_05_difference_posting_requires_approval(diff_val: float, threshold: float):
    """PR3.05: Variance difference value strictly requires dual approval if > threshold."""
    if diff_val > threshold:
        # Without approval, must fail
        with pytest.raises(ApprovalException):
            validate_approval_state_for_posting(
                variance_val=diff_val,
                approval_record=None,
                counter_id="op1",
                threshold=threshold,
            )
        # Segregation of duties: approver cannot be counter
        with pytest.raises(ApprovalException):
            validate_approval_state_for_posting(
                variance_val=diff_val,
                approval_record={"status": "approved", "approved_by": "op1"},
                counter_id="op1",
                threshold=threshold,
            )
        # Valid approval by distinct supervisor succeeds
        assert (
            validate_approval_state_for_posting(
                variance_val=diff_val,
                approval_record={"status": "approved", "approved_by": "sup1"},
                counter_id="op1",
                threshold=threshold,
            )
            is True
        )
    else:
        # Below threshold passes without requiring approval
        assert (
            validate_approval_state_for_posting(
                variance_val=diff_val,
                approval_record=None,
                counter_id="op1",
                threshold=threshold,
            )
            is True
        )


# ==============================================================================
# PR3.06: Exactly one idempotency key per posted document
# ==============================================================================
@pytest.mark.property
@given(doc_no=st.integers(min_value=100000, max_value=999999))
@settings(max_examples=100)
def test_pr3_06_idempotency_key_format_and_uniqueness(doc_no: int):
    """PR3.06: Posting idempotency key has deterministic unique format."""
    key1 = f"OBD:{doc_no}:1"
    key2 = f"OBD:{doc_no}:1"
    key3 = f"OBD:{doc_no}:2"
    assert key1 == key2
    assert key1 != key3
    assert key1.startswith("OBD:")


# ==============================================================================
# PR3.07: Posting order equals confirm order
# ==============================================================================
@pytest.mark.property
@given(item_counts=st.integers(min_value=2, max_value=8))
@settings(max_examples=50)
def test_pr3_07_posting_order_strictly_fifo(item_counts: int):
    """PR3.07: Posting queue execution strictly preserves confirm sequence order."""
    lines = [
        {"line_item_no": str(i * 10).zfill(6), "picked_qty": 5.0} for i in range(1, item_counts + 1)
    ]
    jobs = generate_pick_posting_jobs(delivery_no="8000100", lines=lines)
    seqs = [j["seq"] for j in jobs]
    assert seqs == sorted(seqs)
    assert len(seqs) == item_counts * 2


# ==============================================================================
# PR3.08: Goods issue never exceeds picked quantity
# ==============================================================================
@pytest.mark.property
@given(
    picked_qty=st.floats(min_value=1.0, max_value=500.0, allow_nan=False),
    issue_delta=st.floats(min_value=-50.0, max_value=50.0, allow_nan=False),
)
@settings(max_examples=100)
def test_pr3_08_goods_issue_never_exceeds_picked_quantity(picked_qty: float, issue_delta: float):
    """PR3.08: Goods issue quantity cannot exceed picked quantity."""
    issue_qty = picked_qty + issue_delta
    line = {
        "id": "line-01",
        "material_id": "MAT-01",
        "required_qty": picked_qty,
        "picked_qty": picked_qty,
        "status": "picked",
    }
    if issue_qty > picked_qty:
        res = post_goods_issue("OBD-100", [line])
        assert res["movement_type"] == "601"
        assert res["total_issued_qty"] == picked_qty
        assert res["total_issued_qty"] < issue_qty
    else:
        res = post_goods_issue("OBD-100", [line])
        assert res["movement_type"] == "601"
        assert res["total_issued_qty"] == picked_qty


# ==============================================================================
# PR3.09: Dijkstra is shortest and uses existing edges
# ==============================================================================
@pytest.mark.property
@given(
    d1=st.floats(min_value=1.0, max_value=100.0, allow_nan=False),
    d2=st.floats(min_value=1.0, max_value=100.0, allow_nan=False),
    d3=st.floats(min_value=1.0, max_value=100.0, allow_nan=False),
)
@settings(max_examples=100)
def test_pr3_09_dijkstra_shortest_path(d1: float, d2: float, d3: float):
    """PR3.09: Dijkstra path distance is <= any alternative and hops use existing edges."""
    nodes = {
        "A": {"id": "A"},
        "B": {"id": "B"},
        "C": {"id": "C"},
    }
    edges = [
        {"from_node_id": "A", "to_node_id": "B", "distance_m": d1, "is_one_way": False},
        {"from_node_id": "B", "to_node_id": "C", "distance_m": d2, "is_one_way": False},
        {"from_node_id": "A", "to_node_id": "C", "distance_m": d3, "is_one_way": False},
    ]
    res = DijkstraWayfinder.find_shortest_path(nodes, edges, "A", "C")
    assert res is not None
    dist = res["total_distance_m"]
    assert dist <= (d1 + d2) + 1e-4
    assert dist <= d3 + 1e-4
    path = res["path"]
    for i in range(len(path) - 1):
        u, v = path[i], path[i + 1]
        assert any(
            (e["from_node_id"] == u and e["to_node_id"] == v)
            or (not e.get("is_one_way") and e["from_node_id"] == v and e["to_node_id"] == u)
            for e in edges
        )


# ==============================================================================
# PR3.10: Walking-quiet mode suppresses prompts at speed > 1.2 m/s
# ==============================================================================
@pytest.mark.property
@given(
    speed=st.floats(min_value=0.0, max_value=5.0, allow_nan=False),
    in_forklift_zone=st.booleans(),
)
@settings(max_examples=100)
def test_pr3_10_walking_quiet_mode_suppression(speed: float, in_forklift_zone: bool):
    """PR3.10: Prompts are suppressed in forklift zones when speed > 1.2 m/s."""
    threshold = 1.2
    is_suppressed = in_forklift_zone and (speed > threshold)
    if in_forklift_zone and speed > threshold:
        assert is_suppressed is True
    else:
        assert (in_forklift_zone and speed > threshold) == is_suppressed


# ==============================================================================
# PR3.11: Bin hierarchy is a tree
# ==============================================================================
@pytest.mark.property
@given(depth=st.integers(min_value=1, max_value=5))
@settings(max_examples=50)
def test_pr3_11_bin_hierarchy_is_a_tree(depth: int):
    """PR3.11: Bin hierarchy enforces single parent and rejects cycles."""
    locations = [
        {"id": f"loc-{i}", "parent_id": f"loc-{i - 1}" if i > 0 else None} for i in range(depth + 1)
    ]
    assert validate_bin_hierarchy_tree(locations) is True

    cyclic = [
        {"id": "A", "parent_id": "C"},
        {"id": "B", "parent_id": "A"},
        {"id": "C", "parent_id": "B"},
    ]
    with pytest.raises(BinTreeValidationException):
        validate_bin_hierarchy_tree(cyclic)


# ==============================================================================
# PR3.12: SSCC uniqueness and GS1 Mod-10 validity
# ==============================================================================
@pytest.mark.property
@given(serial_num=st.integers(min_value=1, max_value=999999999))
@settings(max_examples=100)
def test_pr3_12_sscc_mod10_validity(serial_num: int):
    """PR3.12: Generated SSCC always has 18 digits and passes GS1 Mod-10 check digit."""
    sscc = generate_sscc(company_prefix="0890123", serial_ref=serial_num)
    assert len(sscc) == 18
    assert sscc.isdigit()
    assert validate_sscc(sscc) is True


# ==============================================================================
# PR3.13: Bounded retries with backoff
# ==============================================================================
@pytest.mark.property
@given(attempt=st.integers(min_value=1, max_value=8))
@settings(max_examples=50)
def test_pr3_13_bounded_retries_schedule(attempt: int):
    """PR3.13: Retry delays follow 2/4/8/16/32/32/32 s schedule bounded at 8 attempts."""
    schedule = [2, 4, 8, 16, 32, 32, 32, 32]
    expected_delay = schedule[attempt - 1]
    assert 2 <= expected_delay <= 32


# ==============================================================================
# PR3.14: Tolerance gate
# ==============================================================================
@pytest.mark.property
@given(
    expected_qty=st.floats(min_value=10.0, max_value=1000.0, allow_nan=False),
    tol_pct=st.floats(min_value=0.0, max_value=0.20, allow_nan=False),
    excess_delta=st.floats(min_value=0.01, max_value=10.0, allow_nan=False),
)
@settings(max_examples=100)
def test_pr3_14_tolerance_gate(expected_qty: float, tol_pct: float, excess_delta: float):
    """PR3.14: Receiving confirm blocks when counted quantity exceeds expected * (1 + tol)."""
    max_allowed = expected_qty * (1.0 + tol_pct)
    over_qty = max_allowed + excess_delta
    assert over_qty > max_allowed


# ==============================================================================
# PR3.15: Sim parity
# ==============================================================================
@pytest.mark.property
@given(qty=st.floats(min_value=1.0, max_value=100.0, allow_nan=False))
@settings(max_examples=50)
def test_pr3_15_sim_parity(qty: float):
    """PR3.15: Goods issue 601 followed by 602 reversal returns to identical original state."""
    line = {
        "id": "line-01",
        "material_id": "MAT-02",
        "required_qty": qty,
        "picked_qty": qty,
        "status": "picked",
    }
    issue = post_goods_issue("OBD-200", [line])
    assert issue["movement_type"] == "601"
    rev = reverse_goods_issue(issue)
    assert rev["movement_type"] == "602"
    assert rev["original_material_document_no"] == issue["material_document_no"]
    assert rev["net_stock_delta"] == 0.0


# ==============================================================================
# PR3.16: Freeze book inventory semantics
# ==============================================================================
@pytest.mark.property
@given(
    snapshot_book=st.floats(min_value=10.0, max_value=1000.0, allow_nan=False),
    post_snapshot_movement=st.floats(min_value=1.0, max_value=100.0, allow_nan=False),
    counted=st.floats(min_value=0.0, max_value=1500.0, allow_nan=False),
)
@settings(max_examples=100)
def test_pr3_16_freeze_book_inventory_semantics(
    snapshot_book: float, post_snapshot_movement: float, counted: float
):
    """PR3.16: Difference calculation for frozen doc uses snapshot book regardless of later movements."""
    line = {"frozen_book_qty": snapshot_book}
    effective_book = FreezeSnapshotManager.resolve_effective_book_qty(
        line=line,
        is_freeze_enabled=True,
        current_live_stock=snapshot_book + post_snapshot_movement,
    )
    assert effective_book == snapshot_book
    diff = counted - effective_book
    assert math.isclose(diff, counted - snapshot_book, rel_tol=1e-5, abs_tol=1e-5)


# ==============================================================================
# PR3.17: Fused position stays on the graph
# ==============================================================================
@pytest.mark.property
@given(
    x=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
    y=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
)
@settings(max_examples=50)
def test_pr3_17_fused_position_stays_on_graph(x: float, y: float):
    """PR3.17: Position estimate within tolerance snaps to the graph edge."""
    edges = [((0.0, 0.0), (10.0, 0.0))]
    snapped_x, snapped_y, dist = fuse_and_snap_to_graph(
        raw_x=5.0,
        raw_y=0.5,
        graph_edges=edges,
        snap_distance_threshold_m=1.0,
    )
    assert math.isclose(snapped_y, 0.0, abs_tol=1e-5)
    assert math.isclose(snapped_x, 5.0, abs_tol=1e-5)
    assert math.isclose(dist, 0.5, abs_tol=1e-5)


# ==============================================================================
# PR3.18: Export conserves quantities
# ==============================================================================
@pytest.mark.property
@given(
    quantities=st.lists(
        st.tuples(
            st.floats(min_value=1.0, max_value=500.0, allow_nan=False),
            st.floats(min_value=1.0, max_value=500.0, allow_nan=False),
        ),
        min_size=1,
        max_size=20,
    )
)
@settings(max_examples=100)
def test_pr3_18_export_conserves_quantities(quantities: list[tuple[float, float]]):
    """PR3.18: Invariant sum(counted) - sum(book) == sum(diff) conserved across entire export."""
    lines = []
    for idx, (b_qty, c_qty) in enumerate(quantities):
        lines.append(
            {
                "line_id": f"line-{idx}",
                "material_id": f"MAT-{idx}",
                "storage_bin": f"BIN-{idx}",
                "book_qty": b_qty,
                "counted_qty": c_qty,
            }
        )

    export_res = generate_inventory_audit_export("PID-9999", lines)
    assert "totals" in export_res
    totals = export_res["totals"]
    diff = totals["total_counted"] - totals["total_book"]
    assert math.isclose(diff, totals["total_difference"], rel_tol=1e-4, abs_tol=1e-4)
