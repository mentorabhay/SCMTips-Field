"""M5-W01: the bundled SAMPLE photos of the "Try a look" page are drawn deterministically by tools.samples.try_photos,
match the committed files, show what their scene says (8 packs / 5 boxes in reading order) and hold no face, so the
server's face gate leaves their labels sharp."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from field_api.vision.faces import HaarFaces
from field_api.vision.ports import FoundInstance
from field_api.vision.service import order_instances
from PIL import Image

from tools.samples import try_photos

pytestmark = pytest.mark.unit


def test_m5_w01_committed_samples_match_a_fresh_draw() -> None:
    assert try_photos.main(["--check"]) == 0
    for s in try_photos.samples():
        path = try_photos.OUT_DIR / s.name
        data = path.read_bytes()
        assert data.startswith(b"\xff\xd8\xff") and len(data) < 250_000
        assert Image.open(io.BytesIO(data)).size == (s.width, s.height) == (1280, 960)


def test_m5_w01_check_reports_a_changed_file(tmp_path: Path) -> None:
    assert try_photos.main(["--out", str(tmp_path)]) == 0
    (tmp_path / "c1-grocery.jpg").write_bytes(try_photos.pharmacy().jpeg)
    assert try_photos.main(["--check", "--out", str(tmp_path)]) == 1
    assert try_photos.differs(try_photos.grocery().jpeg, try_photos.grocery().jpeg) is False


def test_m5_w01_sample_scenes_are_the_two_test_cases_in_reading_order() -> None:
    c1, c2 = try_photos.grocery(), try_photos.pharmacy()
    assert (c1.case, len(c1.boxes)) == ("grocery", 8) and (c2.case, len(c2.boxes)) == ("pharmacy", 5)
    assert [n for n, lab in c1.labels.items() if lab["damaged"]] == [3]
    assert {n: lab["pieces_per_unit"] for n, lab in c1.labels.items() if lab["pieces_per_unit"] != 6} == {6: 4}
    assert [n for n, lab in c2.labels.items() if lab["damaged"]] == [2]
    assert {n: (lab["batch"], lab["expiry"]) for n, lab in c2.labels.items() if lab["batch"] != "B1"} == {4: ("B2", "2026-12")}
    for s in (c1, c2):
        assert all(0 <= x0 < x1 <= s.width and 0 <= y0 < y1 <= s.height for x0, y0, x1, y1 in s.boxes)
        found = [FoundInstance(b, 0.9) for b in reversed(s.boxes)]
        assert [f.box for f in order_instances(found)] == s.boxes  # n = the look's own numbering
        for lab in s.labels.values():
            text = str(lab["label_text"]).lower()
            assert all(word not in text for word in ("brand", "®", "™"))


def test_m5_w01_samples_hold_no_face() -> None:
    for s in try_photos.samples():
        assert HaarFaces().find(Image.open(io.BytesIO(s.jpeg))) == []
