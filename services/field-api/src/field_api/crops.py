"""Crop (evidence image) storage behind an interface (C4; replaces fake S3/KMS strings).

``LocalCropStore`` writes real bytes under FIELD_CROP_DIR (default ./var/crops) and is what the
owner's PC-hosted field test uses. An S3 implementation is UNVERIFIED (no bucket/credentials) and
is not selectable until it exists. Bytes are content-addressed by sha256 and verified on write.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Protocol

MAX_CROP_BYTES = int(os.getenv("FIELD_CROP_MAX_BYTES", str(1024 * 1024)))  # API2.08: 413 above 1 MB


class CropStoreError(Exception):
    pass


class CropStore(Protocol):
    def put(self, tenant_id: str, data: bytes, expected_sha256: str | None = None) -> str: ...
    def get(self, uri: str) -> bytes: ...
    def exists(self, uri: str) -> bool: ...


class LocalCropStore:
    scheme = "file"

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or os.getenv("FIELD_CROP_DIR") or "var/crops").resolve()

    def _path(self, uri: str) -> Path:
        if not uri.startswith("file://"):
            raise CropStoreError(f"not a local crop uri: {uri}")
        p = (self.root / uri.removeprefix("file://")).resolve()
        if self.root not in p.parents:
            raise CropStoreError("crop uri escapes the crop root")
        return p

    def put(self, tenant_id: str, data: bytes, expected_sha256: str | None = None) -> str:
        if len(data) > MAX_CROP_BYTES:
            raise CropStoreError("too_large")
        digest = hashlib.sha256(data).hexdigest()
        if expected_sha256 and expected_sha256.lower() != digest:
            raise CropStoreError("sha256_mismatch")
        rel = f"{tenant_id}/{digest[:2]}/{digest}.jpg"
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(p)
        return f"file://{rel}"

    def get(self, uri: str) -> bytes:
        return self._path(uri).read_bytes()

    def exists(self, uri: str) -> bool:
        try:
            return self._path(uri).exists()
        except CropStoreError:
            return False


def crop_store() -> CropStore:
    kind = os.getenv("FIELD_CROP_STORE", "local")
    if kind != "local":
        raise CropStoreError(f"crop store {kind!r} is not implemented (S3 is UNVERIFIED)")
    return LocalCropStore()
