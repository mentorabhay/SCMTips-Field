"""Consent records (API2.06 / FR2.064) on Postgres with RLS (C4; was an in-process store).

The consenting user is the authenticated principal (previously taken from the request body, so
anyone could record consent for someone else). Unknown consent versions are refused (422).
The latest record per (site, user, device) wins; withdrawal is a new record with granted=false.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from field_api.auth.jwt import Principal
from field_api.db import principal_tx
from field_api.deps import require_permission
from field_api.errors import FieldError
from field_api.rows import fetch_dict

router = APIRouter(prefix="/v1/consents", tags=["Consents"])

KNOWN_VERSIONS = frozenset(v.strip() for v in os.getenv("FIELD_CONSENT_VERSIONS", "f1-2026-11,v1").split(","))
ERR_VERSION = FieldError(code="FIELD-CON-422-VERSION", status=422, title="Unknown consent version")


class ConsentRequest(BaseModel):
    site_id: str
    device_id: str
    consent_version: str = "f1-2026-11"
    consent_type: str = Field("site_and_bystander_privacy", max_length=64)
    granted: bool = True


class ConsentRecord(BaseModel):
    id: str
    tenant_id: str
    site_id: str
    user_id: str
    device_id: str
    consent_version: str
    consent_type: str
    granted: bool
    granted_at: str | None = None
    withdrawn_at: str | None = None
    created_at: str


@router.post("", response_model=ConsentRecord, status_code=201)
async def record_consent(
    req: ConsentRequest,
    principal: Principal = Depends(require_permission("field.consent.record")),
) -> ConsentRecord:
    if req.consent_version not in KNOWN_VERSIONS:
        raise ERR_VERSION
    with principal_tx(principal) as cur:
        cur.execute(
            """
            INSERT INTO field.consent_record (tenant_id, site_id, user_id, device_id, consent_version, consent_type,
                   granted, granted_at, withdrawn_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), CASE WHEN %s THEN NULL ELSE NOW() END)
            RETURNING id, tenant_id, site_id, user_id, device_id, consent_version, consent_type, granted,
                      granted_at, withdrawn_at, created_at
            """,
            (principal.tenant_id, req.site_id, principal.id, req.device_id, req.consent_version, req.consent_type,
             req.granted, req.granted),
        )
        row = fetch_dict(cur) or {}
    return ConsentRecord.model_validate(row)


def has_active_consent(cur: Any, site_id: str, user_id: str, device_id: str) -> bool:
    """Latest consent for (site, user, device) is granted and not withdrawn (FR2.064, TC2.154)."""
    cur.execute(
        """
        SELECT granted, withdrawn_at FROM field.consent_record
         WHERE site_id::text = %s AND user_id = %s AND device_id::text = %s
         ORDER BY created_at DESC, id DESC LIMIT 1
        """,
        (site_id, user_id, device_id),
    )
    row = cur.fetchone()
    return bool(row and row[0] is True and row[1] is None)
