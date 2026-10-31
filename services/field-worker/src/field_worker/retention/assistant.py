"""Retention of Field Assistant content (owner amendment A-03: voice text and photos kept 30 days).

Daily, the worker calls field.worker_purge_assistant_content(days) (SECURITY DEFINER, migration field_0061; the
worker role has no RLS bypass). It clears heard / said / photo_ref and tool-call arguments of turns older than
FIELD_ASSISTANT_RETENTION_DAYS (default 30), keeps the rest of the record (event, actions, cost, latency, task),
and returns the photo refs no turn uses any more; their files are then deleted from the photo store.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import psycopg
import structlog
from field_api.assistant.photos import AssistantPhotoStore
from field_api.crops import CropStoreError

logger = structlog.get_logger(__name__)

DEFAULT_RETENTION_DAYS = 30


def retention_days() -> int:
    days = int(os.getenv("FIELD_ASSISTANT_RETENTION_DAYS", str(DEFAULT_RETENTION_DAYS)))
    if days < 1:
        raise ValueError("FIELD_ASSISTANT_RETENTION_DAYS must be >= 1")
    return days


@dataclass(frozen=True)
class PurgeResult:
    photos_released: int
    photos_deleted: int


def purge_assistant_content(db_url: str, days: int | None = None,
                            store: AssistantPhotoStore | None = None) -> PurgeResult:
    d = retention_days() if days is None else days
    with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM field.worker_purge_assistant_content(%s)", (d,))
        refs = [str(r[0]) for r in cur.fetchall()]
    photos = store or AssistantPhotoStore()
    deleted = 0
    for ref in refs:
        try:
            deleted += 1 if photos.delete(ref) else 0
        except (CropStoreError, OSError):
            logger.exception("assistant_photo_delete_failed")
    result = PurgeResult(len(refs), deleted)
    logger.info("assistant_retention_purge", days=d, photos_released=result.photos_released,
                photos_deleted=result.photos_deleted)
    return result
