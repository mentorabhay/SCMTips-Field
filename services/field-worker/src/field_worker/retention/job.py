"""Retention and Legal Hold Cleaner Job (Task T2.054 / FR2.051, TC2.143)."""

from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class RetentionCleanerJob:
    """Executes nightly retention sweep for crop evidence.

    1. Checks retention_until against current clock.
    2. Strictly preserves any evidence with is_legal_hold == True.
    3. Deletes expired items not on legal hold.
    4. Writes an audit batch entry.
    """

    def __init__(self, default_retention_days: int = 90) -> None:
        self.default_retention_days = default_retention_days

    def sweep_evidence(
        self,
        evidence_records: list[dict[str, Any]],
        now: datetime | None = None,
        s3_delete_fn: Any = None,
    ) -> dict[str, Any]:
        curr_time = now or datetime.now(UTC)
        deleted_count = 0
        preserved_hold_count = 0
        active_count = 0
        deleted_uris = []

        for ev in evidence_records:
            retention_until_str = ev.get("retention_until")
            is_hold = bool(ev.get("is_legal_hold", False))

            if not retention_until_str:
                active_count += 1
                continue

            retention_dt = datetime.fromisoformat(retention_until_str)
            if retention_dt <= curr_time:
                # Expired
                if is_hold:
                    # Legal hold overrides retention expiry (FR2.051 / TC2.143)
                    preserved_hold_count += 1
                else:
                    deleted_count += 1
                    uri = ev.get("crop_s3_uri", "")
                    deleted_uris.append(uri)
                    if s3_delete_fn:
                        s3_delete_fn(uri)
            else:
                active_count += 1

        audit_entry = {
            "timestamp": curr_time.isoformat(),
            "deleted_count": deleted_count,
            "preserved_hold_count": preserved_hold_count,
            "active_count": active_count,
            "deleted_uris": deleted_uris,
        }
        logger.info("Retention sweep completed", **audit_entry)
        return audit_entry
