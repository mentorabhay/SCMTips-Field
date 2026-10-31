"""SAMPLE decisions, the brief number check and the voice grammar of the stand-in core (dev double).

Two SAMPLE decisions on one disruption (rare-earth magnet export curbs): expedite air freight vs. qualify an
alternate supplier, and a smaller buffer-stock decision. The first sits in an approval band that needs the phone
step-up. Cards are at most 240 characters, the spoken briefs about 20 seconds.

The real core decides every intent and every approval; this module only mimics its observable answers (the
shapes of the ported ARO client, api/Models.kt) so Field's approver flow can be built against them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class Option:
    letter: str
    option_id: str
    title: str
    committed: str
    net: str
    cost_total: int
    details: str


@dataclass
class Decision:
    decision_id: str
    title: str
    card: str
    spoken: str
    options: tuple[Option, ...]
    band_label: str
    step_up: bool
    created_at: datetime
    deadline_at: datetime
    status: str = "open"  # open | approved | rejected
    version: int = 1
    chosen: str | None = None
    approvals: list[dict[str, Any]] = field(default_factory=list)

    def option(self, letter: str) -> Option | None:
        return next((o for o in self.options if o.letter == letter), None)

    def next_item(self, waiting: int) -> dict[str, Any]:
        """``NextItem`` of the ARO client (GET /v1/wearable/next)."""
        return {
            "decision_id": self.decision_id, "title": self.title, "card": self.card, "spoken": self.spoken,
            "options": [{"letter": o.letter, "option_id": o.option_id, "title": o.title, "committed": o.committed,
                         "net": o.net} for o in self.options],
            "band": {"label": self.band_label, "step_up": self.step_up, "approvers": 1},
            "deadline_at": self.deadline_at.isoformat(), "waiting": waiting,
        }

    def challenge_options(self) -> list[dict[str, Any]]:
        """``ChallengeOption`` of the ARO client: cost and band shapes are the backend's (passed through)."""
        return [{"letter": o.letter, "option_id": o.option_id, "title": o.title, "cost_total": o.cost_total,
                 "committed_spend": {"amount": o.cost_total, "currency": "USD"},
                 "band": {"label": self.band_label, "step_up": self.step_up}, "details": o.details}
                for o in self.options]

    def brief(self) -> dict[str, Any]:
        """GET /v1/briefs/decision/{id}: the template brief (shape assumed, see README)."""
        return {"decision_id": self.decision_id, "title": self.title, "card": self.card,
                "template_text": self.spoken, "spoken": self.spoken, "status": self.status,
                "options": [{"letter": o.letter, "option_id": o.option_id, "title": o.title} for o in self.options],
                "band": {"label": self.band_label, "step_up": self.step_up, "approvers": 1},
                "deadline_at": self.deadline_at.isoformat()}


def sample_decisions(now: datetime | None = None) -> list[Decision]:
    t = now or datetime.now(UTC)
    d1 = Decision(
        decision_id="5a3e0d00-0000-4000-8000-000000000001",
        title="SAMPLE: magnet export curbs hit the motor line",
        card=("SAMPLE | Rare-earth magnet export curbs: RM-307 short at PLANT-GOA in 9 days. "
              "A: expedite air freight, USD 48,000, 4 days. B: qualify alternate supplier, USD 18,500, 14 days. "
              "Step-up needed."),
        spoken=("Sample decision. New export curbs on rare-earth magnets leave RM-307 short at PLANT-GOA in 9 days, "
                "and that stops 1,200 drone motors. Option A: expedite air freight for USD 48,000, parts in 4 days. "
                "Option B: qualify the alternate supplier for USD 18,500, parts in 14 days. "
                "Say approve option A or B, reject, or repeat."),
        options=(
            Option("A", "5a3e0d01-0000-4000-8000-00000000000a", "Expedite air freight", "USD 48,000", "-USD 9,500",
                   48000, "Air freight of 1,200 magnet sets from existing stock, parts in 4 days."),
            Option("B", "5a3e0d01-0000-4000-8000-00000000000b", "Qualify alternate supplier", "USD 18,500",
                   "+USD 4,200", 18500, "First article inspection and a trial order, parts in 14 days."),
        ),
        band_label="Over USD 15,000: phone step-up", step_up=True,
        created_at=t - timedelta(hours=2), deadline_at=t + timedelta(hours=6),
    )
    d2 = Decision(
        decision_id="5a3e0d00-0000-4000-8000-000000000002",
        title="SAMPLE: magnet buffer stock at PLANT-GOA",
        card=("SAMPLE | Rare-earth curbs: raise the RM-307 buffer at PLANT-GOA? "
              "A: raise to 6 weeks, USD 7,800. B: keep 3 weeks, USD 0."),
        spoken=("Sample decision. With the magnet export curbs, planning suggests a bigger RM-307 buffer at PLANT-GOA. "
                "Option A: raise it to 6 weeks for USD 7,800. Option B: keep 3 weeks at no cost. "
                "Say approve option A or B, reject, or repeat."),
        options=(
            Option("A", "5a3e0d02-0000-4000-8000-00000000000a", "Raise buffer to 6 weeks", "USD 7,800", "-USD 7,800",
                   7800, "Three extra weeks of RM-307 cover, ordered from the current supplier."),
            Option("B", "5a3e0d02-0000-4000-8000-00000000000b", "Keep buffer at 3 weeks", "USD 0", "USD 0", 0,
                   "No change; the exposure stays as planned."),
        ),
        band_label="Under USD 10,000", step_up=False,
        created_at=t - timedelta(hours=1), deadline_at=t + timedelta(hours=24),
    )
    return [d1, d2]


# --- brief number check (POST /v1/briefs/decision/{id}/check) ---------------------------------------------
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
# Spelled-out numbers the model might use instead of the template's digits. "one" is left out: it is far more
# often a pronoun ("the alternate one") than a quantity.
NUMBER_WORDS = frozenset(
    ["two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million", "billion", "half", "quarter", "dozen"]
)


def _numbers(text: str) -> set[str]:
    out: set[str] = set()
    for m in _NUMBER.findall(text):
        n = m.replace(",", "")
        out.add(n.rstrip("0").rstrip(".") if "." in n else n)
    return out


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def check_brief(text: str, template: str) -> tuple[bool, list[str]]:
    """Accepted only if every number in the text appears in the template (digits, and number words)."""
    reasons: list[str] = []
    allowed = _numbers(template)
    for n in sorted(_numbers(text) - allowed):
        reasons.append(f"number {n} is not in the template")
    for w in sorted((_words(text) & NUMBER_WORDS) - _words(template)):
        reasons.append(f"number word '{w}' is not in the template")
    if not text.strip():
        reasons.append("empty text")
    return not reasons, reasons


# --- voice grammar (POST /v1/voice/commands) ----------------------------------------------------------------
_LETTERS = {
    "a": "A", "one": "A", "1": "A", "first": "A", "ay": "A", "eh": "A",
    "b": "B", "two": "B", "2": "B", "second": "B", "bee": "B", "be": "B", "to": "B", "too": "B",
    "c": "C", "three": "C", "3": "C", "third": "C", "see": "C", "sea": "C",
}


@dataclass(frozen=True)
class Parsed:
    intent: str  # approve | reject | confirm | cancel | repeat | details | unknown
    letter: str | None = None
    reason: str | None = None
    normalized: str = ""
    score: float = 0.0

    def wire(self) -> dict[str, Any]:
        slots: dict[str, Any] = {}
        if self.letter:
            slots["option"] = self.letter
        if self.reason:
            slots["reason"] = self.reason
        return {"intent": self.intent, "slots": slots, "normalized": self.normalized, "score": self.score,
                "clarifier": None, "clarifier_slot": None}


def normalize(transcript: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", transcript.lower()).split())


def parse(transcript: str) -> Parsed:
    t = normalize(transcript)
    if re.fullmatch(r"(yes )?(i )?(confirm|confirmed)( it| that)?( please)?", t):
        return Parsed("confirm", normalized="confirm", score=0.95)
    if re.fullmatch(r"(cancel|stop|no|never mind|nevermind)( it| that| please)?", t):
        return Parsed("cancel", normalized="cancel", score=0.95)
    if re.fullmatch(r"(repeat|say (that|it) again|again|repeat (that|it|the brief))( please)?", t):
        return Parsed("repeat", normalized="repeat", score=0.95)
    m = re.fullmatch(r"(reject|decline)(?: it| this)?(?: because (.+))?", t)
    if m:
        return Parsed("reject", reason=m.group(2), normalized="reject" + (f" because {m.group(2)}" if m.group(2) else ""),
                      score=0.9)
    m = re.fullmatch(r"(?:more )?details?(?: (?:on|about|for))?(?: option)?(?: (\w+))?", t)
    if m:
        letter = _LETTERS.get(m.group(1) or "")
        return Parsed("details", letter=letter, normalized="details" + (f" option {letter.lower()}" if letter else ""),
                      score=0.85)
    m = re.fullmatch(r"(?:i )?(?:approve|go with|choose|pick|select|take)(?: the)?(?: option)? (\w+)(?: please)?"
                     r"|option (\w+)", t)
    if m:
        word = m.group(1) or m.group(2)
        letter = _LETTERS.get(word)
        return Parsed("approve", letter=letter or word.upper(), normalized=f"approve option {(letter or word).lower()}",
                      score=0.9 if letter else 0.5)
    return Parsed("unknown", normalized=t, score=0.0)
