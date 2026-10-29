"""Import Validation & Topology Verification (Task T4.008 / FR4.007 / TC4.104).

Detects orphan locations, hierarchy cycles, and format violations using a topological pass.
Blocks apply when rejected rows exceed 20% of the total batch unless step-up approved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from field_api.sites.fl_mask import validate_fl_code


@dataclass
class ValidationSummary:
    total: int
    valid_count: int
    rejected_count: int
    rejection_pct: float
    blocked: bool
    valid_rows: list[dict[str, Any]] = field(default_factory=list)
    rejected_rows: list[dict[str, Any]] = field(default_factory=list)


def validate_import_staging_rows(
    rows: list[dict[str, Any]],
    known_parent_codes: set[str] | None = None,
    allow_step_up: bool = False,
) -> ValidationSummary:
    """Perform topological validation on staged functional location rows.

    Checks:
    1. Mask compliance (FIELD-FL-422-MASK)
    2. Cycle detection (FIELD-LOC-422-CYCLE)
    3. Orphan detection (FIELD-LOC-422-ORPHAN)

    Rejection of > 20% blocks apply unless allow_step_up=True.
    """
    total = len(rows)
    if total == 0:
        return ValidationSummary(
            total=0,
            valid_count=0,
            rejected_count=0,
            rejection_pct=0.0,
            blocked=False,
            valid_rows=[],
            rejected_rows=[],
        )

    known_parents = set(known_parent_codes or [])
    # Add all codes present in the batch to the potential parent set
    all_batch_codes = {r["fl_code"] for r in rows if r.get("fl_code")}

    # Build parent graph
    parent_map: dict[str, str | None] = {}
    for r in rows:
        code = r.get("fl_code")
        parent = r.get("parent_fl_code")
        if code:
            parent_map[code] = parent

    valid_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []

    for r in rows:
        code = r.get("fl_code")
        parent = r.get("parent_fl_code")

        # 1. Mask validation
        if not code:
            rejected_rows.append({
                "fl_code": "",
                "reason": "Missing functional location code",
                "error_type": "FIELD-FL-422-EMPTY",
                "row": r,
            })
            continue

        mask_res = validate_fl_code(code)
        if not mask_res.is_valid:
            rejected_rows.append({
                "fl_code": code,
                "reason": f"Mask validation failed on segment '{mask_res.error_segment}': {mask_res.error_reason}",
                "error_type": "FIELD-FL-422-MASK",
                "row": r,
            })
            continue

        # 2. Cycle detection via traversal
        has_cycle = False
        visited = set()
        curr = parent
        while curr:
            if curr == code:
                has_cycle = True
                break
            if curr in visited:
                has_cycle = True
                break
            visited.add(curr)
            curr = parent_map.get(curr)

        if has_cycle:
            rejected_rows.append({
                "fl_code": code,
                "reason": f"Hierarchy cycle detected involving parent '{parent}'",
                "error_type": "FIELD-LOC-422-CYCLE",
                "row": r,
            })
            continue

        # 3. Orphan detection
        # If parent is specified, it must either be in the batch or in known DB parents
        if parent and parent not in all_batch_codes and parent not in known_parents:
            rejected_rows.append({
                "fl_code": code,
                "reason": f"Parent location '{parent}' does not exist in batch or database",
                "error_type": "FIELD-LOC-422-ORPHAN",
                "row": r,
            })
            continue

        # Row is valid
        enriched_row = dict(r)
        enriched_row["kind"] = mask_res.kind
        enriched_row["depth"] = mask_res.depth
        enriched_row["sector_code"] = mask_res.sector_code
        enriched_row["short_code"] = mask_res.short_code
        valid_rows.append(enriched_row)

    rejected_count = len(rejected_rows)
    valid_count = len(valid_rows)
    rejection_pct = round((rejected_count / total) * 100.0, 2)

    # Block apply if rejection percentage > 20% without step-up
    blocked = (rejection_pct > 20.0) and not allow_step_up

    return ValidationSummary(
        total=total,
        valid_count=valid_count,
        rejected_count=rejected_count,
        rejection_pct=rejection_pct,
        blocked=blocked,
        valid_rows=valid_rows,
        rejected_rows=rejected_rows,
    )
