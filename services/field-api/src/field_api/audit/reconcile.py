"""Audit Reconciliation Engine (Task T4.015 / FR4.025 / PR4.11 / API4.06).

Classifies findings into matched, serial_mismatch, tower_only, erp_only, and misplaced
based on expected task_lines, on-site captures, and site installed base.
Enforces symmetric set differences per PR4.11 and blocks reconciliation on signed-off tasks.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from field_api.audit.progress import calculate_completeness
from field_api.db import get_conn

logger = structlog.get_logger(__name__)


@dataclass
class ReconcileItem:
    serial_no: str
    location_id: str | None = None
    equipment_class: str = "UNKNOWN"
    capture_id: str | None = None
    reason: str | None = None


@dataclass
class ReconciliationSummary:
    matched: int = 0
    serial_mismatch: int = 0
    tower_only: int = 0
    erp_only: int = 0
    misplaced: int = 0
    completeness: float = 0.0
    findings: list[dict[str, Any]] = field(default_factory=list)


def classify_sets_symmetric(
    expected_serials: set[str],
    captured_serials: set[str],
) -> tuple[set[str], set[str], set[str]]:
    """Pure mathematical symmetric classification (PR4.11).

    Returns:
    - matched: expected intersect captured
    - erp_only: expected - captured
    - tower_only: captured - expected

    Invariant: Swapping expected and captured strictly swaps erp_only and tower_only.
    """
    matched = expected_serials.intersection(captured_serials)
    erp_only = expected_serials.difference(captured_serials)
    tower_only = captured_serials.difference(expected_serials)
    return matched, erp_only, tower_only


@dataclass(frozen=True)
class PositionCheck:
    """One expected unit at one position and what the technician captured there (M2 audit line)."""

    line_id: str
    expected_serial: str
    captured_serial: str | None  # None: not captured (missing / not reached)
    location_id: str | None = None


def classify_positions(
    checks: list[PositionCheck], site_installed: dict[str, str | None]
) -> list[tuple[str, str | None, str | None, str]]:
    """Classify every position of an audit (FR4.025): [(class, expected_serial, found_serial, line_id)].

    Per position with expected E and captured C:
    - C == E                                  -> matched
    - C != E, C installed elsewhere on site   -> misplaced (C belongs to another position), plus
                                                 erp_only for E unless E was captured elsewhere
    - C != E, C unknown to the installed base -> serial_mismatch (ERP has E here, the tower has C;
                                                 one finding, E is not also reported erp_only)
    - no capture                              -> erp_only
    An expected serial E that was not found at its own position but was captured at another position of
    this audit is reported once, as misplaced, by that other position (no erp_only double count).
    Symmetric: every expected unit and every captured unit appears in at least one finding, and
    in exactly one unless it is the misplaced-plus-missing pair above.
    """
    captured_anywhere = {c.captured_serial for c in checks if c.captured_serial}
    out: list[tuple[str, str | None, str | None, str]] = []
    for c in checks:
        e, cap = c.expected_serial, c.captured_serial
        if cap is None:
            if e not in captured_anywhere:
                out.append(("erp_only", e, None, c.line_id))
            continue
        if cap == e:
            out.append(("matched", e, cap, c.line_id))
            continue
        here = c.location_id
        if cap in site_installed and site_installed[cap] != here:
            out.append(("misplaced", e, cap, c.line_id))
            if e not in captured_anywhere:  # the unit ERP expects here was not found anywhere
                out.append(("erp_only", e, None, c.line_id))
        else:  # one finding covers both sides: ERP has E here, the tower has C
            out.append(("serial_mismatch", e, cap, c.line_id))
    return out


def run_audit_reconciliation(
    tenant_id: str,
    task_id: str,
    tower_location_id: str | None = None,
) -> dict[str, Any]:
    """Execute reconciliation for a task, persist audit findings, and return API4.06 summary."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant_id,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")
            out = reconcile_task(cur, tenant_id, task_id, tower_location_id)
        conn.commit()
    return out


def reconcile_task(
    cur: Any,
    tenant_id: str,
    task_id: str,
    tower_location_id: str | None = None,
) -> dict[str, Any]:
    """Reconcile on the caller's cursor and transaction (used by API4.06 and by finishing an M2 audit)."""
    # 1. Verify task status
    cur.execute(
        "SELECT id, site_id, status FROM field.task WHERE tenant_id = %s AND id = %s;",
        (tenant_id, task_id),
    )
    task_row = cur.fetchone()
    if not task_row:
        raise ValueError(f"FIELD-TASK-404: Task {task_id} not found")

    task_status = task_row[2]
    if task_status in ("completed", "signed_off"):
        raise ValueError("FIELD-AUD-409-SIGNED: task already signed off")

    site_id = task_row[1]

    # 2. Fetch expected task_lines
    query_lines = """
        SELECT
            tl.id,
            tl.expected_serial,
            tl.location_id,
            COALESCE(tl.status, 'pending') AS status,
            COALESCE(e.equipment_class, 'UNKNOWN') AS eq_class,
            COALESCE(tl.location_id, l.id) AS loc_id,
            tl.captured_serial,
            tl.reason_code
        FROM field.task_line tl
        LEFT JOIN field.location l ON tl.location_id = l.id
        LEFT JOIN field.equipment e ON e.serial_no = tl.expected_serial AND e.tenant_id = tl.tenant_id
        WHERE tl.tenant_id = %s AND tl.task_id = %s
    """
    params_lines: list[Any] = [tenant_id, task_id]
    if tower_location_id:
        query_lines += " AND (l.parent_id = %s OR l.id = %s)"
        params_lines.extend([tower_location_id, tower_location_id])

    cur.execute(query_lines, tuple(params_lines))
    task_lines_rows = cur.fetchall()

    expected_by_serial: dict[str, dict[str, Any]] = {}
    for r in task_lines_rows:
        s = r[1]
        if s:
            expected_by_serial[s] = {
                "task_line_id": r[0],
                "expected_serial": s,
                "location_id": r[2],
                "status": r[3],
                "equipment_class": r[4],
                "captured_serial": r[6],
                "reason_code": r[7],
            }

    # 3. Fetch captures on this task
    query_caps = """
        SELECT
            c.id,
            c.code_value,
            c.location_id,
            COALESCE(c.verify_status, 'verified') AS verify_status,
            COALESCE(c.parsed_data->>'equipment_class', 'UNKNOWN') AS object_class,
            c.created_at
        FROM field.capture c
        WHERE c.tenant_id = %s AND c.task_id = %s AND c.superseded_by IS NULL
    """
    cur.execute(query_caps, (tenant_id, task_id))
    captures_rows = cur.fetchall()

    captured_by_serial: dict[str, dict[str, Any]] = {}
    for r in captures_rows:
        s = r[1]
        if s:
            captured_by_serial[s] = {
                "capture_id": r[0],
                "serial_no": s,
                "location_id": r[2],
                "verify_status": r[3],
                "object_class": r[4],
                "created_at": r[5],
            }

    # 4. Fetch site-wide installed base to distinguish misplaced vs tower_only
    cur.execute(
        """
        SELECT e.serial_no, e.current_location_id
        FROM field.equipment e
        JOIN field.location l ON e.current_location_id = l.id
        WHERE e.tenant_id = %s AND l.site_id = %s AND e.status = 'installed';
        """,
        (tenant_id, site_id),
    )
    site_ib_map = {r[0]: r[1] for r in cur.fetchall()}

    # 5. Fetch manually marked missing findings (FR4.023)
    cur.execute(
        """
        SELECT expected_serial, reason, location_id
        FROM field.audit_finding
        WHERE tenant_id = %s AND task_id = %s AND class = 'erp_only' AND status <> 'resolved';
        """,
        (tenant_id, task_id),
    )
    marked_missing_map = {
        r[0]: {"reason": r[1], "location_id": r[2]} for r in cur.fetchall()
    }

    # 6. Classification
    matched_count = 0
    serial_mismatch_count = 0
    misplaced_count = 0
    tower_only_count = 0
    erp_only_count = 0

    findings_to_upsert: list[dict[str, Any]] = []

    # 6a. Position checks (M2 audit lines: the serial captured at each expected position).
    #     A line counts as checked once it has a captured serial or was marked missing.
    checks = [
        PositionCheck(str(v["task_line_id"]), s_, v["captured_serial"],
                      str(v["location_id"]) if v["location_id"] else None)
        for s_, v in expected_by_serial.items()
        if v["captured_serial"] or v["status"] in ("flagged", "done", "confirmed")
    ]
    position_serials = {c.expected_serial for c in checks}
    for cls, exp_s, found_s, line_id in classify_positions(checks, {k: (str(v) if v else None)
                                                                      for k, v in site_ib_map.items()}):
        item = expected_by_serial.get(exp_s or "") or {}
        loc = str(item["location_id"]) if item.get("location_id") else None
        reason = (marked_missing_map.get(exp_s or "", {}).get("reason") or item.get("reason_code") or "not_found"
                  if cls == "erp_only" else None)
        if reason is not None and reason not in ("not_found", "removed_by_other", "inaccessible"):
            reason = "not_found"
        key_serial = found_s if cls == "misplaced" else exp_s
        findings_to_upsert.append({
            "task_id": task_id, "site_id": site_id,
            "tower_location_id": tower_location_id or loc,
            "location_id": loc, "task_line_id": line_id, "capture_id": None, "class": cls,
            "expected_serial": exp_s, "found_serial": found_s, "reason": reason,
            "dedupe_key": f"{site_id}:{key_serial}:{cls}",
        })
        if cls == "matched":
            matched_count += 1
        elif cls == "serial_mismatch":
            serial_mismatch_count += 1
        elif cls == "misplaced":
            misplaced_count += 1
        else:
            erp_only_count += 1
        if found_s:
            captured_by_serial.pop(found_s, None)  # already classified by its position

    exp_set_all = set(expected_by_serial.keys())
    cap_set_all = set(captured_by_serial.keys()) | {c.captured_serial for c in checks if c.captured_serial}
    # 6b. Free captures (field.capture rows not tied to a position): the symmetric set rules.
    exp_set = exp_set_all - position_serials
    cap_set = set(captured_by_serial.keys())

    # Symmetric core
    common_serials, erp_only_serials, tower_only_serials = classify_sets_symmetric(
        exp_set, cap_set
    )

    # A. Process common serials: check location match vs misplaced
    for s in common_serials:
        exp_item = expected_by_serial[s]
        cap_item = captured_by_serial[s]

        exp_loc = str(exp_item["location_id"]) if exp_item["location_id"] else None
        cap_loc = str(cap_item["location_id"]) if cap_item["location_id"] else None

        # If locations differ, classify as misplaced; otherwise matched
        if exp_loc and cap_loc and exp_loc != cap_loc:
            misplaced_count += 1
            finding_class = "misplaced"
        else:
            matched_count += 1
            finding_class = "matched"

        findings_to_upsert.append(
            {
                "task_id": task_id,
                "site_id": site_id,
                "tower_location_id": tower_location_id or exp_loc or cap_loc or site_id,
                "location_id": cap_loc or exp_loc,
                "task_line_id": exp_item["task_line_id"],
                "capture_id": cap_item["capture_id"],
                "class": finding_class,
                "expected_serial": s,
                "found_serial": s,
                "reason": None,
                "dedupe_key": f"{site_id}:{s}:{finding_class}",
            }
        )

    # B. Process Tower-only serials: check if misplaced from another tower or completely unknown
    for s in tower_only_serials:
        cap_item = captured_by_serial[s]
        cap_loc = str(cap_item["location_id"]) if cap_item["location_id"] else None

        if s in site_ib_map:
            # Serial exists elsewhere on site -> misplaced!
            misplaced_count += 1
            finding_class = "misplaced"
        else:
            # Serial not found anywhere in site installed base -> tower_only!
            tower_only_count += 1
            finding_class = "tower_only"

        findings_to_upsert.append(
            {
                "task_id": task_id,
                "site_id": site_id,
                "tower_location_id": tower_location_id or cap_loc or site_id,
                "location_id": cap_loc,
                "task_line_id": None,
                "capture_id": cap_item["capture_id"],
                "class": finding_class,
                "expected_serial": None,
                "found_serial": s,
                "reason": None,
                "dedupe_key": f"{site_id}:{s}:{finding_class}",
            }
        )

    # C. Process ERP-only serials: missing from captures
    for s in erp_only_serials:
        exp_item = expected_by_serial[s]
        exp_loc = str(exp_item["location_id"]) if exp_item["location_id"] else None

        reason = marked_missing_map.get(s, {}).get("reason", "not_found")
        erp_only_count += 1

        findings_to_upsert.append(
            {
                "task_id": task_id,
                "site_id": site_id,
                "tower_location_id": tower_location_id or exp_loc or site_id,
                "location_id": exp_loc,
                "task_line_id": exp_item["task_line_id"],
                "capture_id": None,
                "class": "erp_only",
                "expected_serial": s,
                "found_serial": None,
                "reason": reason,
                "dedupe_key": f"{site_id}:{s}:erp_only",
            }
        )

    # 7. Persist findings to field.audit_finding
    for f in findings_to_upsert:
        finding_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO field.audit_finding (
                id, tenant_id, task_id, site_id, tower_location_id,
                location_id, task_line_id, capture_id, class,
                expected_serial, found_serial, reason, status, dedupe_key
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, 'open', %s
            )
            ON CONFLICT (tenant_id, dedupe_key) WHERE status <> 'resolved'
            DO UPDATE SET
                location_id = EXCLUDED.location_id,
                capture_id = EXCLUDED.capture_id,
                found_serial = EXCLUDED.found_serial,
                reason = EXCLUDED.reason,
                updated_at = NOW();
            """,
            (
                finding_id,
                tenant_id,
                f["task_id"],
                f["site_id"],
                f["tower_location_id"],
                f["location_id"],
                f["task_line_id"],
                f["capture_id"],
                f["class"],
                f["expected_serial"],
                f["found_serial"],
                f["reason"],
                f["dedupe_key"],
            ),
        )

    # 8. Compute completeness ratio
    completeness, _ = calculate_completeness(exp_set_all, cap_set_all)

    logger.info(
        "reconciliation_completed",
        task_id=task_id,
        matched=matched_count,
        serial_mismatch=serial_mismatch_count,
        tower_only=tower_only_count,
        erp_only=erp_only_count,
        misplaced=misplaced_count,
        completeness=round(completeness, 3),
    )

    return {
        "matched": matched_count,
        "serial_mismatch": serial_mismatch_count,
        "tower_only": tower_only_count,
        "erp_only": erp_only_count,
        "misplaced": misplaced_count,
        "completeness": round(completeness, 3),
    }
