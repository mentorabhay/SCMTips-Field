"""The local number check of a spoken brief (M4 contract §4, F3), run before the core's own check.

A rewrite may say a number in digits ("1,200", "12.5%") or in words ("twelve", "twenty five", "two lakh"). Both
are read as values. The rewrite passes only when every value it says appears in the template and every value of
the template is still said: a model that invents, changes or drops a number is refused here, so a refusal never
costs a call to the core, and the template is spoken instead.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from types import MappingProxyType

_DIGITS = re.compile(r"\d+(?:[.,]\d+)*")
_WORD = re.compile(r"[a-z]+")
_UNITS = MappingProxyType({
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "dozen": 12,
})
_TENS = MappingProxyType({"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
                          "eighty": 80, "ninety": 90})
_SCALES = MappingProxyType({"hundred": 100, "thousand": 1000, "lakh": 100_000, "lakhs": 100_000,
                            "million": 1_000_000, "crore": 10_000_000, "crores": 10_000_000,
                            "billion": 1_000_000_000})


def _digit_value(raw: str) -> Decimal | None:
    s = raw
    if "," in s and "." not in s and re.fullmatch(r"\d+,\d{1,2}", s) is None:
        s = s.replace(",", "")  # 1,200 / 1,20,000 (thousands separators)
    elif "," in s and "." in s:
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")  # 2,5 (a decimal comma)
    try:
        return Decimal(s).normalize()
    except InvalidOperation:
        return None


def _word_values(text: str) -> list[Decimal]:
    """Values of runs of number words ("twenty five" -> 25, "one hundred and two" -> 102, "two lakh" -> 200000).
    A lone "one" is not read as a number: in English it is mostly a pronoun ("the one we use"); a changed or
    dropped number is still caught by the other direction of the check."""
    out: list[Decimal] = []
    total, current, seen, after_scale, words = 0, 0, False, False, 0

    def flush() -> None:
        nonlocal total, current, seen, after_scale, words
        if seen and not (words == 1 and total + current == 1):
            out.append(Decimal(total + current).normalize())
        total, current, seen, after_scale, words = 0, 0, False, False, 0

    for w in [*_WORD.findall(text.lower()), ""]:
        if w in _UNITS or w in _TENS:
            current += _UNITS.get(w, 0) + _TENS.get(w, 0)
            seen, after_scale, words = True, False, words + 1
        elif w in _SCALES and seen:
            scale = _SCALES[w]
            if scale == 100:
                current = max(current, 1) * 100
            else:
                total += max(current, 1) * scale
                current = 0
            after_scale, words = True, words + 1
        elif w == "and" and after_scale:
            continue
        else:
            flush()
    return out


def values(text: str) -> set[Decimal]:
    """Every number said in ``text``, in digits or in words, as normalised values."""
    found: set[Decimal] = set()
    for m in _DIGITS.finditer(text):
        v = _digit_value(m.group(0))
        if v is not None:
            found.add(v)
    found.update(_word_values(_DIGITS.sub(" ", text)))
    return found


def _fmt(v: Decimal) -> str:
    return f"{v:f}"


def check(spoken: str, template: str) -> list[str]:
    """Reasons to refuse ``spoken`` (empty when it passes): local:number_not_in_template:<n>,
    local:number_dropped:<n>."""
    said, allowed = values(spoken), values(template)
    reasons = [f"local:number_not_in_template:{_fmt(v)}" for v in sorted(said - allowed)]
    reasons += [f"local:number_dropped:{_fmt(v)}" for v in sorted(allowed - said)]
    return reasons
