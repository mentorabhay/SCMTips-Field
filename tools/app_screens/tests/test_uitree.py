"""The UI dump reader finds what to tap and where (M5-K01)."""

from __future__ import annotations

import pytest

from tools.app_screens.steps import ADVANCE, WALK
from tools.app_screens.uitree import clean_dump, find, labels, parse

DUMP = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy rotation="0">
<node text="" content-desc="" clickable="false" enabled="true" bounds="[0,0][1080,2400]">
  <node text="" content-desc="" clickable="true" enabled="true" bounds="[40,1800][1040,1950]">
    <node text="Try the SAMPLE demo" content-desc="" clickable="false" enabled="true" bounds="[300,1850][780,1900]" />
  </node>
  <node text="Get started" content-desc="" clickable="true" enabled="false" bounds="[40,2000][1040,2150]" />
  <node text="Get started" content-desc="" clickable="true" enabled="true" bounds="[40,2200][1040,2350]" />
  <node text="" content-desc="Settings" clickable="true" enabled="true" bounds="[900,100][1000,200]" />
  <node text="SCMTIPS FIELD" content-desc="" clickable="false" enabled="true" bounds="[40,100][600,180]" />
</node></hierarchy>UI hierchary dumped to: /dev/tty"""


def test_a_text_inside_a_clickable_row_is_tapped_on_the_row() -> None:
    hit = find(parse(DUMP), r"^Try the SAMPLE demo$")
    assert hit is not None
    assert hit.center == (540, 1875)


def test_an_enabled_match_wins_over_a_disabled_one() -> None:
    hit = find(parse(DUMP), "get started")
    assert hit is not None and hit.enabled and hit.bounds == (40, 2200, 1040, 2350)


def test_a_content_description_is_found_too() -> None:
    hit = find(parse(DUMP), "^Settings$")
    assert hit is not None and hit.center == (950, 150)


def test_labels_read_top_to_bottom_without_repeats() -> None:
    assert labels(parse(DUMP)) == ["SCMTIPS FIELD", "Settings", "Try the SAMPLE demo", "Get started"]


def test_the_trailing_dump_line_is_dropped_and_a_dump_without_a_hierarchy_is_refused() -> None:
    assert clean_dump(DUMP).endswith("</hierarchy>")
    with pytest.raises(ValueError):
        clean_dump("ERROR: could not get idle state")


def test_the_walk_reaches_the_demo_and_names_every_screenshot() -> None:
    kinds = [s.kind for s in WALK]
    assert all(s.name for s in WALK if s.kind == "shot")
    assert len({s.name for s in WALK if s.kind == "shot"}) == kinds.count("shot")
    demo = [s for s in WALK if s.kind == "tap" and s.arg == r"^Try the SAMPLE demo$"]
    assert demo and demo[0].required
    assert find(parse(DUMP), ADVANCE) is None  # nothing on the welcome dump moves the setup on by itself
