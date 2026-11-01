"""The capture image of a look: its size, and one JPEG crop per instance for the label read (Pillow)."""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from field_api.vision.ports import Box

MAX_PIXELS = 40_000_000  # a capture is at most 1 MB; refuse decompression bombs anyway
CROP_PAD = 0.08  # each crop keeps 8% of the box size around it (labels near the edge)
CROP_MAX_SIDE = 768  # longest crop side sent to the model; larger crops are scaled down
CROP_MIN_SIDE = 48  # smaller instances are scaled up to this so a label read is at least attempted


class ImageUnreadable(Exception):
    pass


@dataclass(frozen=True)
class Capture:
    jpeg: bytes
    width: int
    height: int


def open_capture(data: bytes) -> Capture:
    """Validate and measure a capture image; raises ImageUnreadable for anything Pillow cannot decode."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            w, h = img.size
            if w <= 0 or h <= 0 or w * h > MAX_PIXELS:
                raise ImageUnreadable("image size out of range")
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as e:
        raise ImageUnreadable(type(e).__name__) from None
    return Capture(data, w, h)


def padded(box: Box, width: int, height: int, pad: float = CROP_PAD) -> Box:
    x0, y0, x1, y1 = box
    px, py = int((x1 - x0) * pad), int((y1 - y0) * pad)
    return max(0, x0 - px), max(0, y0 - py), min(width, x1 + px), min(height, y1 + py)


def crops(cap: Capture, boxes: list[tuple[int, Box]]) -> list[tuple[int, bytes]]:
    """(n, JPEG bytes) per numbered box, padded, scaled to at most CROP_MAX_SIDE on the longest side."""
    out: list[tuple[int, bytes]] = []
    with Image.open(io.BytesIO(cap.jpeg)) as src:
        img = src.convert("RGB")
    for n, box in boxes:
        part = img.crop(padded(box, cap.width, cap.height))
        w, h = part.size
        longest, shortest = max(w, h), min(w, h)
        if longest > CROP_MAX_SIDE:
            f = CROP_MAX_SIDE / longest
            part = part.resize((max(1, int(w * f)), max(1, int(h * f))))
        elif 0 < shortest < CROP_MIN_SIDE:
            f = min(CROP_MIN_SIDE / shortest, CROP_MAX_SIDE / longest)
            part = part.resize((max(1, int(w * f)), max(1, int(h * f))))
        buf = io.BytesIO()
        part.save(buf, format="JPEG", quality=85)
        out.append((n, buf.getvalue()))
    return out
