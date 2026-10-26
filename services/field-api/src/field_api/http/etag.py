"""ETag and Concurrency Precondition Evaluator (Task T1.018 / PR1.10 / TC1.115)."""

import hashlib

from fastapi import Request

from field_api.errors import ERR_ETAG_MISMATCH, ERR_ETAG_REQUIRED


def generate_etag(resource_id: str, version: int) -> str:
    """Generate a strong ETag derived from resource ID and monotonic version."""
    raw = f"{resource_id}:{version}".encode()
    digest = hashlib.sha256(raw).hexdigest()[:16]
    return f'"{version}-{digest}"'


def verify_if_match(request: Request, current_version: int, resource_id: str) -> None:
    """Validate If-Match header against the resource's current version."""
    if_match = request.headers.get("If-Match")
    if not if_match:
        raise ERR_ETAG_REQUIRED

    expected_etag = generate_etag(resource_id, current_version)
    clean_header = if_match.strip().strip('"')
    clean_expected = expected_etag.strip('"')

    if clean_header != clean_expected and if_match != "*":
        raise ERR_ETAG_MISMATCH


def check_if_none_match(request: Request, current_etag: str) -> bool:
    """Return True if If-None-Match matches current ETag (client has fresh cache -> 304)."""
    if_none_match = request.headers.get("If-None-Match")
    if not if_none_match:
        return False
    return if_none_match.strip() == current_etag.strip() or if_none_match == "*"
