"""Retention of try looks (M5-W01, the console's "Try a look" page): the photo and its label text are kept 24 hours.

Every PURGE_S (10 minutes, with the idempotency purge) the worker calls field.worker_purge_try_looks() (SECURITY
DEFINER, migration field_0067_m5_try; the worker role has no RLS bypass). It clears ``photo_uri`` and ``raw_labels`` of
try looks past ``photo_expires_at`` (created + 24 h), stamps ``photo_purged_at``, deletes rate-limit slots older than
a day, and returns the photo files no look refers to any more; they are then deleted from the try photo store
(FIELD_TRY_PHOTO_DIR). The rest of the row (counts, model calls, cost) stays.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
import structlog
from field_api.crops import CropStoreError
from field_api.vision.try_look import TryPhotoStore

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class TryPurgeResult:
    photos_released: int
    photos_deleted: int


def purge_try_looks(db_url: str, store: TryPhotoStore | None = None) -> TryPurgeResult:
    with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM field.worker_purge_try_looks()")
        refs = [str(r[0]) for r in cur.fetchall()]
    photos = store or TryPhotoStore()
    deleted = 0
    for ref in refs:
        try:
            deleted += 1 if photos.delete(ref) else 0
        except (CropStoreError, OSError):
            logger.exception("try_photo_delete_failed")
    result = TryPurgeResult(len(refs), deleted)
    logger.info("try_look_retention_purge", photos_released=result.photos_released,
                photos_deleted=result.photos_deleted)
    return result
