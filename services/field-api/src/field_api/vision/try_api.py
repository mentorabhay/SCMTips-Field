"""Try-a-look routes for the console's /try page (M5-W01; docs/design/M5_CONTRACT.md §2 "Try looks", §6).

POST /v1/try/looks                 (field.try.use; Idempotency-Key)   multipart/form-data:
     photo  the JPEG or PNG file (<= 5 MB; the browser scales it to <= 1600 px first, field-api does it again)
     look   JSON {"case": "grocery"|"pharmacy", "expected_units": int, "pieces_per_unit"?: int, "window_days"?: int,
                  "object"?: str}
  -> 200 the look body of GET /v1/vision/looks/{id} (``final`` false while the labels are read, M5-S01) plus
     ``kind: "try"`` and ``try`` {sample, posts: false, photo_url, photo_expires_at, photo_kept_hours: 24};
     ``image.faces_blurred`` = faces field-api pixelated before storing the photo and before any model call.
     413 FIELD-TRY-413-SIZE, 415 FIELD-TRY-415-TYPE, 422 FIELD-TRY-422-FIELDS / -PHOTO, 429 FIELD-TRY-429-RATE
     (Retry-After). Budget or model refusals are not errors: the look answers ``source: "rules"`` with the reason.
GET  /v1/try/looks/{look_id}       (field.try.use) -> 200 the same body as it is now (poll every 1 s until ``final``);
     404 FIELD-TRY-404-LOOK for another principal's look, a task look or an unknown id
GET  /v1/try/looks/{look_id}/photo (field.try.use) -> image/jpeg, the photo as stored (faces pixelated); 410 after 24 h
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartException

from field_api.auth.jwt import Principal
from field_api.deps import require_permission
from field_api.errors import FieldError
from field_api.vision.ports import VisionPorts
from field_api.vision.try_look import (
    ERR_FIELDS,
    ERR_SIZE,
    MAX_UPLOAD_BYTES,
    TryIn,
    create_try_look,
    get_try_look,
    get_try_vision_ports,
    try_photo,
)

router = APIRouter(prefix="/v1/try", tags=["Try a look (M5)"])

FORM_SLACK = 64 * 1024  # multipart framing and the look part on top of the photo


def _request_body() -> dict[str, Any]:
    """The multipart body for the OpenAPI document (the route reads the form itself, after a size check)."""
    return {
        "required": True,
        "content": {"multipart/form-data": {"schema": {
            "type": "object", "required": ["photo", "look"],
            "properties": {
                "photo": {"type": "string", "format": "binary", "description": "JPEG or PNG, at most 5 MB"},
                "look": {"type": "string", "description": "JSON of TryIn",
                         "contentMediaType": "application/json", "contentSchema": TryIn.model_json_schema()},
            }}}},
    }


async def _form_parts(request: Request) -> tuple[TryIn, bytes]:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES + FORM_SLACK:
        raise ERR_SIZE  # refused before the body is read
    try:
        form = await request.form(max_files=1, max_fields=2, max_part_size=16 * 1024)
    except (MultiPartException, StarletteHTTPException) as e:  # a broken or oversized form
        raise FieldError(status=422, code=ERR_FIELDS.code, title=ERR_FIELDS.title, detail=str(e)[:300]) from None
    photo, raw = form.get("photo"), form.get("look")
    if not isinstance(photo, UploadFile) or not isinstance(raw, str):
        raise FieldError(status=422, code=ERR_FIELDS.code, title=ERR_FIELDS.title,
                         detail="multipart parts 'photo' (a file) and 'look' (JSON) are required")
    try:
        body = TryIn.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as e:
        raise FieldError(status=422, code=ERR_FIELDS.code, title=ERR_FIELDS.title, detail=str(e)[:500]) from None
    data = await photo.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ERR_SIZE
    return body, data


@router.post("/looks", status_code=200, openapi_extra={"requestBody": _request_body()})
async def post_try_look(
    request: Request,
    background: BackgroundTasks,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(require_permission("field.try.use")),
    ports: VisionPorts = Depends(get_try_vision_ports),
) -> dict[str, Any]:
    body, data = await _form_parts(request)
    return await run_in_threadpool(create_try_look, principal, body, data, idempotency_key, ports,
                                   defer=background.add_task)


@router.get("/looks/{look_id}")
def read_try_look(
    look_id: str,
    principal: Principal = Depends(require_permission("field.try.use")),
) -> dict[str, Any]:
    return get_try_look(principal, look_id)


@router.get("/looks/{look_id}/photo", response_class=Response,
            responses={200: {"content": {"image/jpeg": {}}, "description": "the stored photo, faces pixelated"}})
def read_try_photo(
    look_id: str,
    principal: Principal = Depends(require_permission("field.try.use")),
) -> Response:
    return Response(content=try_photo(principal, look_id), media_type="image/jpeg",
                    headers={"Cache-Control": "private, no-store"})
