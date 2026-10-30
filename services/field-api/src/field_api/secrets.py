"""Secrets Management & Response Scrubber (Task T1.071 / FR1.062).

Ensures sensitive credentials, private keys, database passwords and auth tokens
are loaded securely and scrubbed from outbound payloads and error logs (TC1.160).
"""

import os
import re
from pathlib import Path
from typing import Any

# Sensitive dictionary keys to scrub
SENSITIVE_KEYS = frozenset({
    "password",
    "pass",
    "pwd",
    "secret",
    "api_key",
    "token",
    "authorization",
    "private_key",
    "client_secret",
    "access_token",
    "refresh_token",
})

# Regex patterns for string scrubbing
URI_PASSWORD_PATTERN = re.compile(r"://([^:]+):([^@]+)@")
BEARER_PATTERN = re.compile(r"Bearer\s+([A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+\.?[A-Za-z0-9\-_=]*)")
PEM_KEY_PATTERN = re.compile(
    r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC )?PRIVATE KEY-----"
)


def load_secret(key: str, default: str | None = None) -> str:
    """Load a secret from vault/KMS file source, environment, or default."""
    source_path = os.getenv("FIELD_SECRETS_FILE")
    if source_path:
        secret_file = Path(source_path) / key
        if secret_file.exists():
            return secret_file.read_text(encoding="utf-8").strip()

    val = os.getenv(key)
    if val is not None:
        return val

    if default is not None:
        return default

    raise KeyError(f"Secret '{key}' not found in secrets provider or environment")


MIN_SECRET_BYTES = 32

# Signing/HMAC keys the service cannot run without. There are no built-in defaults (A-02):
# scripts/dev/run-field-stack.ps1 generates them into the git-ignored .env.local, CI sets test values.
REQUIRED_SECRETS: tuple[tuple[str, ...], ...] = (
    ("FIELD_JWT_SECRET", "JWT_SECRET_KEY"),
    ("FIELD_CURSOR_HMAC_SECRET",),
    ("FIELD_P13F_WEBHOOK_SECRET",),
    ("FIELD_EVIDENCE_SECRET",),
)


def required_secret(*names: str) -> str:
    """First of ``names`` that is set (secrets file or env); at least 32 bytes. Raises if none is."""
    for n in names:
        try:
            val = load_secret(n)
        except KeyError:
            continue
        if len(val.encode("utf-8")) < MIN_SECRET_BYTES:
            raise RuntimeError(f"secret {n} is shorter than {MIN_SECRET_BYTES} bytes")
        return val
    raise RuntimeError(f"secret {' / '.join(names)} is not set (put it in .env.local; see .env.example)")


def missing_required_secrets() -> list[str]:
    out = []
    for names in REQUIRED_SECRETS:
        try:
            required_secret(*names)
        except RuntimeError as e:
            out.append(str(e))
    return out


def scrub_string(val: str) -> str:
    """Mask credentials within a string."""
    # Redact URI passwords
    res = URI_PASSWORD_PATTERN.sub(r"://\1:***@", val)
    # Redact Bearer tokens
    res = BEARER_PATTERN.sub("Bearer [REDACTED]", res)
    # Redact PEM private keys
    res = PEM_KEY_PATTERN.sub("[REDACTED PRIVATE KEY]", res)
    return res


def scrub_secrets(data: Any) -> Any:
    """Recursively scrub sensitive keys and credential patterns from dicts, lists, or strings."""
    if isinstance(data, dict):
        scrubbed = {}
        for k, v in data.items():
            if str(k).lower() in SENSITIVE_KEYS:
                scrubbed[k] = "[REDACTED]"
            else:
                scrubbed[k] = scrub_secrets(v)
        return scrubbed
    elif isinstance(data, list):
        return [scrub_secrets(item) for item in data]
    elif isinstance(data, tuple):
        return tuple(scrub_secrets(item) for item in data)
    elif isinstance(data, str):
        return scrub_string(data)
    else:
        return data
