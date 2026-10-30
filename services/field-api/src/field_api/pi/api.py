"""Physical inventory at the spec contract, on Postgres with RLS (C3 P0 fix + C4).

API3.10  POST /v1/pi-documents                              planner request; book snapshot server-side
API3.11  POST /v1/pi-documents/{id}/items/{item}/counts     blind count; recount by a different operator
API3.12  POST /v1/pi-documents/{id}/post-differences         value server-side; approval above threshold
interim  POST /v1/approval-requests/{id}/decide              SoD: approver is neither requester nor counter

Replaces /v1/warehouse/inventory/differences/post, which took book_qty, unit_price, counter_id and
an "approved" record from the client, so any supervisor could post a write-off of any size
(review §3.11). Here book quantity and price never leave the server (FR3.029) and approval is a
server-side record decided by an eligible, different principal (FR3.034).

Interim notes (honest gaps): (1) the book snapshot is supplied at creation by a principal holding
field.pi.book (inventory controller) until an ERP stock read exists on ErpPort; (2) core approval
bands and step-up re-authentication are the CS seam (P14); band is computed here from value.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.auth.permissions import has_permission
from field_api.db import principal_tx
from field_api.deps import require_permission
from field_api.errors import FieldError
from field_api.posting.staging import JobSpec, stage_document

router = APIRouter(tags=["Physical inventory (API3.10-3.12)"])

RECOUNT_PCT = Decimal(os.getenv("FIELD_PI_RECOUNT_PCT", "2.0"))
RECOUNT_VALUE = Decimal(os.getenv("FIELD_PI_RECOUNT_VALUE", "25000"))
APPROVAL_VALUE = Decimal(os.getenv("FIELD_PI_APPROVAL_VALUE", "50000"))
MAX_ITEMS = int(os.getenv("FIELD_PI_MAX_ITEMS", "50"))
MAX_COUNTS = 3
BAND_B3_FROM = Decimal(os.getenv("FIELD_PI_BAND_B3_FROM", "500000"))
DEFAULT_UNIT_PRICE = Decimal(os.getenv("FIELD_PI_DEFAULT_UNIT_PRICE", "0"))


def _err(status: int, code: str, title: str, detail: str | None = None) -> FieldError:
    return FieldError(code=code, status=status, title=title, detail=detail)


def recount_needed(book: Decimal, counted: Decimal, price: Decimal) -> bool:
    """FR3.031: |diff|/book > FIELD_PI_RECOUNT_PCT % or |diff value| > FIELD_PI_RECOUNT_VALUE."""
    diff = abs(counted - book)
    if diff == 0:
        return False
    pct_hit = book == 0 or (diff / book) * 100 > RECOUNT_PCT
    return pct_hit or diff * price > RECOUNT_VALUE


def recount_accepted(previous: Decimal, current: Decimal) -> bool:
    """FR3.033: accept a recount within max(1 base unit, 0.5 %) of the previous count."""
    return abs(current - previous) <= max(Decimal(1), abs(previous) * Decimal("0.005"))


def count_title(bins: set[str], recount: bool = False) -> str:
    word = "Recount" if recount else "Count"
    return f"{word} bin {next(iter(bins))}" if len(bins) == 1 else f"{word} {len(bins)} bins"


def band_for(value_abs: Decimal) -> str:
    if value_abs <= APPROVAL_VALUE:
        return "B1"
    return "B2" if value_abs <= BAND_B3_FROM else "B3"


# --------------------------------------------------------------------------- API3.10
class PiItemIn(BaseModel):
    """One bin/material to count. Without ``book_qty`` the server snapshots the field bin stock
    (field.bin_stock), so the book never passes through a client; ``unit_price`` defaults to
    FIELD_PI_DEFAULT_UNIT_PRICE (no price source on ErpPort yet)."""

    bin: str = Field(min_length=1)
    material: str = Field(min_length=1)
    uom: str = "EA"
    book_qty: Decimal | None = Field(default=None, ge=0)
    unit_price: Decimal | None = Field(default=None, ge=0)


class PiCreateIn(BaseModel):
    site_id: str
    plant: str
    storage_location: str
    planned_count_date: date | None = None
    freeze: bool = True
    posting_block: bool = True
    currency: str = "INR"
    items: list[PiItemIn] = Field(min_length=1)


@router.post("/v1/pi-documents", status_code=201)
def create_pi_document(
    body: PiCreateIn,
    principal: Principal = Depends(require_permission("field.pi.create")),
) -> dict[str, Any]:
    if any(it.book_qty is not None for it in body.items) and not has_permission(principal.permissions, "field.pi.book"):
        raise _err(403, "FIELD-AUTH-403-PERMISSION", "Book snapshot requires field.pi.book")
    if "*" not in principal.site_ids and body.site_id not in principal.site_ids:
        raise _err(403, "FIELD-AUTH-403-SCOPE", "Site not in scope")
    if len(body.items) > MAX_ITEMS:
        raise _err(422, "FIELD-PI-422-TOO-MANY-ITEMS", f"At most {MAX_ITEMS} items per document")
    with principal_tx(principal) as cur:
        doc_number = f"PID-{datetime.now(UTC):%Y%m%d%H%M%S%f}"
        year = str((body.planned_count_date or date.today()).year)
        cur.execute(
            """
            INSERT INTO field.task (tenant_id, site_id, type, status, priority, title, ref_doc_no, subtitle)
            VALUES (%s, %s, 'count', 'pending', 'normal', %s, %s, %s) RETURNING id
            """,
            (principal.tenant_id, body.site_id, count_title({it.bin for it in body.items}), doc_number,
             f"PI {doc_number}"),
        )
        task_id = str(cur.fetchone()[0])
        cur.execute(
            """
            INSERT INTO field.pi_document (tenant_id, doc_number, fiscal_year, plant, storage_location,
                   posting_blocked, freeze_book, status, site_id, task_id, planned_count_date, requested_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', %s, %s, %s, %s) RETURNING id
            """,
            (principal.tenant_id, doc_number, year, body.plant, body.storage_location, body.posting_block,
             body.freeze, body.site_id, task_id, body.planned_count_date, principal.id),
        )
        pi_id = str(cur.fetchone()[0])
        for n, it in enumerate(body.items, start=1):
            cur.execute("SELECT id FROM field.material WHERE erp_material_no = %s LIMIT 1", (it.material,))
            mrow = cur.fetchone()
            cur.execute(
                """
                INSERT INTO field.task_line (tenant_id, site_id, task_id, line_no, material_id, expected_qty,
                       uom, storage_bin, status)
                VALUES (%s, %s, %s, %s, %s, 0, %s, %s, 'pending') RETURNING id
                """,
                (principal.tenant_id, body.site_id, task_id, n, mrow[0] if mrow else None, it.uom, it.bin),
            )
            line_id = str(cur.fetchone()[0])
            book = it.book_qty
            if book is None:
                cur.execute("SELECT COALESCE(SUM(quantity), 0) FROM field.bin_stock WHERE site_id = %s"
                            " AND storage_bin = %s AND material_no = %s", (body.site_id, it.bin, it.material))
                book = Decimal(cur.fetchone()[0])
            cur.execute(
                "INSERT INTO field.pi_book (tenant_id, pi_document_id, task_line_id, book_qty, unit_price, currency)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (principal.tenant_id, pi_id, line_id, book,
                 it.unit_price if it.unit_price is not None else DEFAULT_UNIT_PRICE, body.currency),
            )
    return {"id": pi_id, "doc_number": doc_number, "task_id": task_id, "status": "open",
            "items": len(body.items), "queue_key": "PID:pending"}


# --------------------------------------------------------------------------- API3.11
class PiCountIn(BaseModel):
    qty: Decimal = Field(ge=0)
    is_zero: bool = False
    source: Literal["voice", "scan", "manual", "mixed"] = "mixed"
    capture_ids: list[str] = []


@router.post("/v1/pi-documents/{pi_id}/items/{item}/counts")
def commit_count(
    pi_id: str,
    item: str,
    body: PiCountIn,
    principal: Principal = Depends(require_permission("field.capture.create")),
) -> dict[str, Any]:
    if body.is_zero and body.qty != 0:
        raise _err(422, "FIELD-HTTP-422-VALIDATION", "is_zero requires qty 0")
    with principal_tx(principal) as cur:
        cur.execute("SELECT status, task_id FROM field.pi_document WHERE id = %s::uuid FOR UPDATE", (pi_id,))
        doc = cur.fetchone()
        if not doc:
            raise _err(404, "FIELD-HTTP-404-NOT-FOUND", "PI document not found")
        if doc[0] in ("posted", "cancelled"):
            raise _err(409, "FIELD-PI-409-STATE", f"Document is {doc[0]}")
        key_col = "l.id::text" if re.fullmatch(r"[0-9a-fA-F-]{36}", item) else "l.line_no::text"
        cur.execute(
            f"""
            SELECT l.id, l.status, b.book_qty, b.unit_price
              FROM field.task_line l JOIN field.pi_book b ON b.task_line_id = l.id
             WHERE b.pi_document_id = %s::uuid AND {key_col} = %s
             FOR UPDATE OF l
            """,  # noqa: S608 - key column picked from two fixed expressions
            (pi_id, item),
        )
        row = cur.fetchone()
        if not row:
            raise _err(404, "FIELD-HTTP-404-NOT-FOUND", "PI item not found")
        line_id, line_status, book, price = row
        cur.execute(
            "SELECT counted_by, quantity, count_no FROM field.count_record"
            " WHERE task_line_id = %s AND pi_doc_id = %s ORDER BY count_no",
            (line_id, pi_id),
        )
        prior = cur.fetchall()
        count_no = len(prior) + 1
        if prior and line_status != "recount":
            raise _err(409, "FIELD-PI-409-NOT-ASSIGNED", "Item is counted; no recount required")
        if count_no > MAX_COUNTS:
            raise _err(409, "FIELD-PI-409-MAX-COUNTS", f"At most {MAX_COUNTS} counts per item")
        if principal.id in {p[0] for p in prior}:
            raise _err(409, "FIELD-PI-409-RECOUNT-SAME-OPERATOR", "Recount must be by a different operator")
        if count_no == MAX_COUNTS and not has_permission(principal.permissions, "field.pi.post"):
            raise _err(409, "FIELD-PI-409-NOT-ASSIGNED", "Third count must be by an inventory controller")
        cur.execute(
            """
            INSERT INTO field.count_record (tenant_id, task_id, task_line_id, quantity, unit, pi_doc_id,
                   counted_by, count_no, source)
            VALUES (%s, %s, %s, %s, 'EA', %s, %s, %s, %s)
            """,
            (principal.tenant_id, doc[1], line_id, body.qty, pi_id, principal.id, count_no, body.source),
        )
        if count_no == 1:
            new_status = "recount" if recount_needed(Decimal(book), body.qty, Decimal(price)) else "counted"
        elif count_no == 2:
            new_status = "counted" if recount_accepted(Decimal(prior[-1][1]), body.qty) else "recount"
        else:
            new_status = "counted"  # controller's third count is final
        cur.execute(
            "UPDATE field.task_line SET status = %s, counted_qty = %s, version = version + 1, updated_at = NOW()"
            " WHERE id = %s",
            (new_status, body.qty, line_id),
        )
        cur.execute(
            """
            UPDATE field.pi_document SET status = CASE
                 WHEN EXISTS (SELECT 1 FROM field.pi_book b JOIN field.task_line l ON l.id = b.task_line_id
                               WHERE b.pi_document_id = %s::uuid AND l.status = 'recount') THEN 'recount'
                 WHEN NOT EXISTS (SELECT 1 FROM field.pi_book b JOIN field.task_line l ON l.id = b.task_line_id
                               WHERE b.pi_document_id = %s::uuid AND l.status = 'pending') THEN 'counted'
                 ELSE 'open' END
             WHERE id = %s::uuid
            """,
            (pi_id, pi_id, pi_id),
        )
    # Never book_qty, difference or recount reason (FR3.029): only that a recount exists.
    return {"item": item, "count_no": count_no, "status": "committed"}


# --------------------------------------------------------------------------- API3.12
def stage_pi_posting(cur: Any, principal_tenant: str, pi_id: str, idem: str, approver: str | None,
                     device_id: str | None = None) -> str:
    """Stage the PI difference posting (create -> counts -> 701/702) as one job in queue PID:<doc>.

    ``device_id`` (the phone that finished the count) receives the erp.posted / erp.failed event.
    """
    cur.execute(
        "SELECT site_id, plant, doc_number, fiscal_year, task_id, storage_location"
        " FROM field.pi_document WHERE id = %s::uuid",
        (pi_id,),
    )
    site_id, plant, doc_no, year, task_id, sloc = cur.fetchone()
    cur.execute(
        """
        SELECT l.id, l.line_no, m.erp_material_no, l.storage_bin, l.counted_qty, b.book_qty, l.uom
          FROM field.pi_book b JOIN field.task_line l ON l.id = b.task_line_id
          LEFT JOIN field.material m ON m.id = l.material_id
         WHERE b.pi_document_id = %s::uuid ORDER BY l.line_no
        """,
        (pi_id,),
    )
    rows = cur.fetchall()
    items = [
        {"PhysicalInventoryDocumentItem": str(r[1]).zfill(3), "Material": r[2], "StorageBin": r[3],
         "QuantityInUnitOfEntry": f"{Decimal(r[4]):.3f}", "BookQuantity": f"{Decimal(r[5]):.3f}", "UnitOfEntry": r[6],
         "MovementType": "701" if Decimal(r[4]) > Decimal(r[5]) else "702"}
        for r in rows  # SAP needs every item counted, not only the ones with a difference
    ]
    staged = stage_document(
        cur, tenant_id=principal_tenant, site_id=str(site_id), doc_type="PI_DIFF", movement_type="701/702",
        queue_key=f"PID:{doc_no}", ref_doc_no=doc_no, plant=plant, idempotency_key=idem,
        payload={"task_id": str(task_id), "line_ids": [str(r[0]) for r in rows], "pi_document_id": pi_id,
                 "approved_by": approver, "line_status_after": "posted", "device_id": device_id},
        jobs=[JobSpec("PhysicalInventory", {"FieldPiDocument": doc_no, "FiscalYear": year,
                                            "StorageLocation": sloc}, tuple(items))],
    )
    cur.execute("UPDATE field.pi_document SET status = 'counted' WHERE id = %s::uuid", (pi_id,))
    cur.execute("UPDATE field.task_line SET status = 'posting', version = version + 1, updated_at = NOW()"
                " WHERE id = ANY(%s::uuid[])", ([str(r[0]) for r in rows],))
    cur.execute("UPDATE field.task SET status = 'posting', version = version + 1, updated_at = NOW()"
                " WHERE id = %s::uuid", (str(task_id),))
    return staged.erp_document_id


@router.post("/v1/pi-documents/{pi_id}/post-differences")
def post_differences(
    pi_id: str,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(require_permission("field.pi.post")),
) -> dict[str, Any]:
    with principal_tx(principal) as cur:
        cur.execute("SELECT status, task_id, requested_by FROM field.pi_document WHERE id = %s::uuid FOR UPDATE",
                    (pi_id,))
        doc = cur.fetchone()
        if not doc:
            raise _err(404, "FIELD-HTTP-404-NOT-FOUND", "PI document not found")
        if doc[0] in ("posted", "cancelled"):
            raise _err(409, "FIELD-PI-409-STATE", f"Document is {doc[0]}")
        cur.execute("SELECT 1 FROM field.erp_document WHERE payload->>'pi_document_id' = %s", (pi_id,))
        if cur.fetchone():
            raise _err(409, "FIELD-PI-409-STATE", "Differences already requested")
        cur.execute(
            """
            SELECT l.status, l.counted_qty, b.book_qty, b.unit_price, b.currency
              FROM field.pi_book b JOIN field.task_line l ON l.id = b.task_line_id
             WHERE b.pi_document_id = %s::uuid
            """,
            (pi_id,),
        )
        lines = cur.fetchall()
        if any(r[0] in ("pending", "recount") for r in lines):
            raise _err(409, "FIELD-PI-409-OPEN-RECOUNTS", "Uncounted items or open recounts remain")
        value_abs = sum((abs(Decimal(r[1]) - Decimal(r[2])) * Decimal(r[3]) for r in lines), Decimal(0))
        currency = lines[0][4] if lines else "INR"
        cur.execute("SELECT DISTINCT counted_by FROM field.count_record WHERE pi_doc_id = %s", (pi_id,))
        counters = sorted({r[0] for r in cur.fetchall() if r[0]})
        if value_abs > APPROVAL_VALUE:
            cur.execute(
                """
                INSERT INTO field.approval_request (tenant_id, task_id, approval_type, threshold_val, status,
                       requested_by, pi_document_id, value_abs, currency, band, excluded_principals)
                VALUES (%s, %s, 'pi_variance', %s, 'pending', %s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (principal.tenant_id, doc[1], APPROVAL_VALUE, principal.id, pi_id, value_abs, currency,
                 band_for(value_abs), sorted({principal.id, *counters})),
            )
            apr = str(cur.fetchone()[0])
            return {"status": "awaiting_approval", "approval_request_id": apr, "band": band_for(value_abs),
                    "value_abs": f"{value_abs:.2f}", "currency": currency}
        erp_doc = stage_pi_posting(cur, principal.tenant_id, pi_id, idempotency_key, None)
    return {"status": "queued", "erp_document_id": erp_doc, "band": "B1", "value_abs": f"{value_abs:.2f}",
            "currency": currency}


# --------------------------------------------------------------------------- approvals (interim seam)
class DecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=1)


@router.post("/v1/approval-requests/{apr_id}/decide")
def decide(
    apr_id: str,
    body: DecisionIn,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(require_permission("field.discrepancy.approve")),
) -> dict[str, Any]:
    with principal_tx(principal) as cur:
        cur.execute(
            "SELECT status, approval_type, requested_by, excluded_principals, pi_document_id"
            " FROM field.approval_request WHERE id = %s::uuid FOR UPDATE",
            (apr_id,),
        )
        apr = cur.fetchone()
        if not apr:
            raise _err(404, "FIELD-HTTP-404-NOT-FOUND", "Approval request not found")
        status, atype, requested_by, excluded, pi_id = apr
        if status != "pending":
            raise _err(409, "FIELD-APR-409-DECIDED", f"Already {status}")
        if principal.id == requested_by or principal.id in (excluded or []):
            raise _err(403, "FIELD-APR-403-SOD", "Approver excluded (requester or counter)")
        new_status = "approved" if body.decision == "approve" else "rejected"
        cur.execute(
            "UPDATE field.approval_request SET status = %s, approved_by = %s, reason = %s, decided_at = NOW()"
            " WHERE id = %s::uuid",
            (new_status, principal.id, body.reason, apr_id),
        )
        erp_doc = None
        if new_status == "approved" and atype == "pi_variance" and pi_id:
            erp_doc = stage_pi_posting(cur, principal.tenant_id, str(pi_id), idempotency_key, principal.id)
    return {"id": apr_id, "status": new_status, "erp_document_id": erp_doc}
