"""Figures as markers: the model rewrites only the words of a spoken brief, never its figures.

The core accepts a rewrite only when its figures are the template's figures, written with the same digits, in the
template's order, with their signs (``core_rule``). A model asked to "keep every number" still reads figures the
way people say them: "$12,480" for "$12,480.00", "a net cost of $1,908.90" for "-$1,908.90", the committed amount
before the net. So the model never sees a figure: every word of the template that holds a digit (an amount with its
currency and sign, a percentage with its " %", a date, a week number, a code such as CP-204) becomes a marker
[F1], [F2], ... in order, the model writes the connecting words around the markers, and ``unmask`` puts the
template's own text back for each marker. The result goes through the local checks like any rewrite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

MARKER: Final = re.compile(r"\[\s*[Ff]\s*(\d{1,3})\s*\]")
_TOKEN: Final = re.compile(r"\S+")
_LEAD: Final = "(\"'“‘"
_TRAIL: Final = ".,;:!?…)\"'”’"
_PERCENT: Final = re.compile(r"\s?%")


@dataclass(frozen=True)
class Masked:
    text: str  # the template with each figure replaced by its marker
    figures: tuple[str, ...]  # the template's text of marker [F1], [F2], ...

    @property
    def markers(self) -> list[str]:
        return [f"[F{i}]" for i in range(1, len(self.figures) + 1)]


def _spans(template: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for m in _TOKEN.finditer(template):
        start, end = m.start(), m.end()
        while start < end and template[start] in _LEAD:
            start += 1
        while end > start and template[end - 1] in _TRAIL:
            end -= 1
        if not any(c.isdigit() for c in template[start:end]):
            continue
        pct = _PERCENT.match(template, end)
        if pct and (pct.end() == len(template) or not template[pct.end()].isalnum()):
            end = pct.end()
        if out and start < out[-1][1]:  # "96.4 %" already took this "%" word
            continue
        out.append((start, end))
    return out


def mask(template: str) -> Masked:
    """The template with markers, and the figures they stand for. A template that already holds marker-like text
    is not masked (no figures), so a marker can never be ambiguous."""
    if MARKER.search(template):
        return Masked(template, ())
    parts: list[str] = []
    figures: list[str] = []
    last = 0
    for start, end in _spans(template):
        figures.append(template[start:end])
        parts += [template[last:start], f"[F{len(figures)}]"]
        last = end
    parts.append(template[last:])
    return Masked("".join(parts), tuple(figures))


def unmask(reply: str, masked: Masked) -> tuple[str, list[str]]:
    """``reply`` with each marker replaced by the template's figure, and local:unknown_marker:F<n> for a marker the
    template does not have (left as it is, so the number checks refuse it too)."""
    unknown: list[str] = []

    def put(m: re.Match[str]) -> str:
        n = int(m.group(1))
        if 1 <= n <= len(masked.figures):
            return masked.figures[n - 1]
        unknown.append(f"local:unknown_marker:F{n}")
        return m.group(0)

    return MARKER.sub(put, reply), list(dict.fromkeys(unknown))
