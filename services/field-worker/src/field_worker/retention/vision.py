"""Retention of vision look label text (M5 contract §6: ``raw`` kept 30 days like assistant turns).

Daily, with the assistant purge, the worker calls field.worker_purge_vision_raw(days) (SECURITY DEFINER, migration
field_0064_m5_vision; the worker role has no RLS bypass). It clears ``raw_labels`` of looks older than
FIELD_ASSISTANT_RETENTION_DAYS (default 30) and stamps ``raw_purged_at``; the rest of the look (instances, counts,
the check, the model calls, the document link) is kept as evidence.
"""

from __future__ import annotations

import psycopg
import structlog

from field_worker.retention.assistant import retention_days

logger = structlog.get_logger(__name__)


def purge_vision_raw(db_url: str, days: int | None = None) -> int:
    """Clears the label text of looks older than ``days``; returns how many looks were cleared."""
    d = retention_days() if days is None else days
    with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT field.worker_purge_vision_raw(%s)", (d,))
        row = cur.fetchone()
    n = int(row[0]) if row else 0
    logger.info("vision_raw_retention_purge", days=d, looks=n)
    return n
