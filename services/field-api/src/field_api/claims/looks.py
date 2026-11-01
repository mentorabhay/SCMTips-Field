"""The look port: how claims and the evidence page read a vision look (M5 contract section 2), without waiting for
stream V.

``get_look(principal, look_id) -> dict | None`` returns the look in the exact section 2 response shape
(``look_id, source, image, instances, counts, pack, expiry, proposal, say, models, reasons``) plus, when the table
has them, ``task_id`` and ``line_id``; None when there is no such look for this tenant (or V's table is not there).

Assumption about stream V's storage (documented in the M5 ledger row M5-X01; to be checked at the V -> X merge):
the look is a row of ``field.vision_look`` with ``id`` = look_id, under forced RLS by tenant (and site), and the
section 2 body is stored EITHER
  (a) as one jsonb column ``body`` (or ``response``) holding the whole response, OR
  (b) as one column per top-level key of section 2 (``source``, ``image``, ``instances``, ``counts``, ``pack``,
      ``expiry``, ``proposal``, ``say``, ``models``, ``reasons``; jsonb or text),
optionally with ``task_id``, ``line_id`` and ``capture_id`` columns. Both are read; (b) wins key by key over (a).
A missing ``image.capture_id`` is filled from a ``capture_id`` column. Nothing is guessed beyond that: a row with
neither a body nor the keys gives an empty look (no instances), so a claim on it has no lines and is refused.

The port is injected (FastAPI dependency ``get_look_port``); tests override it with a test double that lives in
test code only.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Protocol

import psycopg
import structlog

from field_api.auth.jwt import Principal
from field_api.db import principal_tx

logger = structlog.get_logger(__name__)

LOOK_KEYS = ("source", "image", "instances", "counts", "pack", "expiry", "proposal", "say", "models", "reasons")
BODY_COLUMNS = ("body", "response")
LOOK_TABLE = "field.vision_look"


class LookPort(Protocol):
    def __call__(self, principal: Principal, look_id: str) -> dict[str, Any] | None: ...


def _json(v: Any) -> Any:
    if isinstance(v, (bytes, bytearray, memoryview)):
        v = bytes(v).decode("utf-8", "replace")
    if isinstance(v, str):
        s = v.strip()
        if s[:1] in ("{", "["):
            try:
                return json.loads(s)
            except ValueError:
                return v
    return v


def look_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """The section 2 shape from one ``field.vision_look`` row (either storage form, see the module docstring)."""
    body: dict[str, Any] = {}
    for col in BODY_COLUMNS:
        b = _json(row.get(col))
        if isinstance(b, dict):
            body = dict(b)
            break
    out: dict[str, Any] = {k: body.get(k) for k in LOOK_KEYS}
    for k in LOOK_KEYS:
        if k in row and row[k] is not None:
            out[k] = _json(row[k])
    out["look_id"] = str(row.get("id") or body.get("look_id") or "")
    raw_image = out.get("image")
    image: dict[str, Any] = dict(raw_image) if isinstance(raw_image, dict) else {}
    if not image.get("capture_id") and row.get("capture_id"):
        image["capture_id"] = str(row["capture_id"])
    out["image"] = image
    out["instances"] = out["instances"] if isinstance(out.get("instances"), list) else []
    out["counts"] = out["counts"] if isinstance(out.get("counts"), dict) else {}
    out["models"] = out["models"] if isinstance(out.get("models"), list) else []
    out["reasons"] = out["reasons"] if isinstance(out.get("reasons"), list) else []
    for k in ("task_id", "line_id"):
        v = row.get(k) or body.get(k)
        out[k] = str(v) if v else None
    return out


def db_get_look(principal: Principal, look_id: str) -> dict[str, Any] | None:
    """Read the look from ``field.vision_look`` under RLS (the principal's tenant and sites)."""
    try:
        uuid.UUID(look_id)
    except ValueError:
        return None
    try:
        with principal_tx(principal) as cur:
            cur.execute(f"SELECT * FROM {LOOK_TABLE} WHERE id = %s::uuid", (look_id,))
            raw = cur.fetchone()
            cols = [d.name for d in (cur.description or [])]
    except psycopg.errors.UndefinedTable:
        logger.warning("vision_look_table_missing", table=LOOK_TABLE)
        return None
    return look_from_row(dict(zip(cols, raw, strict=True))) if raw else None


def get_look_port() -> LookPort:
    """FastAPI dependency: the database look port (tests override it with a test double)."""
    return db_get_look
