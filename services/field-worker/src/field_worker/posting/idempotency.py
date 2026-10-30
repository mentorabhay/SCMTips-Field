"""Posting Idempotency and Pre-Post Document Probing (Task T3.012 / FR3.041 / PR3.06).

Ensures:
1. Every erp_document has exactly one compact 23-char idempotency key: F + base64url(uuid).
2. Before a retry, the worker asks the ERP for a document carrying the key (ErpPort.find_by_idempotency_key,
   header text FIELD:<key>) and adopts it (field_worker.posting.queue). The ERP database is never read directly.
"""

import base64
import uuid


def generate_idempotency_key(base_uuid: uuid.UUID | None = None) -> str:
    """Generate compact 23-character idempotency key: 'F' + base64url(uuid).

    16 bytes of UUID encoded with base64url produces 22 characters (padding stripped).
    Prepending 'F' yields exactly 23 characters.
    """
    raw_bytes = (base_uuid or uuid.uuid4()).bytes
    encoded = base64.urlsafe_b64encode(raw_bytes).decode("ascii").rstrip("=")
    return f"F{encoded}"
