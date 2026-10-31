"""Photos sent with assistant turns ("what is this", unknown items): JPEG only, at most 1 MB, kept 30 days.

Stored content-addressed under FIELD_ASSISTANT_PHOTO_DIR (default ./var/assistant-photos), separate from
capture evidence. The worker's retention job deletes the files once no turn refers to them.
"""

from __future__ import annotations

import base64
import binascii
import os
from pathlib import Path

from field_api.crops import LocalCropStore
from field_api.errors import FieldError

MAX_PHOTO_BYTES = 1024 * 1024
JPEG_MAGIC = b"\xff\xd8\xff"

ERR_PHOTO_INVALID = FieldError(status=422, code="FIELD-AST-422-PHOTO", title="The photo must be a JPEG image")
ERR_PHOTO_TOO_LARGE = FieldError(status=413, code="FIELD-AST-413-PHOTO-TOO-LARGE", title="The photo is larger than 1 MB")


def decode_photo(b64: str) -> bytes:
    try:
        data = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise ERR_PHOTO_INVALID
    if len(data) > MAX_PHOTO_BYTES:
        raise ERR_PHOTO_TOO_LARGE
    if not data.startswith(JPEG_MAGIC):
        raise ERR_PHOTO_INVALID
    return data


class AssistantPhotoStore(LocalCropStore):
    def __init__(self, root: str | None = None) -> None:
        super().__init__(root or os.getenv("FIELD_ASSISTANT_PHOTO_DIR") or "var/assistant-photos")

    def delete(self, uri: str) -> bool:
        """Remove one stored photo; True if a file was deleted. Refuses URIs outside the store."""
        p: Path = self._path(uri)
        if p.exists():
            p.unlink()
            return True
        return False
