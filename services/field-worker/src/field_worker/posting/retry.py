"""Retry classification, backoff calculation, and jitter (Task T3.011 / FR3.040 / PR3.13).

Backoff schedule: 2, 4, 8, 16, 32 s (capped at 32 s) with ±10% jitter.
Max attempts: 8.
Fails fast on 4xx validation errors.
Retries on network, 5xx server errors, 423 Locked, and SAP enqueue lock messages.
"""

import random

BACKOFF_SCHEDULE: list[int] = [2, 4, 8, 16, 32, 32, 32]
MAX_ATTEMPTS: int = 8


def compute_backoff_jitter(attempt: int, schedule: list[int] | None = None) -> float:
    """Compute backoff delay in seconds with ±10% jitter.

    Attempt index 1 -> schedule[0] (2s), 2 -> schedule[1] (4s), etc.
    """
    sched = schedule or BACKOFF_SCHEDULE
    idx = max(0, min(attempt - 1, len(sched) - 1))
    base_delay = float(sched[idx])
    jitter = random.uniform(0.9, 1.1)
    return round(base_delay * jitter, 3)


def classify_error(exc: Exception) -> tuple[str, bool, str]:
    """Classify an exception into (error_class, is_retryable, sap_message).

    Returns:
        error_class: "network", "server", "lock", or "validation"
        is_retryable: True if eligible for backoff retry, False for fast-fail
        sap_message: sanitized message or error code
    """
    msg = str(exc)
    status_code = getattr(exc, "status_code", None)
    if status_code is None and hasattr(exc, "response") and hasattr(exc.response, "status_code"):
        status_code = exc.response.status_code

    # Check for HTTP 423 Locked or SAP lock contention
    if status_code == 423 or "ZSIM/LOCKED" in msg or "locked by" in msg.lower():
        return ("lock", True, "ZSIM/LOCKED")

    if any(
        lock_code in msg
        for lock_code in ("VL/046", "MC/601", "enqueue lock", "LockContentionError")
    ):
        return ("lock", True, "VL/046" if "VL/046" in msg else "MC/601")

    # Check for network / timeout issues
    err_type_name = type(exc).__name__.lower()
    if any(
        net_term in err_type_name or net_term in msg.lower()
        for net_term in ("connect", "timeout", "network", "socket", "reset")
    ):
        return ("network", True, "COMMUNICATION_FAILURE")

    # Check for HTTP Server errors (5xx)
    if status_code and 500 <= status_code < 600:
        return ("server", True, f"HTTP_{status_code}")

    # Check for HTTP Client / Validation errors (4xx)
    if status_code and 400 <= status_code < 500:
        # 423 handled above; other 4xx are non-retryable validation errors
        return ("validation", False, f"HTTP_{status_code}")

    # Inspect ErpError or custom exception attributes
    is_retryable_attr = getattr(exc, "retryable", None)
    if is_retryable_attr is not None:
        if is_retryable_attr:
            return ("server", True, msg[:64])
        return ("validation", False, msg[:64])

    # Default fallback: unknown runtime errors are treated as server/retryable up to max_attempts
    return ("server", True, msg[:64])
