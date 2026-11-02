"""The SCMTIPS core's acceptance rule for a spoken brief, ported so field-api never sends text the core will refuse.

Port of ``lr_api.domain.ai.short.accept`` with ``lr_api.domain.ai.grounding.check`` (SCMTips repository,
`the core's integration branch` 6357b53; the same code as the hosted release scm-1a36ab0). The core accepts a rewrite only when

1. every number in it is a number of the template or of the decision's stored facts (the grounding check without
   the small-count exemption, dates and years included, no unknown ``[n]`` citation or link);
2. its figures, each read as (minus sign before it, its digits with every separator removed), are a subsequence of
   the template's figures: the template's figures, in the template's order, with their signs. "$12,480" is not
   "$12,480.00" here (digits 12480 against 1248000), and "minus $1,908.90" is not "-$1,908.90";
3. each figure keeps the template's label for it (net, committed, fill, savings: the label word nearest to it in its
   own clause);
4. it writes no number in words that the template does not use itself ("one", "twenty", ...);
5. it is not empty and is at most 70 words (spoken) or 240 characters (card).

Field does not see the core's facts, so rule 1 uses the template's own numbers only: a subset of the core's
evidence, so a rewrite this port accepts is one the core accepts (the port may refuse a number the core would find
in its facts; that ends in the template, never in a refusal by the core). Rules 2 to 5 depend on the two texts only
and are the core's code. ``refusals`` returns the core's own problem sentences, so a test can compare them with the
core's verdicts on shared fixtures (services/field-api/tests/fixtures/core_brief_check_cases.json).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Final, Literal

CARD_MAX: Final = 240
SPOKEN_MAX_WORDS: Final = 70
_WORD: Final = re.compile(r"[^\s]+")


def words(value: str) -> int:
    return len(_WORD.findall(value))


# ------------------------------------------------------------------ grounding (core grounding.py, numbers and dates)
_CITE: Final = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")
_URL: Final = re.compile(r"https?://[^\s)\]>\"']+")
_ISO_DATE: Final = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_MONTH_NAMES: Final = (
    ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",), ("june", "jun"),
    ("july", "jul"), ("august", "aug"), ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"),
    ("december", "dec"),
)
_MONTHS: Final = MappingProxyType({m: i + 1 for i, names in enumerate(_MONTH_NAMES) for m in names})
_MONTH_RE: Final = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DAY_MONTH: Final = re.compile(
    rf"(?<![\w])(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})\.?(?:,?\s+(\d{{4}}))?(?![\w])", re.I
)
_MONTH_DAY: Final = re.compile(
    rf"(?<![\w])({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?(?![\w])", re.I
)
_TIME: Final = re.compile(r"(?<!\d)\d{1,2}:\d{2}(?::\d{2})?(?!\d)")
_CURRENCY: Final = r"(?:[$€£¥₹]|USD|EUR|GBP|INR|JPY|CNY)"
_NUMBER: Final = re.compile(
    rf"(?P<cur>{_CURRENCY}\s?)?"
    r"(?P<sign>[-−])?"
    r"(?P<num>\d{1,2}(?:,\d{2})+,\d{3}(?:\.\d+)?|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<scale>\s?(?:k|K|thousand|m|M|million|mn|bn|billion)(?![A-Za-z]))?"
    r"(?P<pct>\s?(?:%|percent|per cent))?"
)
_SCALES: Final = MappingProxyType({"k": 1_000, "thousand": 1_000, "m": 1_000_000, "million": 1_000_000,
                                   "mn": 1_000_000, "bn": 1_000_000_000, "billion": 1_000_000_000})


@dataclass(frozen=True)
class Figure:
    text: str
    start: int
    end: int
    value: Decimal | None = None
    kind: str = "number"  # number | percent | money | date | year


@dataclass
class Evidence:
    """The numbers, dates and years a rewrite may quote (here: the template's own)."""

    numbers: list[Decimal] = field(default_factory=list)
    dates: set[date] = field(default_factory=set)
    years: set[int] = field(default_factory=set)

    def add_text(self, value: str) -> None:
        for d in dates_in(value):
            self.dates.add(d)
            self.years.add(d.year)
        for f in extract_numbers(value):
            if f.value is not None:
                self.numbers.append(abs(f.value))


def dates_in(value: str) -> set[date]:
    out: set[date] = set()
    for y, m, d in _ISO_DATE.findall(value):
        try:
            out.add(date(int(y), int(m), int(d)))
        except ValueError:
            continue
    return out


def _skip_spans(text: str) -> list[tuple[int, int]]:
    spans = [m.span() for m in _CITE.finditer(text)]
    spans += [m.span() for m in _URL.finditer(text)]
    spans += [m.span() for m in _TIME.finditer(text)]
    return spans


def _inside(pos: int, spans: Sequence[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in spans)


def _identifier(text: str, start: int, end: int) -> bool:
    """Digits that are part of a code: CP-208, L06, SUP-S04, 3PL, v2."""
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    if before.isalpha() or before == "_" or after.isalpha() or after == "_":
        return True
    if before in "-/#" and start >= 2 and (text[start - 2].isalnum()):
        return True
    return after == "-" and end + 1 < len(text) and text[end + 1].isdigit()


def extract_numbers(text: str) -> list[Figure]:
    """Figures in ``text`` (numbers, money, percentages); identifiers excluded."""
    skip = _skip_spans(text)
    out: list[Figure] = []
    for m in _NUMBER.finditer(text):
        num_start, _num_end = m.span("num")
        if _inside(num_start, skip):
            continue
        tail = m.end("num")
        if _identifier(text, num_start, tail) and not (m.group("scale") or m.group("pct")):
            continue
        raw = m.group("num").replace(",", "")
        try:
            value = Decimal(raw)
        except InvalidOperation:
            continue
        scale = (m.group("scale") or "").strip().lower()
        if scale:
            value *= _SCALES.get(scale, 1)
        kind = "number"
        if m.group("pct"):
            kind = "percent"
        elif m.group("cur"):
            kind = "money"
        if m.group("sign"):
            value = -value
        start = m.start("cur") if m.group("cur") else (m.start("sign") if m.group("sign") else num_start)
        out.append(Figure(text[start : m.end()].strip(), start, m.end(), value, kind))
    return out


def _tolerance(fig: Figure) -> Decimal:
    num = re.search(r"\d[\d,]*(?:\.(\d+))?", fig.text)
    decimals = len(num.group(1)) if num and num.group(1) else 0
    tol = Decimal(5) / (Decimal(10) ** (decimals + 1))
    scale = re.search(r"(k|K|thousand|m|M|million|mn|bn|billion)\b", fig.text)
    if scale:
        tol *= _SCALES.get(scale.group(1).lower(), 1)
    return tol


def _matches(value: Decimal, tol: Decimal, pool: Iterable[Decimal], percent: bool) -> bool:
    target = abs(value)
    for v in pool:
        if abs(v - target) <= tol:
            return True
        if percent and abs(v * 100 - target) <= tol:
            return True
    return False


def _date_figure(m: re.Match[str]) -> Figure:
    text = m.group(0).rstrip(".")
    return Figure(text, m.start(), m.start() + len(text), kind="date")


def _date_figures(text: str) -> list[tuple[Figure, int, int, int | None]]:
    out: list[tuple[Figure, int, int, int | None]] = []
    for m in _ISO_DATE.finditer(text):
        out.append((Figure(m.group(0), *m.span(), kind="date"), int(m[2]), int(m[3]), int(m[1])))
    for m in _DAY_MONTH.finditer(text):
        year = int(m.group(3)) if m.group(3) else None
        out.append((_date_figure(m), _MONTHS[m.group(2).lower()], int(m.group(1)), year))
    for m in _MONTH_DAY.finditer(text):
        year = int(m.group(3)) if m.group(3) else None
        out.append((_date_figure(m), _MONTHS[m.group(1).lower()], int(m.group(2)), year))
    return out


def grounding_problems(answer: str, evidence: Evidence) -> list[str]:
    """The core's ``grounding.check(answer, evidence, small_counts=False).problems()`` with no citable articles."""
    ungrounded: list[Figure] = []
    date_spans: list[tuple[int, int]] = []
    for fig, month, day, year in _date_figures(answer):
        if _inside(fig.start, date_spans):
            continue
        date_spans.append((fig.start, fig.end))
        if not any(d.month == month and d.day == day and (year is None or d.year == year) for d in evidence.dates):
            ungrounded.append(fig)
    for fig in extract_numbers(answer):
        if _inside(fig.start, date_spans) or fig.value is None:
            continue
        value = fig.value
        whole = value == value.to_integral_value() and "." not in fig.text
        if fig.kind == "number" and whole and 1900 <= value <= 2100 and "," not in fig.text:
            if int(value) in evidence.years or _matches(value, Decimal(0), evidence.numbers, False):
                continue
            ungrounded.append(Figure(fig.text, fig.start, fig.end, value, "year"))
            continue
        if _matches(value, _tolerance(fig), evidence.numbers, fig.kind == "percent"):
            continue
        ungrounded.append(fig)
    invalid = [int(x) for m in _CITE.finditer(answer) for x in m.group(1).split(",")]
    unknown = [u.rstrip(".,;") for u in _URL.findall(answer)]
    ungrounded.sort(key=lambda f: f.start)
    out: list[str] = []
    if ungrounded:
        out.append("These figures are not in any tool result: " + ", ".join(f'"{f.text}"' for f in ungrounded) + ".")
    if invalid:
        out.append("These citation markers match no article a tool returned: "
                   + ", ".join(f"[{n}]" for n in dict.fromkeys(invalid)) + ".")
    if unknown:
        out.append("These links are not stored articles: " + ", ".join(dict.fromkeys(unknown)))
    return out


# ------------------------------------------------------------- figures, order, signs and labels (core short.py)
_FIGURE: Final = re.compile(r"\d(?:[\d,.  ]*\d)?")
_MINUS: Final = frozenset("-−–")
NUMBER_WORDS: Final = frozenset({
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
    "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty",
    "fifty", "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million", "billion", "trillion", "lakh",
    "lakhs", "crore", "crores", "dozen",
})
_WORDS: Final = re.compile(r"[A-Za-z]+")
_LABEL: Final = re.compile(r"\b(net|commit(?:s|ted|ting)?|fill|sav(?:e|es|ed|ing|ings))\b", re.I)
_CLAUSE_END: Final = re.compile(r"[.;:!?](?=\s|$)|,\s")


def figure_spans(body: str) -> list[tuple[bool, str, int, int]]:
    """(negative, digits, start, end) of each number of ``body``, in order (the core's ``_figure_spans``)."""
    out: list[tuple[bool, str, int, int]] = []
    for m in _FIGURE.finditer(body):
        i = m.start() - 1
        while i >= 0 and m.start() - i <= 4 and not body[i].isalnum() and body[i] not in _MINUS:
            i -= 1
        negative = i >= 0 and body[i] in _MINUS and (i == 0 or not body[i - 1].isalnum())
        out.append((negative, re.sub(r"\D", "", m.group(0)), m.start(), m.end()))
    return out


def signed_figures(body: str) -> list[tuple[bool, str]]:
    return [(neg, digits) for neg, digits, _start, _end in figure_spans(body)]


def _label_word(word: str) -> str:
    w = word.lower()
    return "committed" if w.startswith("commit") else ("savings" if w.startswith("sav") else w)


def figure_labels(body: str) -> list[tuple[tuple[bool, str], str | None]]:
    """Each figure of ``body`` with the fact word nearest to it in its own clause (the one before wins a tie)."""
    ends = [m.start() for m in _CLAUSE_END.finditer(body)]
    out: list[tuple[tuple[bool, str], str | None]] = []
    for neg, digits, start, end in figure_spans(body):
        lo = max((e + 1 for e in ends if e < start), default=0)
        hi = min((e for e in ends if e >= end), default=len(body))
        best: tuple[int, int, str] | None = None
        for m in _LABEL.finditer(body, lo, hi):
            before = m.end() <= start
            gap = start - m.end() if before else m.start() - end
            if gap < 0:
                continue
            key = (gap, 0 if before else 1, _label_word(m.group(1)))
            best = key if best is None or key < best else best
        out.append(((neg, digits), best[2] if best else None))
    return out


def _subsequence(part: list[tuple[bool, str]], whole: list[tuple[bool, str]]) -> bool:
    it = iter(whole)
    return all(any(x == y for y in it) for x in part)


ORDER_PROBLEM: Final = ("The figures are not the template's figures in the template's order with their signs (a figure "
                        "moved to another fact, or a sign changed).")


def labelled_problems(candidate: str, template: str) -> list[str]:
    """The core's ``labelled_check``: order and signs, labels, and numbers written in words."""
    problems: list[str] = []
    if not _subsequence(signed_figures(candidate), signed_figures(template)):
        problems.append(ORDER_PROBLEM)
    named: dict[tuple[bool, str], set[str]] = {}
    for fig, label in figure_labels(template):
        if label:
            named.setdefault(fig, set()).add(label)
    for fig, label in figure_labels(candidate):
        want = named.get(fig)
        if label and want and label not in want:
            shown = ("-" if fig[0] else "") + fig[1]
            problems.append(f"The figure {shown} is the template's {' or '.join(sorted(want))} figure, "
                            f"not its {label} figure.")
    allowed = {w.lower() for w in _WORDS.findall(template)}
    spelled = sorted(({w.lower() for w in _WORDS.findall(candidate)} & NUMBER_WORDS) - allowed)
    if spelled:
        problems.append(f"Numbers written in words cannot be checked: {', '.join(spelled)}.")
    return problems


def refusals(candidate: str, template: str, fmt: Literal["card", "spoken"] = "spoken") -> list[str]:
    """The core's problems with ``candidate`` as a rewrite of ``template`` (empty: the core accepts it), with the
    template's numbers as the only evidence."""
    body = candidate.strip()
    evidence = Evidence()
    evidence.add_text(template)
    problems = grounding_problems(body, evidence) + labelled_problems(body, template)
    if not body:
        problems.append("The rewrite is empty.")
    if fmt == "card" and len(body) > CARD_MAX:
        problems.append(f"The card has {len(body)} characters (at most {CARD_MAX}).")
    if fmt == "spoken" and words(body) > SPOKEN_MAX_WORDS:
        problems.append(f"The spoken brief has {words(body)} words (at most {SPOKEN_MAX_WORDS}).")
    return problems
