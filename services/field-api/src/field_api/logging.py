"""Structured Logging Configuration with Sensitive Data Redaction (Task T1.014 / FR1.063)."""

import re
from collections.abc import MutableMapping
from typing import Any

import structlog

REDACT_KEYS = {
    "authorization",
    "token",
    "password",
    "secret",
    "device_token",
    "access_token",
}
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")


def redact_sensitive_data(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Redact tokens, credentials, and PII from log dictionary."""
    for key, value in list(event_dict.items()):
        lower_key = str(key).lower()
        if any(r in lower_key for r in REDACT_KEYS):
            event_dict[key] = "[REDACTED]"
        elif isinstance(value, str):
            if "Bearer " in value:
                event_dict[key] = "[REDACTED_BEARER]"
            elif EMAIL_REGEX.search(value):
                event_dict[key] = EMAIL_REGEX.sub("[REDACTED_EMAIL]", value)

    return event_dict


def configure_logging() -> None:
    """Initialize structured JSON logging."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            redact_sensitive_data,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
