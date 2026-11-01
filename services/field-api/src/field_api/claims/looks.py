"""The look port: how claims and the evidence page read a vision look (M5 contract section 2).

``get_look(principal, look_id) -> dict | None`` returns the look in the section 2 response shape (``look_id,
source, image, instances, counts, pack, expiry, proposal, say, models, reasons``) plus ``task_id``, ``line_id`` and
``final`` (M5-S01: false while the look's label read is still running; a body without it is final);
None when there is no such look for this principal (tenant RLS and site scope) or the id is not a uuid.

The database port reads stream V's look through ``field_api.vision.service.get_look`` (one column per top-level
key of ``field.vision_look``, assembled by ``look_body`` over ``LOOK_COLS``), so the claim and the evidence pack see
exactly what ``GET /v1/vision/looks/{id}`` answers. ``look_from_body`` only normalises that body for the claims
code (lists and dicts never None, ``image.capture_id`` filled from the row's ``capture_id``); nothing is guessed.

The port is injected (FastAPI dependency ``get_look_port``); the claims unit tests override it with a test double
that lives in test code only, and tests/claims/test_look_port.py runs the database port on a real
``field.vision_look`` row.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from field_api.auth.jwt import Principal
from field_api.errors import FieldError
from field_api.vision import service as vision

LOOK_KEYS = ("source", "image", "instances", "counts", "pack", "expiry", "proposal", "say", "models", "reasons")


class LookPort(Protocol):
    def __call__(self, principal: Principal, look_id: str) -> dict[str, Any] | None: ...


def look_from_body(body: dict[str, Any]) -> dict[str, Any]:
    """The section 2 shape the claims code reads, from stream V's look body (``vision.service.look_body``)."""
    out: dict[str, Any] = {k: body.get(k) for k in LOOK_KEYS}
    out["look_id"] = str(body.get("look_id") or "")
    raw_image = out.get("image")
    image: dict[str, Any] = dict(raw_image) if isinstance(raw_image, dict) else {}
    if not image.get("capture_id") and body.get("capture_id"):
        image["capture_id"] = str(body["capture_id"])
    out["image"] = image
    out["instances"] = out["instances"] if isinstance(out.get("instances"), list) else []
    out["counts"] = out["counts"] if isinstance(out.get("counts"), dict) else {}
    out["models"] = out["models"] if isinstance(out.get("models"), list) else []
    out["reasons"] = out["reasons"] if isinstance(out.get("reasons"), list) else []
    for k in ("task_id", "line_id"):
        v = body.get(k)
        out[k] = str(v) if v else None
    out["final"] = body.get("final") is not False  # M5-S01: false while the look's labels are being read
    return out


def db_get_look(principal: Principal, look_id: str) -> dict[str, Any] | None:
    """Read the look through stream V's service (``field.vision_look`` under the principal's RLS)."""
    try:
        uuid.UUID(look_id)
    except ValueError:
        return None
    try:
        body = vision.get_look(principal, look_id)
    except FieldError as e:
        if e.code == vision.ERR_LOOK.code:
            return None
        raise
    return look_from_body(body)


def get_look_port() -> LookPort:
    """FastAPI dependency: the database look port (tests override it with a test double)."""
    return db_get_look
