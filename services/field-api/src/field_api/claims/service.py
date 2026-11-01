"""Supplier claims (M5 contract section 3): create from a look, list, read, decide by voice, confirm within 10 s.

- create: the look through the look port; lines computed (``claims.lines``); the text drafted by Muse or the
  template (``claims.text``); one claim per look (UNIQUE (tenant_id, look_id)): a second create for the same look
  returns the first claim and makes no model call. A look whose label read is still running (``final`` false,
  M5-S01) is refused 409 FIELD-CLM-409-LOOK-PENDING: a claim is always made from the look's final state.
- decide (supervisor, ``field.claim.decide``; If-Match): ``approve`` / ``reject`` -> ``pending_confirm`` with a
  read-back and ``confirm_by`` = now + FIELD_CONFIRM_TIMEOUT_S (10 s, the posting rule of routes/voice.py), on the
  database clock.
- confirm (the same person who decided; If-Match; server-checked on the database clock): within the window ->
  ``approved`` / ``rejected``; later -> the claim goes back to ``draft`` (the decision is cleared) and the answer is
  422 FIELD-CLM-422-CONFIRM-EXPIRED. A decision left unconfirmed (e.g. "cancel" by voice) is void the same way when
  the claim is next read or listed. Approval writes the SIMULATED send: one ``claim.sent`` outbox record
  (``simulated: true``), no e-mail and no network call.
Every state change bumps ``version``; the ETag is ``generate_etag(claim_id, version)`` like sites and locations.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from types import MappingProxyType
from typing import Any

from field_api.assistant.model import ModelRouter
from field_api.auth.jwt import Principal
from field_api.claims.lines import (
    ClaimLine,
    claim_lines,
    expected_pieces_per_unit,
    lines_from_stored,
    window_days,
)
from field_api.claims.looks import LookPort
from field_api.claims.text import draft_text, summary
from field_api.db import principal_tx
from field_api.deps import require_site_scope
from field_api.errors import ERR_ETAG_MISMATCH, ERR_ETAG_REQUIRED, FieldError
from field_api.http.etag import generate_etag
from field_api.routes.voice import CONFIRM_TIMEOUT_S

ERR_LOOK = FieldError(status=404, code="FIELD-CLM-404-LOOK", title="Look not found")
ERR_CLAIM = FieldError(status=404, code="FIELD-CLM-404-NOT-FOUND", title="Claim not found")
ERR_NOTHING = FieldError(status=422, code="FIELD-CLM-422-NOTHING-TO-CLAIM", title="Nothing to claim",
                         detail="The look has no damaged, short, pack-size, expired or near-expiry units.")
ERR_NO_SITE = FieldError(status=422, code="FIELD-CLM-422-NO-SITE", title="The look's site is not known",
                         detail="Neither the look's capture nor its task is visible here.")
ERR_STATE = FieldError(status=409, code="FIELD-CLM-409-STATE", title="The claim is not in a state for this")
ERR_NOT_DECIDER = FieldError(status=403, code="FIELD-CLM-403-NOT-DECIDER",
                             title="Only the supervisor who decided can confirm")
ERR_EXPIRED = FieldError(status=422, code="FIELD-CLM-422-CONFIRM-EXPIRED", title="Confirm came too late",
                         detail=f"Confirm within {CONFIRM_TIMEOUT_S:g} s of the decision. The claim is a draft "
                                "again; decide again.")
ERR_ID = FieldError(status=422, code="FIELD-HTTP-422-VALIDATION", title="Invalid id")
ERR_LOOK_PENDING = FieldError(status=409, code="FIELD-CLM-409-LOOK-PENDING", title="The look is still reading labels",
                              detail="A claim is made from the look's final state (M5-S01). Try again when GET "
                                     "/v1/vision/looks/{id} answers final: true.")

STATUS_FILTER = MappingProxyType({"draft": ("draft",), "pending": ("pending_confirm",),
                                  "pending_confirm": ("pending_confirm",), "approved": ("approved",),
                                  "rejected": ("rejected",)})
COLS = ("id, site_id, look_id, task_id, capture_id, status, lines, text, source, reasons, model_calls, created_by,"
        " created_at, decision, decision_reason, decided_by, decided_at, confirm_by, confirmed_by, confirmed_at,"
        " confirm_words, sent_outbox_id, version, updated_at")
_NAMES = tuple(c.strip() for c in COLS.split(","))


def check_if_match(if_match: str | None, claim_id: str, version: int) -> None:
    """The If-Match rule of http/etag.verify_if_match, on a header value (the assistant passes its own)."""
    if not if_match:
        raise ERR_ETAG_REQUIRED
    expected = generate_etag(claim_id, version).strip('"')
    if if_match.strip() != "*" and if_match.strip().strip('"') != expected:
        raise ERR_ETAG_MISMATCH


def _uuid(v: str) -> str:
    try:
        return str(uuid.UUID(v))
    except ValueError:
        raise ERR_ID from None


def _iso(v: Any) -> str | None:
    return v.isoformat() if isinstance(v, datetime) else None


def _row(cur: Any) -> dict[str, Any] | None:
    r = cur.fetchone()
    return dict(zip(_NAMES, r, strict=True)) if r else None


def _tid(row: dict[str, Any]) -> str | None:
    return str(row["task_id"]) if row.get("task_id") else None


def _jsonish(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str) else v


def evidence_doc(cur: Any, look_id: str, task_id: str | None) -> tuple[str, str] | None:
    """(doc_number, fiscal_year) of the posted document of this look: ``erp_document.payload.look_id`` (stream V's
    receive extension), else the latest posted goods receipt of the look's task."""
    cur.execute("SELECT doc_number, fiscal_year FROM field.erp_document WHERE payload->>'look_id' = %s"
                " AND status = 'posted' AND doc_number IS NOT NULL ORDER BY created_at DESC LIMIT 1", (look_id,))
    r = cur.fetchone()
    if r is None and task_id:
        cur.execute("SELECT doc_number, fiscal_year FROM field.erp_document WHERE payload->>'task_id' = %s"
                    " AND doc_type = 'GR' AND status = 'posted' AND doc_number IS NOT NULL"
                    " ORDER BY created_at DESC LIMIT 1", (task_id,))
        r = cur.fetchone()
    return (str(r[0]), str(r[1])) if r else None


def evidence_path(doc: tuple[str, str] | None) -> str:
    """The authenticated JSON evidence pack of the claim's document; "" until the receipt is posted."""
    return f"/v1/evidence/documents/{doc[0]}?year={doc[1]}" if doc else ""


def view(row: dict[str, Any], doc: tuple[str, str] | None) -> dict[str, Any]:
    """The claim as the API returns it (contract section 3 fields first, then the record)."""
    lines = lines_from_stored(_jsonish(row["lines"]))
    return {
        "claim_id": str(row["id"]), "status": row["status"], "lines": [ln.api() for ln in lines],
        "text": row["text"], "source": row["source"], "reasons": list(_jsonish(row["reasons"]) or []),
        "evidence_url": evidence_path(doc),
        "look_id": str(row["look_id"]), "task_id": str(row["task_id"]) if row["task_id"] else None,
        "site_id": str(row["site_id"]), "created_by": row["created_by"], "created_at": _iso(row["created_at"]),
        "decision": row["decision"], "decision_reason": row["decision_reason"], "decided_by": row["decided_by"],
        "decided_at": _iso(row["decided_at"]), "confirm_by": _iso(row["confirm_by"]),
        "confirmed_by": row["confirmed_by"], "confirmed_at": _iso(row["confirmed_at"]),
        "confirm_words": row["confirm_words"], "sent": row["sent_outbox_id"] is not None,
        "version": int(row["version"]),
        "etag": generate_etag(str(row["id"]), int(row["version"])),  # the ETag header's value, also in list items
    }


def etag(out: dict[str, Any]) -> str:
    return generate_etag(out["claim_id"], int(out["version"]))


def _site_of(cur: Any, look: dict[str, Any]) -> str | None:
    image = look.get("image") if isinstance(look.get("image"), dict) else {}
    cap = image.get("capture_id") if isinstance(image, dict) else None
    if cap:
        try:
            cur.execute("SELECT site_id FROM field.capture WHERE id = %s::uuid", (str(uuid.UUID(str(cap))),))
            r = cur.fetchone()
            if r:
                return str(r[0])
        except ValueError:
            pass
    if look.get("task_id"):
        cur.execute("SELECT site_id FROM field.task WHERE id = %s::uuid", (str(look["task_id"]),))
        r = cur.fetchone()
        if r:
            return str(r[0])
    return None


def _existing(cur: Any, look_id: str) -> dict[str, Any] | None:
    cur.execute(f"SELECT {COLS} FROM field.supplier_claim WHERE look_id = %s::uuid", (look_id,))
    return _row(cur)


def create_claim(principal: Principal, look_id: str, *, looks: LookPort, router: ModelRouter,
                 request_id: str | None = None) -> tuple[dict[str, Any], bool]:
    """(claim, created). An existing claim of the look is returned as it is (created False, no model call)."""
    look_id = _uuid(look_id)
    with principal_tx(principal) as cur:
        row = _existing(cur, look_id)
        if row is not None:
            return view(row, evidence_doc(cur, look_id, _tid(row))), False
    look = looks(principal, look_id)
    if look is None:
        raise ERR_LOOK
    if look.get("final") is False:  # damage, pack size and expiry are not known before the label read ends
        raise ERR_LOOK_PENDING
    lines = claim_lines(look)
    if not lines:
        raise ERR_NOTHING
    with principal_tx(principal) as cur:
        site_id = _site_of(cur, look)
    if site_id is None:
        raise ERR_NO_SITE
    require_site_scope(site_id, principal)
    ppu, window = expected_pieces_per_unit(look), window_days(look)
    draft = draft_text(lines, router=router, tenant_id=principal.tenant_id, request_id=request_id, ppu=ppu,
                       window=window)
    image = look.get("image") if isinstance(look.get("image"), dict) else {}
    capture_id = image.get("capture_id") if isinstance(image, dict) else None
    try:
        capture_id = str(uuid.UUID(str(capture_id))) if capture_id else None
    except ValueError:
        capture_id = None
    task_id = look.get("task_id")
    with principal_tx(principal) as cur:
        cur.execute(
            f"""
            INSERT INTO field.supplier_claim (tenant_id, site_id, look_id, task_id, capture_id, lines, text, source,
                   reasons, model_calls, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, look_id) DO NOTHING RETURNING {COLS}
            """,
            (principal.tenant_id, site_id, look_id, task_id, capture_id,
             json.dumps([ln.stored() for ln in lines]), draft.text, draft.source, json.dumps(draft.reasons),
             json.dumps(draft.model_calls), principal.id),
        )
        row = _row(cur)
        created = row is not None
        if row is None:  # a concurrent create of the same look won
            row = _existing(cur, look_id)
            if row is None:
                raise ERR_CLAIM
        return view(row, evidence_doc(cur, look_id, str(task_id) if task_id else None)), created


_EXPIRE_SET = ("status = 'draft', decision = NULL, decision_reason = NULL, decided_by = NULL, decided_at = NULL,"
               " confirm_by = NULL, version = version + 1, updated_at = NOW()")


def expire_pending(cur: Any, claim_id: str | None = None) -> None:
    """A decision not confirmed in time is void: the claim is a draft again (also after "cancel" by voice)."""
    sql = f"UPDATE field.supplier_claim SET {_EXPIRE_SET} WHERE status = 'pending_confirm' AND confirm_by < NOW()"
    if claim_id is None:
        cur.execute(sql)
    else:
        cur.execute(sql + " AND id = %s::uuid", (claim_id,))


def list_claims(principal: Principal, status: str | None, limit: int = 50) -> dict[str, Any]:
    """Oldest first (the "next claim" is the first draft)."""
    where, args = "", []
    if status is not None:
        where = " WHERE status = ANY(%s)"
        args.append(list(STATUS_FILTER[status]))
    with principal_tx(principal) as cur:
        expire_pending(cur)
        cur.execute(f"SELECT {COLS} FROM field.supplier_claim{where} ORDER BY created_at, id LIMIT %s",
                    (*args, limit))
        rows = [dict(zip(_NAMES, r, strict=True)) for r in cur.fetchall()]
        items = [view(r, evidence_doc(cur, str(r["look_id"]), _tid(r)))
                 for r in rows]
    return {"items": items, "count": len(items)}


def get_claim(principal: Principal, claim_id: str) -> dict[str, Any]:
    claim_id = _uuid(claim_id)
    with principal_tx(principal) as cur:
        expire_pending(cur, claim_id)
        cur.execute(f"SELECT {COLS} FROM field.supplier_claim WHERE id = %s::uuid", (claim_id,))
        row = _row(cur)
        if row is None:
            raise ERR_CLAIM
        return view(row, evidence_doc(cur, str(row["look_id"]), _tid(row)))


def read_back(decision: str, lines: list[ClaimLine], reason: str | None) -> str:
    """What the supervisor hears before "confirm" (two sentences at most)."""
    what = summary(lines)
    secs = f"{CONFIRM_TIMEOUT_S:g}"
    if decision == "approve":
        return f"Approve the claim for {what}? Say confirm within {secs} seconds."
    why = f", reason {reason.strip().rstrip('.')}" if reason and reason.strip() else ""
    return f"Reject the claim for {what}{why}? Say confirm within {secs} seconds."


def _lock(cur: Any, claim_id: str) -> dict[str, Any]:
    cur.execute(f"SELECT {COLS} FROM field.supplier_claim WHERE id = %s::uuid FOR UPDATE", (claim_id,))
    row = _row(cur)
    if row is None:
        raise ERR_CLAIM
    return row


def decide(principal: Principal, claim_id: str, decision: str, reason: str | None,
           if_match: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """(answer {status, say, confirm_by}, the claim view)."""
    claim_id = _uuid(claim_id)
    with principal_tx(principal) as cur:
        row = _lock(cur, claim_id)
        check_if_match(if_match, claim_id, int(row["version"]))
        if row["status"] not in ("draft", "pending_confirm"):
            raise ERR_STATE
        cur.execute(
            f"""
            UPDATE field.supplier_claim
               SET status = 'pending_confirm', decision = %s, decision_reason = %s, decided_by = %s,
                   decided_at = NOW(), confirm_by = NOW() + make_interval(secs => %s), confirmed_by = NULL,
                   confirmed_at = NULL, confirm_words = NULL, version = version + 1, updated_at = NOW()
             WHERE id = %s::uuid RETURNING {COLS}
            """,
            (decision, (reason or "").strip()[:500] or None, principal.id, CONFIRM_TIMEOUT_S, claim_id),
        )
        new = _row(cur)
        assert new is not None
        out = view(new, evidence_doc(cur, str(new["look_id"]), _tid(new)))
    say = read_back(decision, lines_from_stored(_jsonish(new["lines"])), new["decision_reason"])
    return {"status": "pending_confirm", "say": say, "confirm_by": out["confirm_by"]}, out


def _sent_payload(row: dict[str, Any], outbox_id: str) -> dict[str, Any]:
    return {"id": outbox_id, "type": "claim.sent", "simulated": True, "channel": "none",
            "note": "SIMULATED: no e-mail or network call is made in this build",
            "subject": f"supplier_claim/{row['id']}",
            "data": {"claim_id": str(row["id"]), "look_id": str(row["look_id"]),
                     "lines": [ln.api() for ln in lines_from_stored(_jsonish(row["lines"]))], "text": row["text"],
                     "approved_by": row["confirmed_by"]}}


def confirm(principal: Principal, claim_id: str, if_match: str | None,
            words: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """(answer {status, say}, the claim view). Too late: the claim is a draft again and ERR_EXPIRED is raised."""
    claim_id = _uuid(claim_id)
    expired = False
    with principal_tx(principal) as cur:
        row = _lock(cur, claim_id)
        check_if_match(if_match, claim_id, int(row["version"]))
        if row["status"] != "pending_confirm":
            raise ERR_STATE
        if row["decided_by"] != principal.id:
            raise ERR_NOT_DECIDER
        cur.execute("SELECT NOW() <= %s", (row["confirm_by"],))
        in_time = bool((cur.fetchone() or [False])[0])
        if not in_time:
            cur.execute(f"UPDATE field.supplier_claim SET {_EXPIRE_SET} WHERE id = %s::uuid", (claim_id,))
            expired = True
        else:
            final = "approved" if row["decision"] == "approve" else "rejected"
            cur.execute(
                f"""
                UPDATE field.supplier_claim
                   SET status = %s, confirmed_by = %s, confirmed_at = NOW(), confirm_words = %s,
                       version = version + 1, updated_at = NOW()
                 WHERE id = %s::uuid RETURNING {COLS}
                """,
                (final, principal.id, (words or "").strip()[:500] or None, claim_id),
            )
            new = _row(cur)
            assert new is not None
            if final == "approved":
                outbox_id = str(uuid.uuid4())
                cur.execute("INSERT INTO field.outbox (id, tenant_id, event_type, aggregate_id, payload)"
                            " VALUES (%s, %s, 'claim.sent', %s, %s)",
                            (outbox_id, principal.tenant_id, claim_id, json.dumps(_sent_payload(new, outbox_id))))
                cur.execute(f"UPDATE field.supplier_claim SET sent_outbox_id = %s WHERE id = %s::uuid"
                            f" RETURNING {COLS}", (outbox_id, claim_id))
                new = _row(cur)
                assert new is not None
            out = view(new, evidence_doc(cur, str(new["look_id"]), _tid(new)))
    if expired:
        raise ERR_EXPIRED
    if out["status"] == "approved":
        say = "Claim approved. Sending it to the supplier is simulated in this build."
    else:
        say = "Claim rejected. Nothing is sent to the supplier."
    return {"status": out["status"], "say": say}, out
