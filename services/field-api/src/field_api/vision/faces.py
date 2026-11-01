"""Server-side face gate for photos that did not come through the phone (M5-W01: the console's "Try a look" upload).

A look photo from the phone has its faces pixelated on the phone before upload (M5_CONTRACT §6), and the captures API
refuses a photo without ``blur_applied``. A browser upload has no such gate, and a flag sent by a browser proves
nothing, so field-api finds faces itself and pixelates them before the photo is stored and before any model call:
the try photo, SAM's image and every label crop are cut from the pixelated photo.

Detector: OpenCV's Haar cascades shipped in the opencv-python-headless wheel (frontal default + alt2 agreeing, profile
in both directions; see HaarFaces), on the photo as it will be stored (at most 1600 px on its long side). Honest
limits: Haar cascades miss small, strongly turned, partly covered or poorly lit faces, so the page asks people not to
photograph anyone; every face found is pixelated with a margin. Pixelation is the
phone's method: blocks of about an eighth of the face width, so no face detail survives.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np
from PIL import Image

from field_api.vision.ports import Box

FACE_MARGIN = 0.25  # each found face is widened by a quarter of its size on every side before pixelating
MIN_FACE_PX = 20  # faces smaller than this (pixels of the stored photo) are not looked for
FRONTAL_NEIGHBOURS = 4
FRONTAL_AGREE = 0.3
PROFILE_NEIGHBOURS = 5
CASCADE_DIR = Path(cv2.__file__).resolve().parent / "data"  # cv2.data.haarcascades (untyped in the stubs)
CASCADES = ("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml", "haarcascade_profileface.xml")


class FaceFinder(Protocol):
    def find(self, img: Image.Image) -> list[Box]: ...


def _iou(a: Box, b: Box) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


class HaarFaces:
    """Faces in an RGB image by OpenCV's Haar cascades, on the full stored photo (no smaller copy: at 1000 px a 24 px
    face of the 1600 px photo was missed). Cost measured on the 2-vCPU build sandbox: about 2.5-5 s for a 1600x1200
    photo; it runs before the SAM call, so it adds to the first answer's wait.

    Frontal faces: a box both frontal cascades (default and alt2) find (IoU >= FRONTAL_AGREE) at FRONTAL_NEIGHBOURS;
    on its own each cascade also fires on printed text and woven or grained surfaces, which would pixelate the very
    labels a look must read. Turned faces: the profile cascade, both directions, at PROFILE_NEIGHBOURS."""

    _local = threading.local()  # one classifier set per thread: no lock, concurrent looks do not wait for each other

    @classmethod
    def _load(cls) -> list[cv2.CascadeClassifier]:
        loaded: list[cv2.CascadeClassifier] | None = getattr(cls._local, "classifiers", None)
        if loaded is None:
            loaded = []
            for name in CASCADES:
                c = cv2.CascadeClassifier(str(CASCADE_DIR / name))
                if c.empty():
                    raise RuntimeError(f"face cascade {name} could not be loaded")
                loaded.append(c)
            cls._local.classifiers = loaded
        return loaded

    @staticmethod
    def _detect(c: cv2.CascadeClassifier, gray: Any, neighbours: int, flip: bool = False) -> list[Box]:
        w = gray.shape[1]
        g = cv2.flip(gray, 1) if flip else gray
        out: list[Box] = []
        for x, y, fw, fh in c.detectMultiScale(g, scaleFactor=1.1, minNeighbors=neighbours,
                                               minSize=(MIN_FACE_PX, MIN_FACE_PX)):
            x0 = int(w - x - fw) if flip else int(x)
            out.append((x0, int(y), x0 + int(fw), int(y) + int(fh)))
        return out

    def find(self, img: Image.Image) -> list[Box]:
        gray = cv2.equalizeHist(cv2.cvtColor(np.asarray(img.convert("RGB")), cv2.COLOR_RGB2GRAY))
        default, alt2, profile = self._load()
        a = self._detect(default, gray, FRONTAL_NEIGHBOURS)
        b = self._detect(alt2, gray, FRONTAL_NEIGHBOURS)
        sides = self._detect(profile, gray, PROFILE_NEIGHBOURS) + self._detect(profile, gray, PROFILE_NEIGHBOURS,
                                                                                flip=True)
        frontal = [box for box in a if any(_iou(box, other) >= FRONTAL_AGREE for other in b)]
        return frontal + sides


def pixelate(img: Image.Image, boxes: list[Box], margin: float = FACE_MARGIN) -> Image.Image:
    """The image with each box (widened by ``margin``) replaced by coarse blocks."""
    out = img.convert("RGB").copy()
    width, height = out.size
    for x0, y0, x1, y1 in boxes:
        mx, my = int((x1 - x0) * margin), int((y1 - y0) * margin)
        area = (max(0, x0 - mx), max(0, y0 - my), min(width, x1 + mx), min(height, y1 + my))
        aw, ah = area[2] - area[0], area[3] - area[1]
        if aw <= 0 or ah <= 0:
            continue
        block = max(6, (x1 - x0) // 8)
        part = out.crop(area)
        small = part.resize((max(1, aw // block), max(1, ah // block)), Image.Resampling.BILINEAR)
        out.paste(small.resize((aw, ah), Image.Resampling.NEAREST), area[:2])
    return out


def blur_faces(img: Image.Image, finder: FaceFinder | None = None) -> tuple[Image.Image, int]:
    """(the image with every face found pixelated, how many faces were found)."""
    boxes = (finder or HaarFaces()).find(img)
    return (pixelate(img, boxes), len(boxes)) if boxes else (img.convert("RGB"), 0)
