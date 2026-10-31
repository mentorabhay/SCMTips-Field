"""Signing of the core's webhook feeds (handover 01a; exchange contract README "Signing live pushes").

``X-SCMTIPS-Signature: sha256=<hex HMAC-SHA256(feed_secret, timestamp + "." + raw_body)>`` with
``X-SCMTIPS-Timestamp: <unix seconds>``; the core accepts timestamps within 5 minutes of its clock (confirmed by the
core's reply TO_FIELD section 4). ``X-Requested-With: lr`` goes with every call Field makes to the core (section 3).
The core ignores ``Idempotency-Key`` (it dedupes by body hash); Field still sends it, for its own logs.
"""

from __future__ import annotations

import hashlib
import hmac
import time

MAX_SKEW_S = 300


def sign(secret: str, timestamp: int, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def verify(secret: str, timestamp: int, body: bytes, signature: str, now: float | None = None) -> bool:
    if abs((time.time() if now is None else now) - timestamp) > MAX_SKEW_S:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body).encode(), signature.encode())


def signed_headers(secret: str, body: bytes, idempotency_key: str, now: float | None = None) -> dict[str, str]:
    ts = int(time.time() if now is None else now)
    return {
        "Content-Type": "application/json",
        "X-SCMTIPS-Timestamp": str(ts),
        "X-SCMTIPS-Signature": sign(secret, ts, body),
        "Idempotency-Key": idempotency_key,
        "X-Requested-With": "lr",
        "User-Agent": "scmtips-field-worker",
    }
