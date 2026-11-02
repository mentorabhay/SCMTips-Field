"""Read a UI Automator dump: which visible element carries a text, and where to tap it (pure, no adb)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

_BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


@dataclass(frozen=True)
class Node:
    text: str
    desc: str
    clickable: bool
    enabled: bool
    bounds: tuple[int, int, int, int]
    tap_bounds: tuple[int, int, int, int]
    """The bounds of the element itself, or of its nearest clickable ancestor: where a tap lands."""

    @property
    def label(self) -> str:
        return self.text or self.desc

    @property
    def center(self) -> tuple[int, int]:
        left, top, right, bottom = self.tap_bounds
        return ((left + right) // 2, (top + bottom) // 2)


def _bounds(raw: str | None) -> tuple[int, int, int, int]:
    m = _BOUNDS.fullmatch(raw or "")
    if not m:
        return (0, 0, 0, 0)
    left, top, right, bottom = (int(g) for g in m.groups())
    return (left, top, right, bottom)


def clean_dump(raw: str) -> str:
    """The XML part of `uiautomator dump /dev/tty` (it appends a line after the document)."""
    end = raw.rfind("</hierarchy>")
    start = raw.find("<?xml")
    if end < 0:
        raise ValueError("no UI hierarchy in the dump")
    return raw[(start if start >= 0 else 0) : end + len("</hierarchy>")]


def parse(xml: str) -> list[Node]:
    """Every element with a text or a content description, with where a tap on it lands."""
    root = ET.fromstring(clean_dump(xml))
    out: list[Node] = []

    def walk(el: ET.Element, clickable_above: tuple[int, int, int, int] | None) -> None:
        b = _bounds(el.get("bounds"))
        clickable = el.get("clickable") == "true"
        here = b if clickable else clickable_above
        text = (el.get("text") or "").strip()
        desc = (el.get("content-desc") or "").strip()
        if (text or desc) and b != (0, 0, 0, 0):
            out.append(Node(text, desc, clickable, el.get("enabled") != "false", b, here or b))
        for child in el:
            walk(child, here)

    walk(root, None)
    return out


def find(nodes: list[Node], pattern: str) -> Node | None:
    """The first element whose text or description matches `pattern` (case-insensitive), enabled first."""
    rx = re.compile(pattern, re.IGNORECASE)
    hits = [n for n in nodes if rx.search(n.text) or rx.search(n.desc)]
    enabled = [n for n in hits if n.enabled]
    pool = enabled or hits
    return pool[0] if pool else None


def labels(nodes: list[Node]) -> list[str]:
    """The visible labels, top to bottom, without repeats (for the step report)."""
    seen: set[str] = set()
    ordered = sorted(nodes, key=lambda n: (n.bounds[1], n.bounds[0]))
    result: list[str] = []
    for n in ordered:
        if n.label not in seen:
            seen.add(n.label)
            result.append(n.label)
    return result
