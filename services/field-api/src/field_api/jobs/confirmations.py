"""Line confirmations: the scans of the one job runner (M2 jobs contract §3).

POST /v1/tasks/{task_id}/lines/{line_id}/confirmations  {kind: bin|product|hu|serial, code, source, role?, reason?}

- putaway: ``bin``. The suggested bin confirms the line. A different bin of this site needs a reason
  (FR3.013: bin_full, rack_damaged, other); without one it is 409 FIELD-TASK-409-WRONG-CODE.
- pick: ``bin`` then ``product`` (FR3.018: a source bin scan followed by a product that matches the
  delivery item). Wrong bin / wrong product / product before bin: 409 FIELD-TASK-409-WRONG-CODE.
- audit: ``serial``. Any captured serial is accepted; ``match`` says whether it is the expected unit.
  Mismatches reach the console through reconciliation when the audit is finished (contract §4).
- swap: ``serial`` with role ``old`` (must be the unit to remove) and ``new`` (the replacement; not the
  old unit, not installed anywhere else).
- receive / count: ``product`` / ``hu`` / ``bin`` scans are recorded; a product must match the line.

Bins and products under an open PI document with posting block are refused for putaway and pick
(FR3.036, 423 FIELD-PI-423-POSTING-BLOCKED). Every scan, accepted or not, is kept in
field.task_line_confirmation.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from psycopg import sql
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.db import principal_tx
from field_api.deps import require_permission
from field_api.errors import FieldError

router = APIRouter(tags=["Job runner (M2)"])

PUTAWAY_DIVERT_REASONS = frozenset({"bin_full", "rack_damaged", "other"})
WRONG = "FIELD-TASK-409-WRONG-CODE"


class ConfirmationIn(BaseModel):
    kind: Literal["bin", "product", "hu", "serial"]
    code: str = Field(min_length=1, max_length=128)
    source: Literal["scan", "voice", "manual"] = "scan"
    role: Literal["old", "new"] | None = None
    reason: str | None = Field(default=None, max_length=32)


def norm(code: str | None) -> str:
    return (code or "").strip().upper()


def _wrong(title: str, detail: str | None = None) -> FieldError:
    return FieldError(status=409, code=WRONG, title=title, detail=detail)


def _record(cur: Any, principal: Principal, line: dict[str, Any], body: ConfirmationIn, role: str | None,
            accepted: bool, match: bool | None) -> None:
    cur.execute(
        """
        INSERT INTO field.task_line_confirmation (tenant_id, site_id, task_id, task_line_id, kind, role, code,
               source, accepted, match, confirmed_by, device_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (principal.tenant_id, line["site_id"], line["task_id"], line["id"], body.kind, role, norm(body.code),
         body.source, accepted, match, principal.id, principal.device_id),
    )


def _posting_blocked(cur: Any, storage_bin: str | None, material_id: str | None) -> bool:
    if not storage_bin:
        return False
    cur.execute(
        """
        SELECT 1 FROM field.pi_book b
          JOIN field.pi_document d ON d.id = b.pi_document_id
          JOIN field.task_line tl ON tl.id = b.task_line_id
         WHERE d.posting_blocked AND d.status IN ('open', 'counted', 'recount')
           AND tl.storage_bin = %s AND (%s::uuid IS NULL OR tl.material_id = %s::uuid)
         LIMIT 1
        """,
        (storage_bin, material_id, material_id),
    )
    return cur.fetchone() is not None


def _load(cur: Any, task_id: str, line_id: str) -> dict[str, Any]:
    cur.execute(
        """
        SELECT l.id, l.task_id, l.site_id, l.status, l.storage_bin, l.material_id, m.erp_material_no,
               l.expected_serial, l.confirmed_bin, l.captured_serial, l.new_serial, t.type, t.status, m.gtin
          FROM field.task_line l JOIN field.task t ON t.id = l.task_id
          LEFT JOIN field.material m ON m.id = l.material_id
         WHERE l.id = %s::uuid AND l.task_id = %s::uuid
         FOR UPDATE OF l
        """,
        (line_id, task_id),
    )
    r = cur.fetchone()
    if not r:
        raise FieldError(status=404, code="FIELD-HTTP-404-NOT-FOUND", title="Task line not found")
    keys = ("id", "task_id", "site_id", "status", "bin", "material_id", "material", "expected_serial",
            "confirmed_bin", "captured_serial", "new_serial", "type", "task_status", "gtin")
    return {k: (str(v) if k in ("id", "task_id", "site_id", "material_id") and v is not None else v)
            for k, v in zip(keys, r, strict=True)}


def _set(cur: Any, line_id: str, **cols: Any) -> str:
    sets = sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(c)) for c in cols)
    cur.execute(
        sql.SQL("UPDATE field.task_line SET {}, version = version + 1, updated_at = NOW()"
                " WHERE id = %s::uuid RETURNING status").format(sets),
        (*cols.values(), line_id),
    )
    row = cur.fetchone()
    return str(row[0]) if row else ""


def _bin_exists(cur: Any, site_id: str, code: str) -> bool:
    cur.execute("SELECT 1 FROM field.location WHERE site_id = %s AND code = %s AND erp_ref_type = 'storage_bin'"
                " AND status = 'active'", (site_id, code))
    return cur.fetchone() is not None


def _progress_status(current: str) -> str:
    return "confirmed" if current in ("pending", "in_progress", "confirmed") else current


@router.post("/v1/tasks/{task_id}/lines/{line_id}/confirmations")
def confirm_line(
    task_id: str,
    line_id: str,
    body: ConfirmationIn,
    principal: Principal = Depends(require_permission("field.capture.create")),
) -> dict[str, Any]:
    from field_api.jobs.status import line_state_out

    code = norm(body.code)
    with principal_tx(principal) as cur:
        ln = _load(cur, task_id, line_id)
        if ln["task_status"] in ("completed", "cancelled", "posting") or ln["status"] in ("posted", "done", "posting"):
            raise FieldError(status=409, code="FIELD-TASK-409-STATE", title="This job is already finished")
        ttype = ln["type"]
        out: dict[str, Any] = {"ok": True}
        try:
            if ttype == "putaway":
                out.update(_putaway(cur, ln, body, code))
            elif ttype == "pick":
                out.update(_pick(cur, ln, body, code))
            elif ttype == "audit":
                out.update(_audit(cur, ln, body, code))
            elif ttype == "swap":
                out.update(_swap(cur, ln, body, code))
            else:
                out.update(_record_only(ln, body, code))
        except FieldError as e:
            if e.code == WRONG:  # the refused scan is evidence too; keep it, then answer 409
                _record(cur, principal, ln, body, body.role, False, False)
                cur.connection.commit()
            raise
        _record(cur, principal, ln, body, out.pop("_role", body.role), True, out.get("match"))
        cur.execute("UPDATE field.task SET status = 'in_progress', updated_at = NOW()"
                    " WHERE id = %s::uuid AND status = 'pending'", (task_id,))
        out["line_status"] = line_state_out(str(out.pop("_status", ln["status"])))
    return out


def _putaway(cur: Any, ln: dict[str, Any], body: ConfirmationIn, code: str) -> dict[str, Any]:
    if body.kind != "bin":
        raise _wrong("Scan the bin label", "Put-away lines are confirmed by the bin")
    suggested = norm(ln["bin"])
    divergent = code != suggested
    if divergent:
        if not _bin_exists(cur, ln["site_id"], code):
            raise _wrong(f"{code} is not a bin here. Go to {suggested}.")
        if body.reason not in PUTAWAY_DIVERT_REASONS:
            raise _wrong(f"That is bin {code}. Go to {suggested}.",
                         "To store in a different bin, confirm with a reason: bin_full, rack_damaged or other")
    if _posting_blocked(cur, code, ln["material_id"]):
        raise FieldError(status=423, code="FIELD-PI-423-POSTING-BLOCKED", title=f"Bin {code} is being counted",
                         detail="Wait until the count is posted")
    status = _set(cur, ln["id"], confirmed_bin=code, reason_code=body.reason if divergent else None,
                  status=_progress_status(ln["status"]))
    return {"_status": status, "bin": code, "divergent": divergent}


def _pick(cur: Any, ln: dict[str, Any], body: ConfirmationIn, code: str) -> dict[str, Any]:
    bin_ = norm(ln["bin"])
    if body.kind == "bin":
        if code != bin_:
            raise _wrong(f"That is bin {code}. Go to {bin_}.")
        if _posting_blocked(cur, code, ln["material_id"]):
            raise FieldError(status=423, code="FIELD-PI-423-POSTING-BLOCKED", title=f"Bin {code} is being counted",
                             detail="Pick this line after the count is posted")
        return {"_status": _set(cur, ln["id"], confirmed_bin=code), "bin": code}
    if body.kind == "product":
        if norm(ln["confirmed_bin"]) != bin_:
            raise _wrong(f"Scan bin {bin_} first.")
        if code not in {norm(ln["material"]), norm(ln["gtin"])}:
            raise _wrong(f"That is {code}. Pick {ln['material']}.")
        return {"_status": _set(cur, ln["id"], confirmed_product=code, status=_progress_status(ln["status"])),
                "product": code}
    raise _wrong("Scan the bin, then the product")


def _audit(cur: Any, ln: dict[str, Any], body: ConfirmationIn, code: str) -> dict[str, Any]:
    if body.kind != "serial":
        raise _wrong("Scan the serial number on the unit")
    match = code == norm(ln["expected_serial"])
    status = _set(cur, ln["id"], captured_serial=code, status="confirmed")
    return {"_status": status, "match": match}


def _swap(cur: Any, ln: dict[str, Any], body: ConfirmationIn, code: str) -> dict[str, Any]:
    if body.kind != "serial":
        raise _wrong("Scan the serial number on the unit")
    role = body.role or ("new" if ln["captured_serial"] else "old")
    expected = norm(ln["expected_serial"])
    if role == "old":
        if code != expected:
            raise _wrong(f"That is unit {code}. The unit to remove is {expected}.")
        status = _set(cur, ln["id"], captured_serial=code,
                      status="confirmed" if ln["new_serial"] else _keep_open(ln["status"]))
        return {"_status": status, "_role": role, "match": True}
    if not ln["captured_serial"]:
        raise _wrong(f"Scan the unit you remove first ({expected}).")
    if code == expected:
        raise _wrong("That is the unit you are removing. Scan the new unit.")
    cur.execute(
        "SELECT l.code FROM field.equipment e LEFT JOIN field.location l ON l.id = e.current_location_id"
        " WHERE e.serial_no = %s AND e.status = 'installed' LIMIT 1",
        (code,),
    )
    other = cur.fetchone()
    if other:
        raise _wrong(f"Unit {code} is already installed at {other[0] or 'another location'}.")
    status = _set(cur, ln["id"], new_serial=code, status="confirmed")
    return {"_status": status, "_role": role, "match": True}


def _keep_open(status: str) -> str:
    return "in_progress" if status == "pending" else status


def _record_only(ln: dict[str, Any], body: ConfirmationIn, code: str) -> dict[str, Any]:
    if body.kind == "product" and ln["material"] and code not in {norm(ln["material"]), norm(ln["gtin"])}:
        raise _wrong(f"That is {code}. This line is {ln['material']}.")
    if body.kind == "bin" and ln["bin"] and code != norm(ln["bin"]):
        raise _wrong(f"That is bin {code}. Go to {norm(ln['bin'])}.")
    return {}
