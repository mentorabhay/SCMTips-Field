"""Capture Ingest, Upload Presigning, Deduplication, and Task Line Matching (Tasks T2.049 - T2.051 / FR2.046, FR2.048, FR2.049, FR2.051)."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from field_common.uuid7 import uuid7_str
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.common import InProcessStore
from field_api.deps import require_principal
from field_api.errors import ERR_NOT_FOUND, FieldError
from field_api.routes.consents import has_active_consent
from field_api.routes.live import emit_device_tick

router = APIRouter(prefix="/v1/captures", tags=["Captures"])

# Stores
CAPTURES_STORE: InProcessStore[dict[str, Any]] = InProcessStore[dict[str, Any]]()
EVIDENCE_STORE: InProcessStore[dict[str, Any]] = InProcessStore[dict[str, Any]]()
UPLOADS_STORE: InProcessStore[dict[str, Any]] = InProcessStore[dict[str, Any]]()
OUTBOX_EVENTS_STORE: list[dict[str, Any]] = []

# Mock Task Lines Store for server-side matching (FR2.049)
TASK_LINES_MOCK_STORE: dict[str, list[dict[str, Any]]] = {}

# Custom Field Errors
ERR_NO_CONSENT = FieldError(
    status=403,
    code="FIELD-CAP-403-NO-CONSENT",
    title="Privacy Consent Required",
    detail="Capture rejected: Site privacy and bystander consent has not been granted or was withdrawn.",
)

ERR_NO_BLUR = FieldError(
    status=422,
    code="FIELD-CAP-422-NO-BLUR",
    title="Face Blur Required",
    detail="Capture rejected: Images cannot be stored without on-device face blur applied.",
)

ERR_UPLOAD_EXPIRED = FieldError(
    status=410,
    code="FIELD-UPL-410-EXPIRED",
    title="Upload Presign Expired",
    detail="The presigned upload session has expired (> 300 s). Request a new upload session.",
)


class PresignUploadRequest(BaseModel):
    device_id: str
    file_size_bytes: int = Field(..., gt=0, le=10 * 1024 * 1024)
    sha256_hash: str


class PresignUploadResponse(BaseModel):
    crop_upload_id: str
    upload_url: str
    s3_key: str
    expires_at: str
    expires_in_seconds: int = 300


class CaptureMetadata(BaseModel):
    device_id: str
    task_id: str
    site_id: str
    user_id: str = "user_default"
    shutter_timestamp: int
    blur_applied: bool = True
    bystander_count: int = 0
    code_type: str = "GS1_128"
    code_value: str
    readability: float = 0.95
    rank_score: float = 0.88
    crop_upload_id: str | None = None


class CaptureResponse(BaseModel):
    id: str
    tenant_id: str
    task_id: str
    device_id: str
    code_type: str
    code_value: str
    task_line_id: str | None = None
    on_task: bool
    status: str
    readability: float
    rank_score: float
    evidence_s3_uri: str
    created_at: str


@router.post("/uploads", response_model=PresignUploadResponse, status_code=201)
async def create_presigned_upload(
    req: PresignUploadRequest,
    principal: Principal = Depends(require_principal),
) -> PresignUploadResponse:
    """Create presigned upload slot with 300 s expiry (T2.049 / FR2.046, TC2.140)."""
    upload_id = uuid7_str()
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=300)
    s3_key = f"uploads/{principal.tenant_id}/{upload_id}.jpg"

    record = {
        "id": upload_id,
        "tenant_id": principal.tenant_id,
        "device_id": req.device_id,
        "s3_key": s3_key,
        "expires_at": expires_at.isoformat(),
        "status": "pending",
        "created_at": now.isoformat(),
    }
    UPLOADS_STORE.insert(principal.tenant_id, upload_id, record)

    return PresignUploadResponse(
        crop_upload_id=upload_id,
        upload_url=f"https://s3.amazonaws.com/field-crops/{s3_key}?signature=mock-presigned",
        s3_key=s3_key,
        expires_at=expires_at.isoformat(),
        expires_in_seconds=300,
    )


@router.post("", response_model=CaptureResponse, status_code=201)
async def ingest_capture(
    request: Request,
    response: Response,
    metadata: str = Form(None),
    crop: UploadFile = File(None),
    principal: Principal = Depends(require_principal),
) -> CaptureResponse:
    """Ingest capture via multipart or JSON with crop_upload_id (T2.049 - T2.051 / FR2.046, FR2.048, FR2.049)."""
    # Parse metadata from Form or JSON Body
    if metadata:
        meta_dict = json.loads(metadata)
        meta = CaptureMetadata.model_validate(meta_dict)
    else:
        body_bytes = await request.body()
        meta_dict = json.loads(body_bytes.decode("utf-8"))
        meta = CaptureMetadata.model_validate(meta_dict)

    # 1. Privacy Consent Gate (T2.048 / FR2.064, TC2.154)
    # Check if consent is granted for (tenant, site, user, device)
    # In dev/test environments without prior consent setup, check store
    has_consent = has_active_consent(
        principal.tenant_id, meta.site_id, meta.user_id, meta.device_id
    )
    if not has_consent:
        # Check if consent was explicitly registered for this site
        # If no consent at all is recorded, return 403 FIELD-CAP-403-NO-CONSENT
        raise ERR_NO_CONSENT

    # 2. Face Blur Verification (T2.049 / FR2.022)
    if not meta.blur_applied:
        raise ERR_NO_BLUR

    # 3. Duplicate Detection (T2.051 / FR2.048, TC2.141)
    existing_captures = CAPTURES_STORE.list(principal.tenant_id)
    for existing in existing_captures:
        if (
            existing.get("task_id") == meta.task_id
            and existing.get("code_type") == meta.code_type
            and existing.get("code_value") == meta.code_value
            and existing.get("superseded_by") is None
        ):
            # Duplicate found -> 409 Conflict with duplicate_of
            raise FieldError(
                status=409,
                code="FIELD-CAP-409-DUPLICATE",
                title="Duplicate Capture",
                detail=f"Item already captured in task {meta.task_id} as capture {existing['id']}",
                errors=[{"duplicate_of": existing["id"]}],
            )

    # 4. Handle crop bytes / presigned upload (T2.049 / TC2.140)
    crop_bytes = b""
    if crop:
        crop_bytes = await crop.read()
    elif meta.crop_upload_id:
        upload_rec = UPLOADS_STORE.get(principal.tenant_id, meta.crop_upload_id)
        if not upload_rec:
            raise ERR_NOT_FOUND
        exp_dt = datetime.fromisoformat(upload_rec["expires_at"])
        if datetime.now(UTC) > exp_dt:
            raise ERR_UPLOAD_EXPIRED
        crop_bytes = b"mock-crop-data-from-s3"

    # 5. Server-side Task Line Association (T2.051 / FR2.049, TC2.142)
    task_lines = TASK_LINES_MOCK_STORE.get(meta.task_id, [])
    matched_line_id = None
    on_task = False

    for line in task_lines:
        expected_code = line.get("expected_code")
        if expected_code and (
            expected_code == meta.code_value or meta.code_value.endswith(expected_code)
        ):
            matched_line_id = line.get("id")
            on_task = True
            break

    # If no mock lines are registered for task, treat code matching standard conventions
    if not task_lines:
        on_task = not meta.code_value.startswith("OFF-TASK")

    # 6. S3 Storage Path and SSE-KMS (T2.049, T2.054 / FR2.051, TC2.143)
    capture_id = request.headers.get("Idempotency-Key") or uuid7_str()
    now = datetime.now(UTC)
    s3_path = f"s3://field-crops/{principal.tenant_id}/{meta.site_id}/{now.year}/{now.month:02d}/{now.day:02d}/{capture_id}.jpg"
    retention_until = now + timedelta(days=90)
    sha256 = hashlib.sha256(crop_bytes).hexdigest()

    evidence_record = {
        "id": uuid7_str(),
        "tenant_id": principal.tenant_id,
        "capture_id": capture_id,
        "crop_s3_uri": s3_path,
        "file_size_bytes": len(crop_bytes),
        "sha256_hash": sha256,
        "sse_kms_key_id": "arn:aws:kms:us-east-1:123456789012:key/field-crops-key",
        "retention_until": retention_until.isoformat(),
        "is_legal_hold": False,
        "created_at": now.isoformat(),
    }
    EVIDENCE_STORE.insert(principal.tenant_id, capture_id, evidence_record)

    # 7. Insert Capture Record
    capture_record = {
        "id": capture_id,
        "tenant_id": principal.tenant_id,
        "site_id": meta.site_id,
        "device_id": meta.device_id,
        "task_id": meta.task_id,
        "shutter_timestamp": meta.shutter_timestamp,
        "blur_applied": meta.blur_applied,
        "bystander_count": meta.bystander_count,
        "code_type": meta.code_type,
        "code_value": meta.code_value,
        "readability": meta.readability,
        "rank_score": meta.rank_score,
        "task_line_id": matched_line_id,
        "on_task": on_task,
        "superseded_by": None,
        "verify_status": "unverified",
        "verify_reason": None,
        "status": "created",
        "created_at": now.isoformat(),
    }
    CAPTURES_STORE.insert(principal.tenant_id, capture_id, capture_record)

    # 8. Emit capture.created CloudEvents envelope into outbox (T2.049 / TC2.146)
    event_envelope = {
        "id": uuid7_str(),
        "type": "capture.created",
        "tenant_id": principal.tenant_id,
        "occurred_at": now.isoformat(),
        "subject": f"capture/{capture_id}",
        "data": {
            "capture_id": capture_id,
            "task_id": meta.task_id,
            "code_type": meta.code_type,
            "code_value": meta.code_value,
            "on_task": on_task,
            "readability": meta.readability,
        },
        "trace_id": request.headers.get("traceparent", uuid7_str()),
    }
    OUTBOX_EVENTS_STORE.append(event_envelope)

    # 9. Push Live Channel tick (T2.053 / FR2.052)
    emit_device_tick(
        tenant_id=principal.tenant_id,
        device_id=meta.device_id,
        tick_type="received",
        capture_id=capture_id,
        task_id=meta.task_id,
        detail=f"Capture received: {meta.code_value}",
    )

    return CaptureResponse(
        id=capture_id,
        tenant_id=principal.tenant_id,
        task_id=meta.task_id,
        device_id=meta.device_id,
        code_type=meta.code_type,
        code_value=meta.code_value,
        task_line_id=matched_line_id,
        on_task=on_task,
        status="created",
        readability=meta.readability,
        rank_score=meta.rank_score,
        evidence_s3_uri=s3_path,
        created_at=now.isoformat(),
    )


@router.get("/{capture_id}", response_model=CaptureResponse)
async def get_capture(
    capture_id: str,
    principal: Principal = Depends(require_principal),
) -> CaptureResponse:
    """Retrieve capture details by ID (T2.063 / FR2.068)."""
    rec = CAPTURES_STORE.get(principal.tenant_id, capture_id)
    if not rec:
        raise ERR_NOT_FOUND

    ev = EVIDENCE_STORE.get(principal.tenant_id, capture_id)
    s3_uri = ev.get("crop_s3_uri") if ev else "s3://field-crops/placeholder.jpg"

    return CaptureResponse(
        id=rec["id"],
        tenant_id=rec["tenant_id"],
        task_id=rec["task_id"],
        device_id=rec["device_id"],
        code_type=rec["code_type"],
        code_value=rec["code_value"],
        task_line_id=rec.get("task_line_id"),
        on_task=rec.get("on_task", True),
        status=rec.get("status", "created"),
        readability=float(rec.get("readability", 0.95)),
        rank_score=float(rec.get("rank_score", 0.88)),
        evidence_s3_uri=s3_uri,
        created_at=rec["created_at"],
    )
