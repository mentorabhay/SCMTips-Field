"""ERP Sim Enqueue Locks Manager (Task T1.044 / PR1.06).

Acquires (object_type, object_key) with INSERT ... ON CONFLICT DO NOTHING
plus TTL takeover after FIELD_SIM_LOCK_TTL_S.
Returns ZSIM/LOCKED with holder and object in SAP-like text;
releases at end of the logical unit of work.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

DEFAULT_LOCK_TTL_SECONDS = 30


class LockContentionError(Exception):
    """Raised when an object is currently locked by another active session."""

    def __init__(self, object_type: str, object_key: str, holder_session: str) -> None:
        super().__init__(
            f"Object {object_type} {object_key} locked by user/session {holder_session} [ZSIM/LOCKED]"
        )
        self.code = "ZSIM/LOCKED"
        self.object_type = object_type
        self.object_key = object_key
        self.holder_session = holder_session


def acquire_lock(
    cur: psycopg.Cursor[Any],
    client: str,
    object_type: str,
    object_key: str,
    session_id: str,
    ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
) -> None:
    """Acquire exclusive lock on object; raises LockContentionError if held and active."""
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=ttl_seconds)

    # 1. Clean up expired lock for this object if any
    cur.execute(
        """
        DELETE FROM erpsim.enqueue_lock
        WHERE client = %s AND object_type = %s AND object_key = %s
          AND expires_at <= %s;
    """,
        (client, object_type, object_key, now),
    )

    # 2. Try insert new lock
    cur.execute(
        """
        INSERT INTO erpsim.enqueue_lock (client, object_type, object_key, session_id, acquired_at, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (client, object_type, object_key) DO NOTHING
        RETURNING session_id;
    """,
        (client, object_type, object_key, session_id, now, expires_at),
    )
    inserted = cur.fetchone()
    if inserted:
        return

    # 3. Conflict occurred: inspect holder
    cur.execute(
        """
        SELECT session_id, expires_at FROM erpsim.enqueue_lock
        WHERE client = %s AND object_type = %s AND object_key = %s;
    """,
        (client, object_type, object_key),
    )
    row = cur.fetchone()
    if row:
        holder, _exp = row[0], row[1]
        if holder == session_id:
            # Re-entrant: extend TTL
            cur.execute(
                """
                UPDATE erpsim.enqueue_lock
                SET expires_at = %s
                WHERE client = %s AND object_type = %s AND object_key = %s;
            """,
                (expires_at, client, object_type, object_key),
            )
            return
        raise LockContentionError(object_type, object_key, holder)


def release_lock(
    cur: psycopg.Cursor[Any],
    client: str,
    object_type: str,
    object_key: str,
    session_id: str,
) -> None:
    """Release lock if held by session_id."""
    cur.execute(
        """
        DELETE FROM erpsim.enqueue_lock
        WHERE client = %s AND object_type = %s AND object_key = %s AND session_id = %s;
    """,
        (client, object_type, object_key, session_id),
    )
