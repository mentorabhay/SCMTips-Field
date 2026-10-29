"""Recount Rule and Different Operator Enforcement (Task T3.040 / FR3.031 / PR3.04 / TC3.125).

Invariant PR3.04:
For all recount tasks, recount_counter != initial_counter,
and the recount task cannot be started or submitted by the initial counter.
"""

from typing import Any


class RecountException(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def validate_recount_assignment(
    initial_counter_id: str,
    recount_counter_id: str,
) -> bool:
    """Enforces PR3.04: Recount operator must be strictly distinct from the initial counter."""
    clean_initial = initial_counter_id.strip().lower()
    clean_recount = recount_counter_id.strip().lower()

    if clean_initial == clean_recount:
        raise RecountException(
            code="FIELD-PI-422-RECOUNT-SAME-OPERATOR",
            message=f"Operator '{recount_counter_id}' conducted the initial count. Recount MUST be performed by a different operator (PR3.04).",
            status_code=422,
        )

    return True


def initiate_recount(
    pi_line: dict[str, Any],
    initial_count: float,
    book_qty: float,
    threshold_qty: float = 0.0,
) -> dict[str, Any]:
    """Evaluates whether discrepancy requires recount, and sets recount status."""
    discrepancy = abs(initial_count - book_qty)
    needs_recount = discrepancy > threshold_qty

    return {
        "line_id": pi_line.get("line_id") or pi_line.get("id"),
        "needs_recount": needs_recount,
        "initial_counted_qty": initial_count,
        "initial_counter_id": pi_line.get("initial_counter_id") or pi_line.get("counter_id"),
        "status": "recount" if needs_recount else "ready_for_post",
    }
