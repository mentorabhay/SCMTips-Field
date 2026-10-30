"""Capture ingest (API2.08-2.11 / T2.049-T2.051) on Postgres + a real crop store (C4).

Replaces in-process stores, a fake S3 presign URL, a fabricated KMS key ARN, placeholder crop bytes
and a test-only task-line dictionary.

Flow: POST /v1/captures/uploads -> PUT /v1/captures/uploads/{id} (crop bytes, sha256 verified,
<= 1 MB, 300 s) -> POST /v1/captures (metadata + crop_upload_id), or one multipart POST with the
crop. Gates: device binding, site consent (FR2.064), on-device blur (FR2.022), duplicate per
(task, code type, code) -> 409 with duplicate_of (FR2.048). Server-side association to a task line by
SSCC, GTIN (GS1 AI 01), material number or expected serial (FR2.049). Emits capture.created to the
outbox and a ``received`` live tick, in the same transaction.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import Response as RawResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, ValidationError

from field_api.auth.jwt import Principal
from field_api.crops import MAX_CROP_BYTES, CropStoreError, crop_store
from field_api.db import principal_tx
from field_api.deps import require_permission
from field_api.errors import FieldError
from field_api.routes.consents import has_active_consent
from field_api.routes.live import emit_device_tick
from field_api.rows import fetch_dict

router = APIRouter(prefix="/v1/captures", tags=["Captures"])

UPLOAD_TTL = timedelta(seconds=300)
RETENTION = timedelta(days=90)
ERR_NO_CONSENT = FieldError(status=403, code="FIELD-CAP-403-NO-CONSENT", title="Privacy consent required")
ERR_NO_BLUR = FieldError(status=422, code="FIELD-CAP-422-BLUR-MISSING", title="Face blur required")
ERR_UPLOAD_EXPIRED = FieldError(status=410, code="FIELD-UPL-410-EXPIRED", title="Upload session expired")
ERR_TOO_LARGE = FieldError(status=413, code="FIELD-CAP-413-CROP-TOO-LARGE", title="Crop above 1 MB")
ERR_SHA = FieldError(status=422, code="FIELD-CAP-422-SHA256", title="Crop sha256 mismatch")
ERR_CAP_404 = FieldError(status=404, code="FIELD-CAP-404", title="Capture not found or out of scope")
ERR_UPL_404 = FieldError(status=404, code="FIELD-UPL-404", title="Upload not found")
ERR_DEVICE = FieldError(status=403, code="FIELD-AUTH-401-BINDING", title="Device binding mismatch")
GTIN_RE = re.compile(r"(?:^|\(01\)|^01)(\d{14})")


class UploadRequest(BaseModel):
    device_id: str
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    bytes: int = Field(gt=0)
    content_type: str = Field("image/jpeg", pattern=r"^image/(jpeg|png|webp)$")


class CaptureMetadata(BaseModel):
    device_id: str
    task_id: str | None = None
    site_id: str
    shutter_timestamp: int = Field(ge=0)
    blur_applied: bool
    bystander_count: int = Field(0, ge=0)
    code_type: str = Field(max_length=32)
    code_value: str = Field(min_length=1, max_length=256)
    object_class: str | None = Field(None, max_length=32)
    confidence: float | None = Field(None, ge=0, le=1)
    readability: float = Field(0.0, ge=0, le=1)
    rank_score: float = Field(0.0, ge=0, le=1)
    client_seq: int | None = None
    look_id: str | None = None
    location_id: str | None = None
    crop_upload_id: str | None = None


def _bound_device(principal: Principal, device_id: str) -> None:
    if principal.device_id and principal.device_id != device_id:
        raise ERR_DEVICE


@router.post("/uploads", status_code=201)
async def create_upload(
    req: UploadRequest,
    principal: Principal = Depends(require_permission("field.capture.create")),
) -> dict[str, Any]:
    _bound_device(principal, req.device_id)
    if req.bytes > MAX_CROP_BYTES:
        raise ERR_TOO_LARGE
    expires = datetime.now(UTC) + UPLOAD_TTL
    with principal_tx(principal) as cur:
        cur.execute(
            "INSERT INTO field.capture_upload (tenant_id, device_id, s3_key, expires_at, status)"
            " VALUES (%s, %s, %s, %s, 'pending') RETURNING id",
            (principal.tenant_id, req.device_id, f"pending:{req.sha256.lower()}", expires),
        )
        upload_id = str(cur.fetchone()[0])
    return {"upload_id": upload_id, "put_url": f"/v1/captures/uploads/{upload_id}", "method": "PUT",
            "expires_at": expires.isoformat()}


@router.put("/uploads/{upload_id}", status_code=204)
async def put_upload(
    upload_id: str,
    request: Request,
    principal: Principal = Depends(require_permission("field.capture.create")),
) -> RawResponse:
    data = await request.body()
    if len(data) > MAX_CROP_BYTES:
        raise ERR_TOO_LARGE
    with principal_tx(principal) as cur:
        cur.execute("SELECT s3_key, expires_at, status, device_id FROM field.capture_upload WHERE id = %s::uuid"
                    " FOR UPDATE", (upload_id,))
        row = cur.fetchone()
        if not row:
            raise ERR_UPL_404
        key, expires, status, device_id = row
        _bound_device(principal, str(device_id))
        if datetime.now(UTC) > expires:
            raise ERR_UPLOAD_EXPIRED
        try:
            uri = crop_store().put(principal.tenant_id, data, key.removeprefix("pending:") if status == "pending" else None)
        except CropStoreError as e:
            raise ERR_SHA if str(e) == "sha256_mismatch" else ERR_TOO_LARGE from e
        cur.execute("UPDATE field.capture_upload SET s3_key = %s, status = 'completed', uploaded_at = NOW()"
                    " WHERE id = %s::uuid", (uri, upload_id))
    return RawResponse(status_code=204)


def _match_line(cur: Any, task_id: str | None, code: str) -> str | None:
    if not task_id:
        return None
    gtin = GTIN_RE.search(code)
    cur.execute(
        """
        SELECT l.id FROM field.task_line l LEFT JOIN field.material m ON m.id = l.material_id
         WHERE l.task_id = %s::uuid AND l.status NOT IN ('posted', 'cancelled')
           AND (l.sscc = %s OR m.erp_material_no = %s OR l.expected_serial = %s OR (%s::text IS NOT NULL AND m.gtin = %s))
         ORDER BY l.line_no LIMIT 1
        """,
        (task_id, code, code, code, gtin.group(1) if gtin else None, gtin.group(1) if gtin else None),
    )
    row = cur.fetchone()
    return str(row[0]) if row else None


CAP_COLS = ("id, tenant_id, site_id, device_id, task_id, task_line_id, code_type, code_value, on_task, status,"
            " readability, rank_score, verify_status, blur_applied, bystander_count, shutter_timestamp, created_at")


@router.post("", status_code=201)
async def ingest_capture(
    request: Request,
    metadata: str | None = Form(None),
    crop: UploadFile | None = File(None),
    principal: Principal = Depends(require_permission("field.capture.create")),
) -> dict[str, Any]:
    try:
        raw = json.loads(metadata) if metadata else json.loads((await request.body()) or b"{}")
        meta = CaptureMetadata.model_validate(raw)
    except (ValueError, ValidationError) as e:
        raise FieldError(status=422, code="FIELD-HTTP-422-VALIDATION", title="Invalid capture metadata",
                         detail=str(e)[:500]) from e
    _bound_device(principal, meta.device_id)
    if not meta.blur_applied:
        raise ERR_NO_BLUR
    crop_bytes = await crop.read() if crop else None
    with principal_tx(principal) as cur:
        if not has_active_consent(cur, meta.site_id, principal.id, meta.device_id):
            raise ERR_NO_CONSENT
        if meta.task_id:
            cur.execute(
                "SELECT id FROM field.capture WHERE task_id = %s::uuid AND code_type = %s AND code_value = %s"
                " AND superseded_by IS NULL LIMIT 1",
                (meta.task_id, meta.code_type, meta.code_value),
            )
            dup = cur.fetchone()
            if dup:
                raise FieldError(status=409, code="FIELD-CAP-409-DUPLICATE", title="Duplicate capture",
                                 detail=f"already captured as {dup[0]}", errors=[{"duplicate_of": str(dup[0])}])
        uri: str | None = None
        if crop_bytes is not None:
            try:
                uri = crop_store().put(principal.tenant_id, crop_bytes)
            except CropStoreError as e:
                raise ERR_TOO_LARGE from e
        elif meta.crop_upload_id:
            cur.execute("SELECT s3_key, status, expires_at FROM field.capture_upload WHERE id = %s::uuid",
                        (meta.crop_upload_id,))
            up = cur.fetchone()
            if not up:
                raise ERR_UPL_404
            if up[1] != "completed":
                raise ERR_UPLOAD_EXPIRED if datetime.now(UTC) > up[2] else FieldError(
                    status=409, code="FIELD-UPL-409-NOT-UPLOADED", title="Crop bytes not uploaded yet")
            uri = up[0]
        line_id = _match_line(cur, meta.task_id, meta.code_value)
        on_task = line_id is not None if meta.task_id else False
        cur.execute(
            f"""
            INSERT INTO field.capture (tenant_id, site_id, device_id, task_id, task_line_id, code_type, code_value,
                   on_task, status, readability, rank_score, confidence, verify_status, blur_applied, bystander_count,
                   shutter_timestamp, location_id, parsed_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'received', %s, %s, %s, 'not_needed', %s, %s, %s, %s, %s)
            RETURNING {CAP_COLS}
            """,  # noqa: S608
            (principal.tenant_id, meta.site_id, meta.device_id, meta.task_id, line_id, meta.code_type,
             meta.code_value, on_task, meta.readability, meta.rank_score,
             meta.confidence if meta.confidence is not None else meta.readability, meta.blur_applied,
             meta.bystander_count, meta.shutter_timestamp, meta.location_id,
             Jsonb({"object_class": meta.object_class, "client_seq": meta.client_seq, "look_id": meta.look_id})),
        )
        cap = fetch_dict(cur) or {}
        if uri:
            data = crop_bytes if crop_bytes is not None else crop_store().get(uri)
            cur.execute(
                "INSERT INTO field.capture_evidence (tenant_id, capture_id, crop_s3_uri, file_size_bytes, sha256_hash,"
                " retention_until, consent_ref) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (principal.tenant_id, cap["id"], uri, len(data), hashlib.sha256(data).hexdigest(),
                 datetime.now(UTC) + RETENTION, "consent:latest"),
            )
        cur.execute(
            "INSERT INTO field.outbox (tenant_id, event_type, aggregate_id, payload) VALUES (%s, 'capture.created', %s, %s)",
            (principal.tenant_id, cap["id"], Jsonb({"type": "capture.created", "subject": f"capture/{cap['id']}",
                                                     "data": {"capture_id": cap["id"], "task_id": meta.task_id,
                                                              "task_line_id": line_id, "on_task": on_task},
                                                     "trace": request.headers.get("traceparent")})),
        )
        emit_device_tick(cur, principal.tenant_id, meta.device_id, "received",
                         {"subject_id": cap["id"], "task_line_id": line_id, "on_task": on_task})
    return {"id": cap["id"], "task_line_id": line_id, "on_task": on_task, "verify_status": "not_needed",
            "received_at": cap["created_at"], "evidence_uri": uri}


@router.get("/{capture_id}")
async def get_capture(
    capture_id: str,
    principal: Principal = Depends(require_permission("field.capture.read")),
) -> dict[str, Any]:
    with principal_tx(principal) as cur:
        cur.execute(f"SELECT {CAP_COLS} FROM field.capture WHERE id = %s::uuid", (capture_id,))  # noqa: S608
        cap = fetch_dict(cur)
        if not cap:
            raise ERR_CAP_404
        cur.execute("SELECT id, transcript, confidence, intent, is_accepted FROM field.voice_event"
                    " WHERE capture_id = %s::uuid ORDER BY created_at", (capture_id,))
        voice = [{"id": str(r[0]), "transcript": r[1], "confidence": float(r[2]), "intent": r[3], "accepted": r[4]}
                 for r in cur.fetchall()]
    return {**cap, "code": cap["code_value"], "voice_events": voice}


@router.get("/{capture_id}/crop")
async def get_crop(
    capture_id: str,
    principal: Principal = Depends(require_permission("field.evidence.read")),
) -> Response:
    with principal_tx(principal) as cur:
        cur.execute("SELECT crop_s3_uri, retention_until, is_legal_hold FROM field.capture_evidence"
                    " WHERE capture_id = %s::uuid ORDER BY created_at DESC LIMIT 1", (capture_id,))
        ev = cur.fetchone()
    if not ev:
        raise FieldError(status=404, code="FIELD-CAP-404-CROP-WITHHELD", title="No crop for this capture")
    uri, until, hold = ev
    store = crop_store()
    if (datetime.now(UTC) > until and not hold) or not store.exists(uri):
        raise FieldError(status=410, code="FIELD-CAP-410-CROP-EXPIRED", title="Crop deleted by retention")
    return Response(content=store.get(uri), media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})
