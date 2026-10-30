"""Over- and Under-Delivery Tolerance Evaluation (Task T3.020 / FR3.007 / FR3.008 / PR3.14 / TC3.106 / TC3.107).

Rules:
1. Over-delivery:
   - If counted_qty > expected_qty * (1 + over_tolerance_pct / 100):
     Block confirmation and open an exception case (supervisor decision required).
   - Supervisor may approve capped receipt (e.g. up to tolerance) and reject excess.
2. Under-delivery:
   - If counted_qty < expected_qty:
     Require a valid reason code (e.g. 'Later delivery', 'Short shipment').
     Confirm proceeds with GR qty = counted_qty, and records remaining as late-receipt candidate.
"""

from dataclasses import dataclass

from field_api.errors import FieldError

ERR_OVER_DELIVERY_BLOCKED = FieldError(
    status=422,
    code="FIELD-RCV-422-OVER-DELIVERY",
    title="Over-Delivery Exceeds Tolerance",
    detail="Counted quantity exceeds expected quantity plus allowed over-delivery tolerance. Supervisor decision required.",
)

ERR_UNDER_DELIVERY_REASON_REQUIRED = FieldError(
    status=422,
    code="FIELD-RCV-422-REASON-REQUIRED",
    title="Reason Code Required for Under-Delivery",
    detail="Counted quantity is less than expected. A valid under-delivery reason code must be specified.",
)

VALID_UNDER_DELIVERY_REASONS = frozenset({
    "Later delivery",
    "Short shipment",
    "Damaged in transit",
    "Supplier stockout",
    "Partial container",
    "Other",
})


@dataclass
class ToleranceDecision:
    is_blocked: bool
    status: str  # 'OK', 'OVER_DELIVERY_BLOCKED', 'UNDER_DELIVERY_NEEDS_REASON', 'UNDER_DELIVERY_ACCEPTED'
    approved_gr_qty: float
    rejected_qty: float
    late_receipt_qty: float
    reason_code: str | None
    exception_case_opened: bool


def evaluate_receipt_tolerance(
    expected_qty: float,
    counted_qty: float,
    over_tolerance_pct: float = 0.0,
    under_tolerance_pct: float = 0.0,
    reason_code: str | None = None,
    supervisor_approved_qty: float | None = None,
) -> ToleranceDecision:
    """Evaluate counted receipt quantity against cached PO tolerances.

    Complies with PR3.14 and TC3.106 / TC3.107.
    """
    max_allowed = round(expected_qty * (1.0 + over_tolerance_pct / 100.0), 3)

    # 1. Over-delivery scenario
    if counted_qty > max_allowed:
        if supervisor_approved_qty is not None:
            # Supervisor decision applied
            capped_qty = min(supervisor_approved_qty, max_allowed)
            rejected = max(0.0, counted_qty - capped_qty)
            return ToleranceDecision(
                is_blocked=False,
                status="OVER_DELIVERY_RESOLVED",
                approved_gr_qty=capped_qty,
                rejected_qty=rejected,
                late_receipt_qty=0.0,
                reason_code=reason_code or "Supervisor override",
                exception_case_opened=True,
            )
        else:
            # Must block and open exception case
            return ToleranceDecision(
                is_blocked=True,
                status="OVER_DELIVERY_BLOCKED",
                approved_gr_qty=0.0,
                rejected_qty=0.0,
                late_receipt_qty=0.0,
                reason_code=None,
                exception_case_opened=True,
            )

    # 2. Under-delivery scenario
    if counted_qty < expected_qty:
        if not reason_code or reason_code not in VALID_UNDER_DELIVERY_REASONS:
            return ToleranceDecision(
                is_blocked=True,
                status="UNDER_DELIVERY_NEEDS_REASON",
                approved_gr_qty=0.0,
                rejected_qty=0.0,
                late_receipt_qty=expected_qty - counted_qty,
                reason_code=None,
                exception_case_opened=False,
            )
        else:
            # Under-delivery accepted with reason code
            return ToleranceDecision(
                is_blocked=False,
                status="UNDER_DELIVERY_ACCEPTED",
                approved_gr_qty=counted_qty,
                rejected_qty=0.0,
                late_receipt_qty=expected_qty - counted_qty,
                reason_code=reason_code,
                exception_case_opened=False,
            )

    # 3. Exactly expected or within allowable over-tolerance
    return ToleranceDecision(
        is_blocked=False,
        status="OK",
        approved_gr_qty=counted_qty,
        rejected_qty=0.0,
        late_receipt_qty=0.0,
        reason_code=reason_code,
        exception_case_opened=False,
    )
