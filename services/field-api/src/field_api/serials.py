"""Serial Pattern Normalisation Library (Task T4.033 / FR4.016 / PR4.18).

Provides shared rules for equipment serial validation and confusable character
normalisation (O/0, I/1, S/5, B/8, Z/2) based on equipment class patterns.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

# Confusable character substitutions: (Letter, Digit)
CONFUSABLE_PAIRS = (
    ("O", "0"),
    ("I", "1"),
    ("S", "5"),
    ("B", "8"),
    ("Z", "2"),
)

LETTER_TO_DIGIT = MappingProxyType(dict(CONFUSABLE_PAIRS))
DIGIT_TO_LETTER = MappingProxyType({digit: letter for letter, digit in CONFUSABLE_PAIRS})

# Standard equipment class serial patterns
EQUIPMENT_PATTERNS: Mapping[str, str] = MappingProxyType({
    "RRU": r"^([0-9]{2}[A-Z][0-9][A-Z][0-9]{4}|RRU-[A-Z0-9-]{4,16})$",
    "BBU": r"^BBU-[A-Z0-9-]{4,16}$",
    "TMA": r"^TMA-[A-Z0-9-]{4,16}$",
    "ANT_PANEL": r"^ANT-[A-Z0-9-]{4,16}$",
    "RECTIFIER": r"^REC-[A-Z0-9-]{4,16}$",
    "MICROWAVE": r"^MW-[A-Z0-9-]{4,16}$",
    "ROUTER": r"^RTR-[A-Z0-9-]{4,16}$",
    "CABINET": r"^CAB-[A-Z0-9-]{4,16}$",
    "UNKNOWN": r"^[A-Z0-9-]{6,24}$",
})

DEFAULT_PATTERN = r"^[A-Z0-9-]{6,24}$"


@dataclass
class Substitution:
    position: int
    original: str
    replacement: str


@dataclass
class NormalisationResult:
    original_serial: str
    normalised_serial: str
    is_normalised: bool
    substitutions: list[Substitution] = field(default_factory=list)
    matches_pattern: bool = False
    equipment_class: str = "UNKNOWN"
    pattern: str = DEFAULT_PATTERN


def get_class_pattern(equipment_class: str | None = None) -> str:
    """Return regex pattern for the given equipment class."""
    if not equipment_class:
        return DEFAULT_PATTERN
    return EQUIPMENT_PATTERNS.get(equipment_class.upper(), DEFAULT_PATTERN)


def normalise_serial(
    raw_serial: str,
    equipment_class: str | None = None,
    expected_pattern: str | None = None,
) -> NormalisationResult:
    """Normalise confusable characters in a raw OCR serial string per class pattern.

    Rule: If raw_serial does not match the target pattern, try confusable substitutions
    (O/0, I/1, S/5, B/8, Z/2) based on whether digits or letters are expected.
    """
    clean_raw = raw_serial.strip().upper()
    eq_class = (equipment_class or "UNKNOWN").upper()
    pattern_str = expected_pattern or get_class_pattern(eq_class)
    regex = re.compile(pattern_str)

    # 1. Exact match without substitution
    if regex.match(clean_raw):
        return NormalisationResult(
            original_serial=raw_serial,
            normalised_serial=clean_raw,
            is_normalised=False,
            substitutions=[],
            matches_pattern=True,
            equipment_class=eq_class,
            pattern=pattern_str,
        )

    # 2. Identify all positions with confusable characters
    confusable_positions: list[tuple[int, str, list[str]]] = []
    for idx, ch in enumerate(clean_raw):
        options = []
        if ch in LETTER_TO_DIGIT:
            options.append(LETTER_TO_DIGIT[ch])
        if ch in DIGIT_TO_LETTER:
            options.append(DIGIT_TO_LETTER[ch])
        if options:
            confusable_positions.append((idx, ch, options))

    # 3. Explore combinations ordered by fewest substitutions
    best_candidate: str | None = None
    best_subs: list[Substitution] = []

    for r in range(1, min(len(confusable_positions) + 1, 5)):
        found = False
        for combo in itertools.combinations(confusable_positions, r):
            chars = list(clean_raw)
            current_subs = []
            for pos, orig, reps in combo:
                rep = reps[0]
                chars[pos] = rep
                current_subs.append(Substitution(position=pos, original=orig, replacement=rep))

            candidate_str = "".join(chars)
            if regex.match(candidate_str):
                best_candidate = candidate_str
                best_subs = current_subs
                found = True
                break
        if found:
            break

    if best_candidate is not None:
        return NormalisationResult(
            original_serial=raw_serial,
            normalised_serial=best_candidate,
            is_normalised=True,
            substitutions=best_subs,
            matches_pattern=True,
            equipment_class=eq_class,
            pattern=pattern_str,
        )

    # Not matched even after confusable exploration
    return NormalisationResult(
        original_serial=raw_serial,
        normalised_serial=clean_raw,
        is_normalised=False,
        substitutions=[],
        matches_pattern=False,
        equipment_class=eq_class,
        pattern=pattern_str,
    )
