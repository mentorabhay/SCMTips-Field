"""The evidence pack of one posted ERP document (M5 contract section 3), assembled from what Field already records.

Sources (no new copies of data; only the claim table is new in M5 stream X):
- ``document``: ``field.erp_document`` (number, year, type, movement type, status) and its posting jobs
  (``field.posting_job``: each step as staged for the ERP: family, items, header) with the outbox events of those
  jobs (``posting.requested``, ``erp.posted``, ``erp.failed``), and the task lines the document posted;
- ``look``: the look named by ``erp_document.payload.look_id`` (stream V's receive extension) or, without it, the
  look of the latest claim of the document's task, read through the look port; label ``raw`` text is left out
  (M5 contract section 6: no brand or company names, raw text is not repeated);
- ``models``: every model call: the look's ``models``, the claim's drafting call(s) and the model calls of the
  assistant turns about the document's task;
- ``check``: the deterministic check: counts, pack, expiry, proposal and the claim lines computed from the look;
- ``confirm``: how the operator confirmed (``payload.confirm_method``), who and when (``requested_by``,
  ``requested_at``), and the words of the voice turns (``field.voice_event`` transcripts of the post / confirm pair);
- ``claim``: the supplier claim of the look, if any;
- ``hashes``: ``photo_sha256`` as recorded by the crop store (``capture_evidence.sha256_hash``, verified on write)
  with ``photo_sha256_verified`` = the stored bytes still hash to it; ``pack_sha256`` = sha256 of the canonical JSON
  (sorted keys, no whitespace, UTF-8) of the pack without ``hashes.pack_sha256``. Nothing time-varying is in the
  pack, so the same records always give the same hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog

from field_api.auth.jwt import Principal
from field_api.claims.lines import claim_lines, flagged_instances, short_packs
from field_api.claims.looks import LookPort
from field_api.claims.service import COLS as CLAIM_COLS
from field_api.claims.service import view as claim_view
from field_api.crops import CropStoreError, crop_store
from field_api.db import principal_tx
from field_api.errors import FieldError

logger = structlog.get_logger(__name__)

ERR_DOC = FieldError(status=404, code="FIELD-EVD-404-DOCUMENT", title="Document not found")
ERR_YEAR = FieldError(status=409, code="FIELD-EVD-409-YEAR", title="Several documents have this number",
                      detail="Give the fiscal year (?year=).")
POSTING_EVENTS = ("posting.requested", "erp.posted", "erp.failed")
_CLAIM_NAMES = tuple(c.strip() for c in CLAIM_COLS.split(","))


@dataclass(frozen=True)
class Pack:
    body: dict[str, Any]
    photo: bytes | None  # the stored image of the look's capture, for the page (never in the JSON)


def plain(v: Any) -> Any:
    """JSON-safe, deterministic values (Decimal as its plain string, datetimes in UTC ISO 8601)."""
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    if isinstance(v, Decimal):
        return f"{v.normalize():f}"
    if isinstance(v, datetime):
        return v.astimezone(UTC).isoformat()
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def canonical_json(obj: Any) -> bytes:
    return json.dumps(plain(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def pack_sha256(body: dict[str, Any]) -> str:
    """sha256 over the canonical JSON of the pack without ``hashes.pack_sha256``."""
    hashes = {k: v for k, v in (body.get("hashes") or {}).items() if k != "pack_sha256"}
    return hashlib.sha256(canonical_json({**body, "hashes": hashes})).hexdigest()


def _jsonish(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str) else v


def _document(cur: Any, doc_number: str, year: str | None) -> dict[str, Any]:
    sql = ("SELECT id, site_id, doc_type, doc_number, fiscal_year, movement_type, status, payload, created_at"
           " FROM field.erp_document WHERE doc_number = %s")
    args: list[Any] = [doc_number]
    if year:
        sql += " AND fiscal_year = %s"
        args.append(year)
    cur.execute(sql + " ORDER BY created_at DESC LIMIT 2", args)
    rows = cur.fetchall()
    if not rows:
        raise ERR_DOC
    if len(rows) > 1 and not year:
        raise ERR_YEAR
    r = rows[0]
    names = ("id", "site_id", "doc_type", "doc_number", "fiscal_year", "movement_type", "status", "payload",
             "created_at")
    return dict(zip(names, r, strict=True))


def _jobs(cur: Any, doc_id: str) -> list[dict[str, Any]]:
    cur.execute("SELECT id, seq, status, payload FROM field.posting_job WHERE erp_doc_id = %s::uuid ORDER BY seq",
                (doc_id,))
    out = []
    for jid, seq, status, payload in cur.fetchall():
        p = _jsonish(payload) or {}
        out.append({"job_id": str(jid), "seq": seq, "status": status, "family": p.get("doc_family"),
                    "header": p.get("header_data") or {}, "items": p.get("items") or []})
    return out


def _events(cur: Any, job_ids: list[str]) -> list[dict[str, Any]]:
    if not job_ids:
        return []
    cur.execute("SELECT event_type, payload, created_at FROM field.outbox WHERE aggregate_id = ANY(%s::uuid[])"
                " AND event_type = ANY(%s) ORDER BY created_at, id", (job_ids, list(POSTING_EVENTS)))
    out: list[dict[str, Any]] = []
    for etype, payload, at in cur.fetchall():
        p = _jsonish(payload) or {}
        raw = p.get("data")
        data: dict[str, Any] = raw if isinstance(raw, dict) else {}
        keep: dict[str, Any] = {k: data.get(k) for k in ("doc_type", "doc_no", "doc_year", "movement_types", "queue_key",
                                         "error_class") if k in data}
        out.append({"type": etype, "at": at, **keep})
    return out


def _lines(cur: Any, line_ids: list[str]) -> list[dict[str, Any]]:
    if not line_ids:
        return []
    cur.execute(
        "SELECT l.line_no, m.erp_material_no, m.description, l.expected_qty, l.counted_qty, l.damaged_qty, l.uom,"
        " l.storage_bin FROM field.task_line l LEFT JOIN field.material m ON m.id = l.material_id"
        " WHERE l.id = ANY(%s::uuid[]) ORDER BY l.line_no", (line_ids,))
    names = ("line_no", "material", "description", "expected_qty", "counted_qty", "damaged_qty", "uom", "bin")
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def _confirm(cur: Any, payload: dict[str, Any]) -> dict[str, Any]:
    ids = [str(payload[k]) for k in ("post_voice_event_id", "confirm_voice_event_id") if payload.get(k)]
    turns: list[dict[str, Any]] = []
    if ids:
        cur.execute("SELECT intent, transcript, confidence, client_timestamp FROM field.voice_event"
                    " WHERE id = ANY(%s::uuid[]) ORDER BY client_timestamp", (ids,))
        turns = [{"intent": i, "words": t, "confidence": c, "at": at} for i, t, c, at in cur.fetchall()]
    method = payload.get("confirm_method") or ("voice" if ids else None)
    return {"method": method, "by": payload.get("requested_by"), "at": payload.get("requested_at"),
            "device_id": payload.get("device_id"), "words": [t["words"] for t in turns], "turns": turns}


def _claim(cur: Any, look_id: str | None, task_id: str | None) -> dict[str, Any] | None:
    if look_id:
        cur.execute(f"SELECT {CLAIM_COLS} FROM field.supplier_claim WHERE look_id = %s::uuid", (look_id,))
    elif task_id:
        cur.execute(f"SELECT {CLAIM_COLS} FROM field.supplier_claim WHERE task_id = %s::uuid"
                    " ORDER BY created_at DESC LIMIT 1", (task_id,))
    else:
        return None
    r = cur.fetchone()
    return dict(zip(_CLAIM_NAMES, r, strict=True)) if r else None


def _assistant_calls(cur: Any, task_id: str | None) -> list[dict[str, Any]]:
    if not task_id:
        return []
    cur.execute("SELECT at, tool_calls FROM field.assistant_turn WHERE task_id = %s::uuid AND ai = 'model'"
                " ORDER BY at", (task_id,))
    out = []
    for _at, calls in cur.fetchall():
        for c in _jsonish(calls) or []:
            if isinstance(c, dict) and c.get("name") == "model_calls":
                for m in c.get("calls") or []:
                    if isinstance(m, dict):
                        out.append({"model": m.get("model"), "purpose": "assistant",
                                    "latency_ms": m.get("latency_ms") or 0, "cost_usd": m.get("cost_usd") or "0",
                                    "outcome": m.get("error") or "ok"})
    return out


def _photo(cur: Any, capture_id: str | None) -> tuple[dict[str, Any], bytes | None]:
    if not capture_id:
        return {"photo_sha256": None, "photo_sha256_verified": False, "photo": "none"}, None
    cur.execute("SELECT crop_s3_uri, sha256_hash, retention_until, is_legal_hold FROM field.capture_evidence"
                " WHERE capture_id = %s::uuid ORDER BY created_at DESC LIMIT 1", (capture_id,))
    r = cur.fetchone()
    if r is None:
        return {"photo_sha256": None, "photo_sha256_verified": False, "photo": "none"}, None
    uri, sha, until, hold = r
    if datetime.now(UTC) > until and not hold:
        return {"photo_sha256": sha, "photo_sha256_verified": False, "photo": "deleted_by_retention"}, None
    try:
        data = crop_store().get(uri)
    except (CropStoreError, OSError):
        return {"photo_sha256": sha, "photo_sha256_verified": False, "photo": "missing"}, None
    ok = hashlib.sha256(data).hexdigest() == str(sha).lower()
    return {"photo_sha256": sha, "photo_sha256_verified": ok, "photo": "stored"}, data if ok else None


def _look_section(look: dict[str, Any] | None) -> dict[str, Any] | None:
    if look is None:
        return None
    instances = []
    for inst in look.get("instances") or []:
        if not isinstance(inst, dict):
            continue
        label = inst.get("label") if isinstance(inst.get("label"), dict) else None
        instances.append({**{k: v for k, v in inst.items() if k != "label"},
                          "label": None if label is None else {k: v for k, v in label.items() if k != "raw"}})
    image = look.get("image") if isinstance(look.get("image"), dict) else {}
    return {"look_id": look.get("look_id"), "source": look.get("source"), "image": image,
            "capture_id": (image or {}).get("capture_id"), "instances": instances, "counts": look.get("counts"),
            "pack": look.get("pack"), "expiry": look.get("expiry"), "say": look.get("say"),
            "reasons": look.get("reasons") or []}


def _check(look: dict[str, Any] | None) -> dict[str, Any] | None:
    if look is None:
        return None
    flagged = flagged_instances(look)
    return {"rules": "claims.lines (deterministic; a model's opinion never decides)",
            "counts": look.get("counts"), "pack": look.get("pack"), "expiry": look.get("expiry"),
            "proposal": look.get("proposal"),
            "flagged": [{"n": n, "reason": r} for n, r in sorted(flagged.items())],
            "short_packs": [{"n": n, "pieces_short": p} for n, p in sorted(short_packs(look, flagged).items())],
            "claim_lines": [ln.api() for ln in claim_lines(look)]}


def build_pack(principal: Principal, doc_number: str, year: str | None, *, looks: LookPort) -> Pack:
    with principal_tx(principal) as cur:
        doc = _document(cur, doc_number, year)
        payload = _jsonish(doc["payload"]) or {}
        task_id = str(payload["task_id"]) if payload.get("task_id") else None
        jobs = _jobs(cur, str(doc["id"]))
        events = _events(cur, [j["job_id"] for j in jobs])
        lines = _lines(cur, [str(x) for x in payload.get("line_ids") or []])
        confirm = _confirm(cur, payload)
        look_id = str(payload["look_id"]) if payload.get("look_id") else None
        claim_row = _claim(cur, look_id, task_id)
        if look_id is None and claim_row is not None:
            look_id = str(claim_row["look_id"])
        assistant = _assistant_calls(cur, task_id)
        cur.execute("SELECT mode FROM field.site WHERE id = %s", (doc["site_id"],))
        srow = cur.fetchone()
    look = looks(principal, look_id) if look_id else None
    capture_id = None
    if look is not None and isinstance(look.get("image"), dict):
        capture_id = look["image"].get("capture_id")
    with principal_tx(principal) as cur:
        photo_hashes, photo = _photo(cur, str(capture_id) if capture_id else None)
    models: list[dict[str, Any]] = []
    for m in (look or {}).get("models") or []:
        if isinstance(m, dict):
            models.append({k: m.get(k) for k in ("model", "purpose", "latency_ms", "cost_usd", "outcome")})
    claim = None
    if claim_row is not None:
        cv = claim_view(claim_row, (str(doc["doc_number"]), str(doc["fiscal_year"])))
        claim = {k: cv[k] for k in ("claim_id", "status", "lines", "text", "source", "reasons", "decision",
                                    "decision_reason", "decided_by", "decided_at", "confirmed_by", "confirmed_at",
                                    "confirm_words", "sent", "created_by", "created_at")}
        claim["sent_simulated"] = cv["sent"]
        for m in _jsonish(claim_row["model_calls"]) or []:
            if isinstance(m, dict):
                models.append({k: m.get(k) for k in ("model", "purpose", "latency_ms", "cost_usd", "outcome")})
    models.extend(assistant)
    body: dict[str, Any] = {
        "kind": "scmtips-field.evidence-pack", "version": 1,
        "sample": True,
        "site_mode": (srow[0] if srow else None) or "production",
        "erp": "erp-sim (simulated SAP S/4HANA)",
        "document": {"number": doc["doc_number"], "year": doc["fiscal_year"], "type": doc["doc_type"],
                     "movement_type": doc["movement_type"], "status": doc["status"], "task_id": task_id,
                     "delivery": payload.get("delivery_document"), "posted_lines": lines, "movements": jobs,
                     "events": events},
        "look": _look_section(look),
        "models": models,
        "check": _check(look),
        "confirm": confirm,
        "claim": claim,
        "hashes": photo_hashes,
    }
    body = plain(body)
    body["hashes"]["pack_sha256"] = pack_sha256(body)
    return Pack(body, photo)
