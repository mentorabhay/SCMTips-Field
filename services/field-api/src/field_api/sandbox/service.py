"""Sandbox (home / training) actions, M3 contract sections 3 and 7.

A sandbox site (field.site.mode = 'sandbox') lets any real box become a material, a receipt line and a
count line, with real documents in the ERP (erp-sim). On a production site every action here is refused
with 403 FIELD-SBX-403-PRODUCTION. The ERP is reached only through the adapter chosen by config
(sandbox/erp.py); the S/4 adapter refuses sandbox operations (409 FIELD-SBX-409-NOT-SUPPORTED).

- ``create_receipt``: an open inbound delivery in the ERP with no items, and its receive task at once.
- ``create_count``: an empty count (field PI document) for one bin; boxes become its lines.
- ``add_item`` (the SandboxItems seam of track A): a scanned code on a sandbox receive or count task.
  A code no material has yet becomes a new ERP material HOME-nnnn with that barcode. On a receipt the
  line is a new delivery item (soft pegging: at post the delivery quantity is set to the counted one,
  then GR 101, tasks/api.py). On a count it is a new count line for the count's bin, its book taken from
  the field bin stock (0 for a new box: the count then posts 561 instead of a difference, jobs/finish.py).
  ``qty``: on a receipt the delivery quantity of the new item (the operator still counts; soft pegging
  makes the counted quantity win at post); on a count the blind count of the new line.
  The same Idempotency-Key, or the same material again, returns the first line.
"""

from __future__ import annotations

from collections.abc import Coroutine
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, TypedDict

from field_sap.ports.erp_port import SANDBOX_NOT_SAP, ErpError

from field_api.auth.jwt import Principal
from field_api.auth.permissions import has_permission
from field_api.codes.resolve import SiteInfo, find_material, site_info
from field_api.db import principal_tx
from field_api.errors import FieldError
from field_api.jobs.counting import record_blind_count
from field_api.pi.api import DEFAULT_UNIT_PRICE, count_title
from field_api.sandbox import erp

SBX_PRODUCTION = "FIELD-SBX-403-PRODUCTION"
HOME_SUPPLIER = "HOME"
DEFAULT_SLOC = "0001"
FINISHED = frozenset({"completed", "cancelled", "posting", "awaiting_approval"})


class SandboxItemResult(TypedDict):
    line_id: str
    material: str
    created_material: bool


class SandboxTaskResult(TypedDict):
    task_id: str
    ref_doc_no: str


def production_refused(site_name: str) -> FieldError:
    return FieldError(status=403, code=SBX_PRODUCTION,
                      title="This is a production site. Only items the ERP already knows can be used here.",
                      detail=f"{site_name} is in production mode; sandbox actions need a sandbox site")


def _state(title: str, detail: str | None = None) -> FieldError:
    return FieldError(status=409, code="FIELD-TASK-409-STATE", title=title, detail=detail)


def _require_execute(principal: Principal) -> None:
    if not has_permission(principal.permissions, "field.task.execute"):
        raise FieldError(status=403, code="FIELD-AUTH-403-PERMISSION", title="Permission denied",
                         detail="sandbox actions need field.task.execute")


def _require_scope(principal: Principal, site_id: str) -> None:
    if "*" not in principal.site_ids and site_id not in principal.site_ids:
        raise FieldError(code="FIELD-AUTH-403-SCOPE", status=403, title="Site not in scope")


def _sandbox_site(cur: Any, site_id: str) -> SiteInfo:
    site = site_info(cur, site_id)
    if site["mode"] != "sandbox":
        raise production_refused(site["name"])
    if not site["plant"]:
        raise _state("This sandbox site has no ERP plant", "set erp_plant on the site")
    return site


def _sloc(site: SiteInfo) -> str:
    return site["storage_locations"][0] if site["storage_locations"] else DEFAULT_SLOC


def _erp[T](coro: Coroutine[Any, Any, T]) -> T:
    try:
        return erp.run(coro)
    except ErpError as e:
        if e.code == SANDBOX_NOT_SAP:
            raise FieldError(status=409, code="FIELD-SBX-409-NOT-SUPPORTED",
                             title="This ERP has no sandbox", detail=e.message) from e
        raise FieldError(status=502, code="FIELD-SBX-502-ERP", title="The ERP refused the sandbox action",
                         detail=e.message) from e


# --------------------------------------------------------------------------- receipts and counts
def create_receipt(principal: Principal, site_id: str) -> SandboxTaskResult:
    """An open, empty inbound delivery in the ERP and its receive task (created now, no worker wait)."""
    _require_execute(principal)
    _require_scope(principal, site_id)
    with principal_tx(principal) as cur:
        site = _sandbox_site(cur, site_id)
    deliv = _erp(erp.get_sandbox_port().create_sandbox_inbound_delivery(
        str(site["plant"]), _sloc(site), HOME_SUPPLIER))
    with principal_tx(principal) as cur:
        cur.execute("SELECT id FROM field.task WHERE site_id = %s AND type = 'receive' AND ref_doc_no = %s",
                    (site_id, deliv.delivery_document))
        row = cur.fetchone()
        if row is None:
            cur.execute(
                """
                INSERT INTO field.task (tenant_id, site_id, type, status, priority, title, ref_doc_no, last_change_at,
                       subtitle)
                VALUES (%s, %s, 'receive', 'pending', 'normal', %s, %s, %s::timestamptz, %s) RETURNING id
                """,
                (principal.tenant_id, site_id, f"Delivery {deliv.delivery_document}", deliv.delivery_document,
                 deliv.last_change, f"From {site['name']}"),
            )
            row = cur.fetchone()
    return {"task_id": str(row[0]), "ref_doc_no": deliv.delivery_document}


def create_count(principal: Principal, site_id: str, storage_bin: str, simulated: bool = False) -> SandboxTaskResult:
    """An empty blind count of one bin of a sandbox site; scanned boxes become its lines (add_item).

    No posting block: at home the same bin is received into while it is counted. ``simulated`` marks the
    count set up by ``stack home --simulate-differences`` (its ERP documents say so).
    """
    _require_execute(principal)
    _require_scope(principal, site_id)
    with principal_tx(principal) as cur:
        site = _sandbox_site(cur, site_id)
        cur.execute("SELECT code FROM field.location WHERE site_id = %s AND upper(code) = upper(%s)"
                    " AND erp_ref_type = 'storage_bin' AND status = 'active'", (site_id, storage_bin.strip()))
        brow = cur.fetchone()
        if not brow:
            raise FieldError(status=404, code="FIELD-HTTP-404-NOT-FOUND", title=f"{storage_bin} is not a bin here")
        bin_ = str(brow[0])
        now = datetime.now(UTC)
        doc_number = f"PID-{now:%Y%m%d%H%M%S%f}"
        cur.execute(
            """
            INSERT INTO field.task (tenant_id, site_id, type, status, priority, title, ref_doc_no, subtitle)
            VALUES (%s, %s, 'count', 'pending', 'normal', %s, %s, %s) RETURNING id
            """,
            (principal.tenant_id, site_id, count_title({bin_}), doc_number, f"PI {doc_number}"),
        )
        task_id = str(cur.fetchone()[0])
        cur.execute(
            """
            INSERT INTO field.pi_document (tenant_id, doc_number, fiscal_year, plant, storage_location,
                   posting_blocked, freeze_book, status, site_id, task_id, requested_by, storage_bin, simulated)
            VALUES (%s, %s, %s, %s, %s, false, true, 'open', %s, %s, %s, %s, %s)
            """,
            (principal.tenant_id, doc_number, str(now.year), site["plant"], _sloc(site), site_id, task_id,
             principal.id, bin_, simulated),
        )
    return {"task_id": task_id, "ref_doc_no": doc_number}


# --------------------------------------------------------------------------- add item (contract section 7)
def _line_by_key(cur: Any, task_id: str, key: str) -> tuple[str, str] | None:
    cur.execute(
        "SELECT l.id, m.erp_material_no FROM field.task_line l LEFT JOIN field.material m ON m.id = l.material_id"
        " WHERE l.task_id = %s::uuid AND l.source_key = %s",
        (task_id, key),
    )
    row = cur.fetchone()
    return (str(row[0]), str(row[1])) if row else None


def _line_by_material(cur: Any, task_id: str, material_id: str) -> str | None:
    cur.execute("SELECT id FROM field.task_line WHERE task_id = %s::uuid AND material_id = %s::uuid"
                " AND status <> 'cancelled' ORDER BY line_no LIMIT 1", (task_id, material_id))
    row = cur.fetchone()
    return str(row[0]) if row else None


def _load_task(cur: Any, task_id: str) -> dict[str, Any]:
    cur.execute("SELECT id, site_id, type, status, ref_doc_no FROM field.task WHERE id = %s::uuid FOR UPDATE",
                (task_id,))
    row = cur.fetchone()
    if not row:
        raise FieldError(status=404, code="FIELD-HTTP-404-NOT-FOUND", title="Task not found")
    task = {"id": str(row[0]), "site_id": str(row[1]), "type": row[2], "status": row[3], "ref_doc_no": row[4]}
    site = _sandbox_site(cur, task["site_id"])
    if task["type"] not in ("receive", "count"):
        raise _state("Items are added to receipts and counts only", f"this is a {task['type']} job")
    if task["status"] in FINISHED:
        raise _state("This job is already finished")
    task["site"] = site
    if task["type"] == "count":
        cur.execute("SELECT id, storage_bin FROM field.pi_document WHERE task_id = %s::uuid"
                    " AND status IN ('open', 'counted', 'recount') ORDER BY created_at DESC LIMIT 1", (task_id,))
        pi = cur.fetchone()
        if not pi or not pi[1]:
            raise _state("This count takes no new items", "only a sandbox count of one bin gains lines")
        task["pi_id"], task["bin"] = str(pi[0]), str(pi[1])
    return task


def _ensure_field_material(cur: Any, principal: Principal, plant: str, material_no: str, description: str,
                           uom: str, barcode: str) -> str:
    cur.execute(
        """
        INSERT INTO field.material (tenant_id, plant, erp_material_no, description, base_uom, source, status)
        VALUES (%s, %s, %s, %s, %s, 'sandbox', 'active')
        ON CONFLICT (tenant_id, plant, erp_material_no) DO UPDATE SET status = 'active', deleted_in_erp_at = NULL
        RETURNING id
        """,
        (principal.tenant_id, plant, material_no, description, uom),
    )
    material_id = str(cur.fetchone()[0])
    cur.execute(
        "INSERT INTO field.material_barcode (tenant_id, material_id, barcode, uom) VALUES (%s, %s, %s, %s)"
        " ON CONFLICT (tenant_id, material_id, barcode) DO NOTHING",
        (principal.tenant_id, material_id, barcode, uom),
    )
    return material_id


def add_item(principal: Principal, task_id: str, code: str, description: str, qty: Decimal | None,
             idempotency_key: str) -> SandboxItemResult:
    """The SandboxItems of the M3 contract (section 7). Raises FIELD-SBX-403-PRODUCTION on a production site."""
    _require_execute(principal)
    barcode = code.strip()
    if not barcode or len(barcode) > 128:
        raise FieldError(status=422, code="FIELD-HTTP-422-VALIDATION", title="A code of 1 to 128 characters is needed")
    if qty is not None and qty < 0:
        raise FieldError(status=422, code="FIELD-HTTP-422-VALIDATION", title="The quantity cannot be negative")
    with principal_tx(principal) as cur:
        task = _load_task(cur, task_id)
        again = _line_by_key(cur, task_id, idempotency_key)
        if again:
            return {"line_id": again[0], "material": again[1], "created_material": False}
        found = find_material(cur, task["site"]["plant"], barcode)
    plant = str(task["site"]["plant"])
    created = False
    if found:
        material_id, mat = found[0], found[1]["material"]
        uom = found[1]["uom"]
    else:
        sm = _erp(erp.get_sandbox_port().create_sandbox_material(plant, (description or barcode).strip()[:40], "EA",
                                                                barcode))
        created, mat, uom = sm.created, sm.material_no, sm.base_uom
        with principal_tx(principal) as cur:
            material_id = _ensure_field_material(cur, principal, plant, sm.material_no, sm.description, uom, barcode)
    with principal_tx(principal) as cur:
        existing = _line_by_material(cur, task_id, material_id)
    if existing:
        return {"line_id": existing, "material": mat, "created_material": created}
    item_no: str | None = None
    last_change: str | None = None
    if task["type"] == "receive":
        item = _erp(erp.get_sandbox_port().add_sandbox_inbound_delivery_item(
            str(task["ref_doc_no"]), mat, f"{qty or Decimal(0):.3f}", uom, idempotency_key))
        item_no, last_change = item.item_no, item.last_change
    with principal_tx(principal) as cur:
        task = {**task, **_load_task(cur, task_id)}
        raced = _line_by_key(cur, task_id, idempotency_key)
        same = raced[0] if raced else _line_by_material(cur, task_id, material_id)
        if same:
            return {"line_id": same, "material": mat, "created_material": created}
        if task["type"] == "receive":
            cur.execute(
                """
                INSERT INTO field.task_line (tenant_id, site_id, task_id, line_no, material_id, expected_qty, uom,
                       captured_qty, counted_qty, status, source_key)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0, 'pending', %s) RETURNING id
                """,
                (principal.tenant_id, task["site_id"], task_id, int(str(item_no)), material_id, qty or Decimal(0), uom,
                 idempotency_key),
            )
            line_id = str(cur.fetchone()[0])
            cur.execute("UPDATE field.task SET last_change_at = COALESCE(%s::timestamptz, NOW()), version = version + 1,"
                        " updated_at = NOW() WHERE id = %s::uuid", (last_change, task_id))
        else:
            cur.execute("SELECT COALESCE(MAX(line_no), 0) + 1 FROM field.task_line WHERE task_id = %s::uuid", (task_id,))
            line_no = int(cur.fetchone()[0])
            cur.execute(
                """
                INSERT INTO field.task_line (tenant_id, site_id, task_id, line_no, material_id, expected_qty, uom,
                       storage_bin, status, source_key)
                VALUES (%s, %s, %s, %s, %s, 0, %s, %s, 'pending', %s) RETURNING id
                """,
                (principal.tenant_id, task["site_id"], task_id, line_no, material_id, uom, task["bin"], idempotency_key),
            )
            line_id = str(cur.fetchone()[0])
            cur.execute("SELECT COALESCE(SUM(quantity), 0) FROM field.bin_stock WHERE site_id = %s AND storage_bin = %s"
                        " AND material_no = %s", (task["site_id"], task["bin"], mat))
            book = Decimal(cur.fetchone()[0])  # server-side snapshot; never shown to the operator (FR3.029)
            cur.execute(
                "INSERT INTO field.pi_book (tenant_id, pi_document_id, task_line_id, book_qty, unit_price, currency)"
                " VALUES (%s, %s, %s, %s, %s, 'INR')",
                (principal.tenant_id, task["pi_id"], line_id, book, DEFAULT_UNIT_PRICE),
            )
            cur.execute("UPDATE field.pi_document SET status = 'open' WHERE id = %s::uuid AND status = 'counted'",
                        (task["pi_id"],))
            cur.execute("UPDATE field.task SET version = version + 1, updated_at = NOW() WHERE id = %s::uuid", (task_id,))
            if qty is not None:  # "How many?" answered with the item: that is the blind count of the new line
                record_blind_count(cur, principal, task_id, line_id, qty, uom, "manual", None)
    return {"line_id": line_id, "material": mat, "created_material": created}
