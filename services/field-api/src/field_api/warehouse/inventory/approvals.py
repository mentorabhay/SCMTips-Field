"""Variance Approvals Engine (Task T3.041 / FR3.032 / PR3.05 / TC3.126).

Invariant PR3.05:
For all physical inventory lines with difference_value > threshold (SAMPLE $1,000 / €1,000),
PostDifferences is blocked until an approval_request exists with status 'approved'
and decided_by != counter.
"""

from typing import Any

DEFAULT_VARIANCE_APPROVAL_THRESHOLD = 1000.00  # $1,000 / €1,000 threshold


class ApprovalException(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def evaluate_variance_approval_requirement(
    diff_qty: float,
    unit_price: float,
    threshold: float = DEFAULT_VARIANCE_APPROVAL_THRESHOLD,
) -> tuple[bool, float]:
    """Calculates difference value and determines if manager approval is required."""
    variance_val = abs(diff_qty) * unit_price
    needs_approval = variance_val > threshold
    return needs_approval, variance_val


def validate_approval_state_for_posting(
    variance_val: float,
    approval_record: dict[str, Any] | None,
    counter_id: str,
    threshold: float = DEFAULT_VARIANCE_APPROVAL_THRESHOLD,
) -> bool:
    """Enforces PR3.05 before allowing 701/702 difference posting."""
    if variance_val <= threshold:
        return True  # Within automatic threshold

    if not approval_record:
        raise ApprovalException(
            code="FIELD-PI-422-APPROVAL-REQUIRED",
            message=f"Variance value {variance_val:.2f} exceeds approval threshold {threshold:.2f}. Supervisor approval request required (PR3.05).",
            status_code=422,
        )

    if approval_record.get("status") != "approved":
        raise ApprovalException(
            code="FIELD-PI-422-APPROVAL-PENDING",
            message=f"Approval status is '{approval_record.get('status')}'. Difference posting is blocked until approved.",
            status_code=422,
        )

    approver = (
        (approval_record.get("approved_by") or approval_record.get("decided_by") or "")
        .strip()
        .lower()
    )
    counter = counter_id.strip().lower()

    if approver == counter:
        raise ApprovalException(
            code="FIELD-PI-422-SELF-APPROVAL-FORBIDDEN",
            message=f"Counter '{counter_id}' cannot approve their own inventory variance (PR3.05).",
            status_code=422,
        )

    return True
