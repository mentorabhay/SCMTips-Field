"""Try looks (M5-W01): the console's "Try a look" page runs the real look engine on a SAMPLE or uploaded photo.

No task, line, capture, posting or claim: the look row is ``kind = 'try'`` (migration field_0067_m5_try), read only by
its own principal through GET /v1/try/looks/{id}, never by ``vision.service.get_look`` (so claims, evidence packs and
receipts cannot use it). Stages a-f, the two-step answer (M5-S01) and the number-checked ``say`` are the same code as
the phone's look (``vision.service.run_look``).

Server-side guard rails (all enforced here, whatever the browser does):
- JPEG or PNG only, by the file's own bytes (415 FIELD-TRY-415-TYPE); at most 5 MB (413 FIELD-TRY-413-SIZE);
- faces: the browser has no blur gate, so field-api pixelates every face it finds (vision.faces) before the photo is
  stored and before any model call; ``image.faces_blurred`` says how many;
- the photo is scaled to at most 1600 px on its long side (as the phone's look photo, M5-P01), re-encoded as JPEG;
- FIELD_TRY_LOOKS_PER_HOUR (default 10) try looks per principal per rolling hour (429 FIELD-TRY-429-RATE with
  Retry-After); an Idempotency-Key replay is not counted again;
- model calls go through the budget guard with the ``try`` scope: AI_TRY_DAILY_CAP_USD (default 3) per tenant per UTC
  day on top of every other cap. A refused call degrades the look to ``source: rules`` (never an error);
- the photo and the label text are kept 24 hours (``try.photo_expires_at``); the worker's try purge removes them.
"""

from __future__ import annotations

import hashlib
import io
import os
import time
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from field_api.ai.budget import BudgetGuard
from field_api.auth.jwt import Principal
from field_api.crops import MAX_CROP_BYTES, LocalCropStore
from field_api.db import principal_tx
from field_api.errors import FieldError
from field_api.vision import settings
from field_api.vision.faces import FaceFinder, blur_faces
from field_api.vision.image import MAX_PIXELS, Capture, ImageUnreadable
from field_api.vision.ports import VisionPorts
from field_api.vision.reconcile import Expectation
from field_api.vision.service import (
    DEFAULT_OBJECT,
    LOOK_COLS,
    Defer,
    LookContext,
    LookTarget,
    _settle_overdue,
    look_body,
    run_look,
    vision_ports,
)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
LONG_SIDE = 1600  # as the phone's look photo (M5-P01)
PHOTO_TTL = timedelta(hours=24)
JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
RATE_ENV = "FIELD_TRY_LOOKS_PER_HOUR"
RATE_DEFAULT = 10

ERR_TYPE = FieldError(status=415, code="FIELD-TRY-415-TYPE", title="The photo must be a JPEG or PNG image")
ERR_SIZE = FieldError(status=413, code="FIELD-TRY-413-SIZE", title="The photo is larger than 5 MB")
ERR_PHOTO = FieldError(status=422, code="FIELD-TRY-422-PHOTO", title="The photo could not be read")
ERR_FIELDS = FieldError(status=422, code="FIELD-TRY-422-FIELDS", title="The look fields are not valid")
ERR_LOOK = FieldError(status=404, code="FIELD-TRY-404-LOOK", title="Try look not found")
ERR_GONE = FieldError(status=410, code="FIELD-TRY-410-PHOTO-EXPIRED", title="The photo was deleted after 24 hours")


class TryIn(BaseModel):
    """The ``look`` part of POST /v1/try/looks (JSON)."""

    case: Literal["grocery", "pharmacy"]
    expected_units: int = Field(ge=1, le=200, description="units the delivery should have (C1: 8 packs, C2: 5 boxes)")
    pieces_per_unit: int | None = Field(None, ge=1, le=1000, description="C1: pieces each pack should hold (6)")
    window_days: int | None = Field(None, ge=0, le=3650, description="C2: expiring within this many days is flagged")
    object: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z -]{0,39}$",
                               description="the noun to count; default pack (C1) or box (C2)")


class TryPhotoStore(LocalCropStore):
    """Try photos, content-addressed under FIELD_TRY_PHOTO_DIR (default ./var/try-photos), kept 24 hours."""

    def __init__(self, root: str | None = None) -> None:
        super().__init__(root or os.getenv("FIELD_TRY_PHOTO_DIR") or "var/try-photos")

    def delete(self, uri: str) -> bool:
        """Remove one stored photo; True if a file was deleted. Refuses URIs outside the store."""
        p: Path = self._path(uri)
        if p.exists():
            p.unlink()
            return True
        return False


def get_try_vision_ports() -> VisionPorts:
    """FastAPI dependency: the look's production adapters over a budget guard with the ``try`` scope."""
    return vision_ports(BudgetGuard(scope="try"))


def rate_per_hour() -> int:
    raw = os.getenv(RATE_ENV, "").strip()
    return max(1, min(1000, int(raw))) if raw.isdigit() else RATE_DEFAULT


# --------------------------------------------------------------------------- the photo
def check_upload(data: bytes) -> str:
    """'jpeg' or 'png' by the file's own bytes; 413 above 5 MB, 415 for anything else (the declared type is ignored)."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ERR_SIZE
    if data.startswith(JPEG_MAGIC):
        return "jpeg"
    if data.startswith(PNG_MAGIC):
        return "png"
    raise ERR_TYPE


def _open(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        w, h = img.size
        if w <= 0 or h <= 0 or w * h > MAX_PIXELS:
            raise ImageUnreadable("image size out of range")
        img.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as e:
        raise ImageUnreadable(type(e).__name__) from None
    return img


def readable(data: bytes) -> None:
    """Refuses (422) a file that is not a decodable image before a rate slot is used."""
    try:
        _open(data)
    except ImageUnreadable:
        raise ERR_PHOTO from None


def prepare_photo(data: bytes, finder: FaceFinder | None = None) -> tuple[Capture, int]:
    """The photo as it is stored and seen by the models: upright (EXIF), RGB, at most 1600 px on its long side, every
    face found pixelated, JPEG at most 1 MB (the look's capture limit). Returns it and the number of faces blurred."""
    img = ImageOps.exif_transpose(_open(data))
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.split()[-1])
        img = flat
    img = img.convert("RGB")
    img.thumbnail((LONG_SIDE, LONG_SIDE), Image.Resampling.LANCZOS)  # keeps the aspect, never scales up
    img, faces = blur_faces(img, finder)
    for quality in (85, 78, 70, 62, 55):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        if buf.tell() <= MAX_CROP_BYTES:
            return Capture(buf.getvalue(), img.width, img.height), faces
    raise ERR_PHOTO  # pragma: no cover - a 1600 px JPEG at quality 55 is far below 1 MB


# --------------------------------------------------------------------------- rate
def take_slot(principal: Principal) -> None:
    """One try look for this principal in the rolling hour, or 429 FIELD-TRY-429-RATE with Retry-After (seconds until
    the oldest look of the hour leaves it). Serialised per principal, so parallel uploads cannot overrun the limit."""
    limit = rate_per_hour()
    with principal_tx(principal) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"try:{principal.tenant_id}:{principal.id}",))
        cur.execute("SELECT count(*), ceil(extract(epoch FROM (min(created_at) + interval '1 hour' - NOW())))"
                    " FROM field.try_look_slot WHERE principal_id = %s AND created_at > NOW() - interval '1 hour'",
                    (principal.id,))
        row = cur.fetchone()
        used = int(row[0]) if row else 0
        if used >= limit:
            wait = max(1, int(row[1])) if row and row[1] is not None else 60
            raise FieldError(status=429, code="FIELD-TRY-429-RATE", title="Too many try looks",
                             detail=f"{limit} try looks per hour; try again in {wait} seconds.",
                             headers={"Retry-After": str(wait)})
        cur.execute("INSERT INTO field.try_look_slot (tenant_id, principal_id) VALUES (%s, %s)",
                    (principal.tenant_id, principal.id))


# --------------------------------------------------------------------------- the look
TRY_COLS = LOOK_COLS + ", photo_uri, photo_expires_at, photo_purged_at"
_OWN_SQL = ("SELECT " + TRY_COLS + " FROM field.vision_look"
            " WHERE id = %s::uuid AND kind = 'try' AND principal_id = %s")  # a fixed column list


def try_body(row: tuple[Any, ...]) -> dict[str, Any]:
    """The look body (contract §2, as GET /v1/vision/looks answers) plus ``kind`` and ``try`` (SAMPLE, nothing
    posted, where the stored photo is and until when)."""
    n = len(LOOK_COLS.split(","))
    body = look_body(row[:n])
    photo_uri, expires, purged = row[n:n + 3]
    alive = photo_uri is not None and purged is None and expires > datetime.now(UTC)
    body["kind"] = "try"
    body["try"] = {"sample": True, "posts": False,
                   "photo_url": f"/v1/try/looks/{body['look_id']}/photo" if alive else None,
                   "photo_expires_at": expires.isoformat(), "photo_kept_hours": int(PHOTO_TTL.total_seconds() // 3600)}
    return body


def _own(cur: Any, look_id: str, principal: Principal) -> tuple[Any, ...] | None:
    try:
        uuid.UUID(look_id)
    except ValueError:
        return None
    _settle_overdue(cur, "id::text", look_id)
    cur.execute(_OWN_SQL, (look_id, principal.id))
    row: tuple[Any, ...] | None = cur.fetchone()
    return row


def get_try_look(principal: Principal, look_id: str) -> dict[str, Any]:
    """The caller's own try look as it is now (poll it until ``final``); 404 for anyone else's or a task look."""
    with principal_tx(principal) as cur:
        row = _own(cur, look_id, principal)
    if row is None:
        raise ERR_LOOK
    return try_body(row)


def try_photo(principal: Principal, look_id: str) -> bytes:
    """The stored (face-blurred) photo of the caller's own try look; 410 once it is past its 24 hours."""
    with principal_tx(principal) as cur:
        row = _own(cur, look_id, principal)
    if row is None:
        raise ERR_LOOK
    n = len(LOOK_COLS.split(","))
    uri, expires, purged = row[n:n + 3]
    if uri is None or purged is not None or expires <= datetime.now(UTC):
        raise ERR_GONE
    try:
        return TryPhotoStore().get(str(uri))
    except OSError:
        raise ERR_GONE from None


def _replay(principal: Principal, key: str) -> dict[str, Any] | None:
    with principal_tx(principal) as cur:
        cur.execute("SELECT id FROM field.vision_look WHERE idempotency_key = %s AND kind = 'try' AND principal_id = %s",
                    (key, principal.id))
        hit = cur.fetchone()
        row = _own(cur, str(hit[0]), principal) if hit else None
    return try_body(row) if row else None


def expectation(body: TryIn) -> Expectation:
    noun = (body.object or DEFAULT_OBJECT[body.case]).strip().lower()
    window = body.window_days if body.window_days is not None else settings.expiry_window_days()
    return Expectation(case=body.case, object_noun=noun, expected_units=body.expected_units,
                       expected_pieces_per_unit=body.pieces_per_unit if body.case == "grocery" else None,
                       window_days=window if body.case == "pharmacy" else settings.expiry_window_days())


def create_try_look(principal: Principal, body: TryIn, data: bytes, idempotency_key: str, ports: VisionPorts,
                    today: Callable[[], date] = lambda: datetime.now(UTC).date(), defer: Defer | None = None,
                    finder: FaceFinder | None = None) -> dict[str, Any]:
    """A try look: type and size checked, rate slot taken, faces pixelated, photo stored for 24 h, then the real
    look engine (one or two steps). Returns the try body (``final`` false while the labels are read)."""
    t0 = time.perf_counter()
    check_upload(data)
    again = _replay(principal, idempotency_key)
    if again is not None:
        return again
    readable(data)
    take_slot(principal)
    try:
        cap, faces = prepare_photo(data, finder)
    except ImageUnreadable:
        raise ERR_PHOTO from None
    uri = TryPhotoStore().put(principal.tenant_id, cap.jpeg)
    target = LookTarget("try", None, None, photo_uri=uri, photo_sha256=hashlib.sha256(cap.jpeg).hexdigest(),
                        photo_expires_at=datetime.now(UTC) + PHOTO_TTL)
    lc = LookContext(None, "try", None, expectation(body), None)
    first = run_look(principal, target, lc, cap, [], idempotency_key, ports, today, defer, t0,
                     image_extra={"faces_blurred": faces})
    return get_try_look(principal, str(first["look_id"]))
