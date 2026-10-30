"""Blind count of a count task line (contract §3 POST /v1/count-records; FR3.029 - FR3.035).

A count task is the operator face of a field PI document (field.pi_document, created by API3.10 or
by a recount). The book snapshot sits in field.pi_book and never leaves the server. Recounts are new
documents (``count_round`` 2 and 3, SAP MI11 style) carrying the frozen book of the first one.

- round 2 and 3 must be counted by someone who did not count an earlier round (FR3.032);
- round 3 must be counted by an inventory controller (field.pi.post, FR3.033); at most 3 rounds.
- tolerance (FR3.031): |diff| / book > FIELD_PI_RECOUNT_PCT % or |diff value| > FIELD_PI_RECOUNT_VALUE.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from field_api.auth.jwt import Principal
from field_api.auth.permissions import has_permission
from field_api.errors import FieldError
from field_api.pi.api import APPROVAL_VALUE, MAX_COUNTS, recount_needed


def pi_of_line(cur: Any, line_id: str) -> tuple[str, int, str | None]:
    """(pi_document id, count_round, recount_of) of a count task line."""
    cur.execute(
        "SELECT d.id, d.count_round, d.recount_of, d.status FROM field.pi_book b"
        " JOIN field.pi_document d ON d.id = b.pi_document_id WHERE b.task_line_id = %s::uuid",
        (line_id,),
    )
    row = cur.fetchone()
    if not row:
        raise FieldError(status=409, code="FIELD-TASK-409-STATE", title="This count has no inventory document")
    if row[3] in ("posted", "cancelled"):
        raise FieldError(status=409, code="FIELD-PI-409-STATE", title=f"This count is already {row[3]}")
    return str(row[0]), int(row[1]), str(row[2]) if row[2] else None


def earlier_counters(cur: Any, pi_id: str) -> set[str]:
    """Everyone who counted an earlier round of this document chain."""
    cur.execute(
        """
        WITH RECURSIVE chain(id, recount_of) AS (
            SELECT id, recount_of FROM field.pi_document WHERE id = %s::uuid
            UNION ALL
            SELECT d.id, d.recount_of FROM field.pi_document d JOIN chain c ON d.id = c.recount_of
        )
        SELECT DISTINCT cr.counted_by FROM field.count_record cr
          JOIN chain c ON cr.pi_doc_id = c.id::text
         WHERE c.id <> %s::uuid AND cr.counted_by IS NOT NULL
        """,
        (pi_id, pi_id),
    )
    return {str(r[0]) for r in cur.fetchall()}


def record_blind_count(
    cur: Any, principal: Principal, task_id: str, line_id: str, qty: Decimal, uom: str, source: str,
    voice_event_id: str | None,
) -> int:
    """Store one blind count; returns the line version. Re-counting the same line before posting replaces it."""
    pi_id, count_round, _ = pi_of_line(cur, line_id)
    if count_round > MAX_COUNTS:
        raise FieldError(status=409, code="FIELD-PI-409-MAX-COUNTS", title=f"At most {MAX_COUNTS} counts per item")
    if count_round > 1 and principal.id in earlier_counters(cur, pi_id):
        raise FieldError(status=409, code="FIELD-PI-409-RECOUNT-SAME-OPERATOR",
                         title="Someone else must do this recount",
                         detail="A recount must be counted by a different operator (FR3.032).")
    if count_round == MAX_COUNTS and not has_permission(principal.permissions, "field.pi.post"):
        raise FieldError(status=409, code="FIELD-PI-409-NOT-ASSIGNED",
                         title="The third count is for an inventory controller")
    cur.execute(
        "UPDATE field.task_line SET counted_qty = %s, status = 'counted', version = version + 1, updated_at = NOW()"
        " WHERE id = %s::uuid RETURNING version",
        (qty, line_id),
    )
    row = cur.fetchone()
    cur.execute(
        """
        INSERT INTO field.count_record (tenant_id, task_id, task_line_id, voice_event_id, quantity, unit, pi_doc_id,
               counted_by, count_no, recount_round, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (principal.tenant_id, task_id, line_id, voice_event_id, qty, uom, pi_id, principal.id, count_round,
         count_round, source),
    )
    cur.execute("UPDATE field.task SET status = 'in_progress', updated_at = NOW() WHERE id = %s::uuid"
                " AND status = 'pending'", (task_id,))
    return int(row[0]) if row else 0


def count_outcome(cur: Any, pi_id: str) -> tuple[bool, Decimal, str]:
    """(beyond_tolerance, absolute difference value, currency) of a counted document.

    Beyond tolerance when any item breaks FR3.031 or the document value exceeds FIELD_PI_APPROVAL_VALUE
    (FR3.034). Contract §4: beyond tolerance -> an approval request for the console, no posting.
    """
    cur.execute(
        "SELECT l.counted_qty, b.book_qty, b.unit_price, b.currency FROM field.pi_book b"
        " JOIN field.task_line l ON l.id = b.task_line_id WHERE b.pi_document_id = %s::uuid",
        (pi_id,),
    )
    rows = cur.fetchall()
    value = sum((abs(Decimal(r[0]) - Decimal(r[1])) * Decimal(r[2]) for r in rows), Decimal(0))
    beyond = any(recount_needed(Decimal(r[1]), Decimal(r[0]), Decimal(r[2])) for r in rows) or value > APPROVAL_VALUE
    return beyond, value, (rows[0][3] if rows else "INR")
