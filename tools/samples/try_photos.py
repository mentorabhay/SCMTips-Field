"""SAMPLE photos for the console's "Try a look" page (M5-W01), drawn with Pillow, the same bytes on every run.

    uv run python -m tools.samples.try_photos            # writes apps/field-console/public/samples/*.jpg
    uv run python -m tools.samples.try_photos --check    # exit 1 when the committed files differ from a fresh draw

Two synthetic photos, one per test case of docs/design/M5_CONTRACT.md §1, each a top view of items on a linen cloth:
- ``c1-grocery.jpg``: 8 biscuit packs, labels "biscuit pack · pack of 6"; pack 6 says "pack of 4", pack 3 is torn;
- ``c2-pharmacy.jpg``: 5 tablet boxes, "tablet box · BATCH B1 · EXP 2027-09"; box 4 is "BATCH B2 · EXP 2026-12"
  (inside the 90-day window from November 2026), box 2 is dented.
Generic printed words only: no brand, company, logo or face. ``truth`` holds each item's box (pixels, reading order:
rows top to bottom, left to right, as the look numbers instances) and what its label says, so tests can script the
model test double from the same scene the photo shows. What a real SAM 3.1 / Muse Spark answer on these photos is
UNVERIFIED (docs/META_FIELD.md rows 20, 23).
"""

from __future__ import annotations

import argparse
import io
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "apps" / "field-console" / "public" / "samples"
WIDTH, HEIGHT = 1280, 960
QUALITY = 82

Box = tuple[int, int, int, int]


@dataclass
class SamplePhoto:
    name: str  # file name under public/samples
    case: str  # grocery | pharmacy
    jpeg: bytes
    width: int
    height: int
    boxes: list[Box] = field(default_factory=list)  # reading order, n = index + 1
    labels: dict[int, dict[str, Any]] = field(default_factory=dict)  # n -> label fields as the label schema


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def _table(seed: int) -> Image.Image:
    """A light linen tablecloth: soft woven noise, low contrast (strong straight grain made Haar face cascades fire)."""
    rnd = random.Random(seed)
    img = Image.new("RGB", (WIDTH, HEIGHT), (214, 204, 186))
    d = ImageDraw.Draw(img)
    for _ in range(9000):
        x, y = rnd.randrange(WIDTH), rnd.randrange(HEIGHT)
        t = rnd.randint(-10, 10)
        if rnd.random() < 0.5:
            d.line((x, y, x + rnd.randint(4, 14), y), fill=(214 + t, 204 + t, 186 + t))
        else:
            d.line((x, y, x, y + rnd.randint(4, 14)), fill=(214 + t, 204 + t, 186 + t))
    return img.filter(ImageFilter.GaussianBlur(1.2))


def _shadow(base: Image.Image, box: Box, offset: int = 10, blur: int = 9) -> None:
    x0, y0, x1, y1 = box
    mask = Image.new("L", base.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((x0 + offset, y0 + offset, x1 + offset, y1 + offset), 14, fill=120)
    mask = mask.filter(ImageFilter.GaussianBlur(blur))
    base.paste(Image.new("RGB", base.size, (40, 26, 16)), (0, 0), mask)


def _centered(d: ImageDraw.ImageDraw, cx: int, y: int, text: str, size: int, fill: tuple[int, int, int]) -> None:
    f = _font(size)
    w = d.textlength(text, font=f)
    d.text((cx - w / 2, y), text, font=f, fill=fill)


def _pack(w: int, h: int, pieces: int, torn: bool, rnd: random.Random) -> Image.Image:
    """One biscuit pack seen from above (RGBA tile)."""
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    d.rounded_rectangle((0, 0, w - 1, h - 1), 18, fill=(226, 184, 52, 255), outline=(150, 112, 20, 255), width=3)
    for i in range(0, h, 9):  # crimped ends
        if i < 26 or i > h - 26:
            d.line((6, i, w - 7, i), fill=(196, 152, 34, 255), width=2)
    d.rectangle((14, 34, w - 15, 74), fill=(180, 52, 40, 255))
    _centered(d, w // 2, 42, "biscuit pack", 26, (255, 246, 220))
    d.rounded_rectangle((22, h // 2 - 30, w - 23, h // 2 + 64), 10, fill=(252, 250, 240, 255), outline=(120, 90, 20, 255),
                        width=2)
    _centered(d, w // 2, h // 2 - 20, f"pack of {pieces}", 34, (30, 30, 30))
    _centered(d, w // 2, h // 2 + 24, f"{pieces} x 25 g", 24, (70, 70, 70))
    for k in range(pieces):  # biscuits showing through a window
        bx = 26 + k * ((w - 52) // max(pieces, 1))
        d.ellipse((bx, h - 96, bx + 30, h - 66), fill=(204, 150, 84, 255), outline=(150, 100, 50, 255))
    if torn:
        cx, cy = w // 2 + 20, 96
        pts = [(cx - 70, cy), (cx - 40, cy - 18), (cx - 18, cy + 10), (cx + 10, cy - 14), (cx + 36, cy + 12),
               (cx + 72, cy - 6), (cx + 64, cy + 38), (cx + 20, cy + 54), (cx - 30, cy + 44), (cx - 66, cy + 30)]
        d.polygon(pts, fill=(92, 60, 30, 255), outline=(60, 36, 16, 255))
        d.polygon([(x * 0.7 + cx * 0.3, y * 0.7 + cy * 0.3) for x, y in pts], fill=(208, 158, 96, 255))
        for _ in range(9):  # crumbs and creases
            x, y = rnd.randint(cx - 90, cx + 90), rnd.randint(cy + 50, cy + 110)
            d.ellipse((x, y, x + 9, y + 7), fill=(196, 140, 80, 255))
        d.line((20, 150, w - 30, 120), fill=(170, 128, 30, 255), width=4)
        d.line((30, 190, w - 50, 210), fill=(170, 128, 30, 255), width=3)
    return tile


def _box(w: int, h: int, batch: str, expiry: str, dented: bool) -> Image.Image:
    """One tablet box seen from above (RGBA tile)."""
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    d.rectangle((0, 0, w - 1, h - 1), fill=(240, 244, 248, 255), outline=(150, 160, 175, 255), width=3)
    d.rectangle((0, 0, 26, h - 1), fill=(40, 120, 170, 255))
    d.rectangle((w - 18, 0, w - 1, h - 1), fill=(200, 210, 222, 255))
    _centered(d, w // 2 + 6, 22, "tablet box", 34, (20, 60, 100))
    _centered(d, w // 2 + 6, 66, "10 tablets", 24, (60, 70, 80))
    d.rectangle((44, h - 92, w - 34, h - 18), fill=(255, 255, 255, 255), outline=(120, 130, 140, 255), width=2)
    d.text((56, h - 86), f"BATCH {batch}", font=_font(26), fill=(10, 10, 10))
    d.text((56, h - 52), f"EXP {expiry}", font=_font(26), fill=(10, 10, 10))
    if dented:
        d.polygon([(w - 120, 0), (w - 1, 0), (w - 1, 96), (w - 70, 54)], fill=(176, 184, 196, 255))
        d.line((w - 120, 0, w - 70, 54), fill=(110, 118, 130, 255), width=4)
        d.line((w - 70, 54, w - 1, 96), fill=(110, 118, 130, 255), width=4)
        d.line((w - 96, 18, w - 40, 60), fill=(130, 138, 150, 255), width=2)
    return tile


def _place(base: Image.Image, tile: Image.Image, x: int, y: int, angle: float) -> Box:
    turned = tile.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    bbox = turned.getbbox() or (0, 0, turned.width, turned.height)
    box = (x + bbox[0], y + bbox[1], x + bbox[2], y + bbox[3])
    _shadow(base, box)
    base.paste(turned, (x, y), turned)
    return box


def _jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=QUALITY, optimize=True)
    return buf.getvalue()


def grocery() -> SamplePhoto:
    rnd = random.Random(61)
    img = _table(11)
    boxes: list[Box] = []
    labels: dict[int, dict[str, Any]] = {}
    pw, ph = 250, 380
    for n in range(1, 9):
        r, c = divmod(n - 1, 4)
        pieces = 4 if n == 6 else 6
        torn = n == 3
        tile = _pack(pw, ph, pieces, torn, rnd)
        boxes.append(_place(img, tile, 70 + c * 290 + rnd.randint(-8, 8), 50 + r * 440 + rnd.randint(-8, 8),
                            rnd.uniform(-3.5, 3.5)))
        labels[n] = {"pieces_per_unit": pieces, "batch": None, "expiry": None, "damaged": torn,
                     "damage_note": "torn wrapper" if torn else None,
                     "label_text": f"biscuit pack · pack of {pieces} · {pieces} x 25 g"}
    return SamplePhoto("c1-grocery.jpg", "grocery", _jpeg(img), WIDTH, HEIGHT, boxes, labels)


def pharmacy() -> SamplePhoto:
    rnd = random.Random(62)
    img = _table(12)
    boxes: list[Box] = []
    labels: dict[int, dict[str, Any]] = {}
    bw, bh = 340, 250
    spots = [(80, 120), (470, 110), (860, 125), (270, 540), (670, 550)]
    for n, (x, y) in enumerate(spots, start=1):
        batch, expiry = ("B2", "2026-12") if n == 4 else ("B1", "2027-09")
        dented = n == 2
        boxes.append(_place(img, _box(bw, bh, batch, expiry, dented), x + rnd.randint(-6, 6), y + rnd.randint(-6, 6),
                            rnd.uniform(-4.0, 4.0)))
        labels[n] = {"pieces_per_unit": None, "batch": batch, "expiry": expiry, "damaged": dented,
                     "damage_note": "dented corner" if dented else None,
                     "label_text": f"tablet box · 10 tablets · BATCH {batch} · EXP {expiry}"}
    return SamplePhoto("c2-pharmacy.jpg", "pharmacy", _jpeg(img), WIDTH, HEIGHT, boxes, labels)


def samples() -> list[SamplePhoto]:
    return [grocery(), pharmacy()]


def differs(committed: bytes, fresh: bytes, tolerance: float = 2.0) -> bool:
    """True when two JPEGs differ by more than ``tolerance`` mean absolute difference per channel (0-255), or in size:
    a newer Pillow / libjpeg may encode the same drawing with slightly different bytes."""
    a, b = Image.open(io.BytesIO(committed)).convert("RGB"), Image.open(io.BytesIO(fresh)).convert("RGB")
    if a.size != b.size:
        return True
    diff = sum(abs(x - y) for x, y in zip(a.tobytes(), b.tobytes(), strict=True))
    return diff / (a.width * a.height * 3) > tolerance


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--check", action="store_true", help="compare the committed files with a fresh draw")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)
    bad = 0
    for s in samples():
        path = args.out / s.name
        if args.check:
            if not path.exists() or differs(path.read_bytes(), s.jpeg):
                print(f"{path}: differs from a fresh draw; run python -m tools.samples.try_photos")
                bad += 1
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(s.jpeg)
        print(f"{path}: {len(s.jpeg)} bytes, {s.width}x{s.height}, {len(s.boxes)} items")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
