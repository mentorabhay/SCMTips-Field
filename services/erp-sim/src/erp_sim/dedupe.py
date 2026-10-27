"""ERP Sim Idempotency Deduplication Engine (Task T1.051 / PR1.08).

Every create operation reads header text FIELD:<key> (or header Idempotency-Key);
erpsim.dedupe(client, idem_key, request_hash, document_no, fiscal_year) unique on (client, idem_key).
Same hash returns the original document with sap-message ZSIM/DUP;
different hash returns ZSIM/IDEM-CONFLICT.
"""

import hashlib
import json
from typing import Any

import psycopg


class IdempotencyConflictError(Exception):
    """Raised when an idempotency key is reused with a different request hash."""

    def __init__(self, key: str) -> None:
        super().__init__(
            f"Idempotency key '{key}' was already used with a different request payload [ZSIM/IDEM-CONFLICT]"
        )
        self.code = "ZSIM/IDEM-CONFLICT"
        self.key = key


def compute_request_hash(data: Any) -> str:
    """Compute sha256 of canonically sorted JSON."""
    if isinstance(data, (bytes, bytearray)):
        return hashlib.sha256(data).hexdigest()
    if isinstance(data, str):
        return hashlib.sha256(data.encode("utf-8")).hexdigest()
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def check_dedupe(
    cur: psycopg.Cursor[Any],
    client: str,
    idem_key: str,
    request_hash: str,
) -> tuple[bool, str | None, str | None]:
    """Check dedupe table for existing key.

    Returns (is_duplicate, doc_no, fiscal_year).
    Raises IdempotencyConflictError if hash does not match.
    """
    cur.execute(
        """
        SELECT request_hash, document_no, fiscal_year
        FROM erpsim.dedupe
        WHERE client = %s AND idem_key = %s;
    """,
        (client, idem_key),
    )
    row = cur.fetchone()
    if not row:
        return False, None, None

    stored_hash, doc_no, year = row[0], row[1], row[2]
    if stored_hash != request_hash:
        raise IdempotencyConflictError(idem_key)

    return True, str(doc_no), str(year)


def record_dedupe(
    cur: psycopg.Cursor[Any],
    client: str,
    idem_key: str,
    request_hash: str,
    doc_no: str,
    fiscal_year: str,
) -> None:
    """Record successfully posted document in dedupe store."""
    cur.execute(
        """
        INSERT INTO erpsim.dedupe (client, idem_key, request_hash, document_no, fiscal_year)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (client, idem_key) DO NOTHING;
    """,
        (client, idem_key, request_hash, doc_no, fiscal_year),
    )
