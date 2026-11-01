"""The C3 verdict: the rule table of docs/design/M5_C3_CONTRACT.md section 3 and the spoken sentences of 3.1.

Deterministic and pure: the inputs are the code status (seal_code.verify), the registry status and history, and
the first-check status; the visual seal check never enters (it only sets ``tamper``, see ``tamper_of``). Every
number or date in a sentence comes from these inputs (``facts_text`` lists them for the number check of
tests/property/test_m5_c3_rules_property.py).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from types import MappingProxyType

VERDICTS = ("GENUINE_NEW", "GENUINE_PREVIOUSLY_ACTIVATED", "RETURNED_REFURBISHED", "CANNOT_VERIFY",
            "LIKELY_COUNTERFEIT")
REGISTRY_STATUSES = ("found", "unknown_unit", "sku_mismatch", "unavailable", "not_asked")
FIRST_CHECK_STATUSES = ("first", "same_checker", "other_checker", "not_recorded")
SIGNS = ("tape_over_seal", "seal_torn", "reglued", "sticker_over_seal", "seal_missing")
SIGN_WORDS = MappingProxyType({"tape_over_seal": "tape over the original", "seal_torn": "a torn seal",
                               "reglued": "signs of re-gluing", "sticker_over_seal": "a sticker over the seal",
                               "seal_missing": "no seal"})
MONTHS = ("", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")

# (code status) -> (rule, verdict, reason) for R1-R7; the registry rules R8-R10 likewise.
CODE_RULES = MappingProxyType({
    "not_a_seal_code": ("R1", "CANNOT_VERIFY", "code:not_a_seal_code"),
    "unknown_oem": ("R2", "CANNOT_VERIFY", "code:unknown_oem"),
    "oem_not_configured": ("R3", "CANNOT_VERIFY", "oem:not_configured"),
    "oem_unavailable": ("R4", "CANNOT_VERIFY", "oem:unavailable"),
    "unknown_key": ("R5", "LIKELY_COUNTERFEIT", "code:unknown_key"),
    "bad_signature": ("R6", "LIKELY_COUNTERFEIT", "code:bad_signature"),
    "bad_payload": ("R7", "CANNOT_VERIFY", "code:bad_payload"),
})
REGISTRY_RULES = MappingProxyType({
    "unavailable": ("R8", "CANNOT_VERIFY", "registry:unavailable"),
    "unknown_unit": ("R9", "CANNOT_VERIFY", "registry:unknown_unit"),
    "sku_mismatch": ("R10", "CANNOT_VERIFY", "registry:sku_mismatch"),
})
CANNOT_SAY = MappingProxyType({
    "R1": "It is not a seal code.", "R2": "The maker is not known.",
    "R3": "The maker's records cannot be reached.", "R4": "The maker's records cannot be reached.",
    "R7": "The maker's records do not match this code.", "R8": "The maker's records cannot be reached.",
    "R9": "The maker has no record of this unit.", "R10": "The maker's records do not match this code.",
})


@dataclass(frozen=True)
class Inputs:
    code: str  # seal_code.STATUSES
    registry: str = "not_asked"  # REGISTRY_STATUSES
    events: Sequence[tuple[str, date]] = ()  # (type, day) of the unit's history
    first_check: str = "not_recorded"  # FIRST_CHECK_STATUSES
    first_checked_at: datetime | None = None
    today: date = field(default_factory=date.today)


@dataclass(frozen=True)
class Verdict:
    verdict: str
    rule: str
    reasons: tuple[str, ...]
    sentences: tuple[str, ...]

    @property
    def say(self) -> str:
        return " ".join(self.sentences)


def spoken_date(d: date, today: date) -> str:
    return f"{d.day} {MONTHS[d.month]}" + (f" {d.year}" if d.year != today.year else "")


def _dates(events: Sequence[tuple[str, date]], kind: str) -> list[date]:
    return sorted(d for t, d in events if t == kind)


def history_dates(events: Sequence[tuple[str, date]]) -> dict[str, date | None]:
    """The first activation, the last return and the last refurbishment (what the sentences say)."""
    act, ret, ref = _dates(events, "activated"), _dates(events, "returned"), _dates(events, "refurbished")
    return {"activated": act[0] if act else None, "returned": ret[-1] if ret else None,
            "refurbished": ref[-1] if ref else None}


def decide(i: Inputs) -> Verdict:
    """R1-R14, first match wins (contract section 3)."""
    if i.code != "valid":
        rule, verdict, reason = CODE_RULES[i.code]
        if verdict == "LIKELY_COUNTERFEIT":
            return Verdict(verdict, rule, (reason,),
                           ("This code is not signed by the maker.", "This is likely a counterfeit."))
        return Verdict(verdict, rule, (reason,), ("I cannot verify this code.", CANNOT_SAY[rule]))
    if i.registry != "found":
        rule, verdict, reason = REGISTRY_RULES.get(i.registry, REGISTRY_RULES["unavailable"])
        return Verdict(verdict, rule, (reason,), ("I cannot verify this code.", CANNOT_SAY[rule]))
    types = {t for t, _ in i.events}
    h = history_dates(i.events)
    reasons = [f"history:{t}" for t in ("activated", "returned", "refurbished") if t in types]
    if i.first_check == "other_checker":
        reasons.append("first_check:other_checker")
    if "shipped_to_seller" not in types:
        reasons.append("history:not_shipped")

    def sd(d: date) -> str:
        return spoken_date(d, i.today)

    if "returned" in types or "refurbished" in types:
        parts = []
        if h["activated"]:
            parts.append(f"activated on {sd(h['activated'])}")
        if h["returned"]:
            parts.append(f"returned on {sd(h['returned'])}")
        if h["refurbished"]:
            parts.append(f"refurbished on {sd(h['refurbished'])}")
        return Verdict("RETURNED_REFURBISHED", "R11", tuple(reasons),
                       ("Code is genuine.", f"But this unit was {' and '.join(parts)}.", "It is not a new unit."))
    if "activated" in types and h["activated"]:
        return Verdict("GENUINE_PREVIOUSLY_ACTIVATED", "R12", tuple(reasons),
                       ("Code is genuine.", f"But this unit was activated on {sd(h['activated'])}.",
                        "It is not a new unit."))
    if i.first_check == "other_checker":
        when = f" on {sd(i.first_checked_at.date())}" if i.first_checked_at else ""
        return Verdict("CANNOT_VERIFY", "R13", tuple(reasons),
                       (f"Code is genuine, but it was first checked{when} by someone else.",
                        "A printed code can be copied, so I cannot verify this unit."))
    sentences = ["Code is genuine.", "This unit is new: it was never activated or returned."]
    if i.first_check == "same_checker" and i.first_checked_at and i.first_checked_at.date() != i.today:
        sentences.append(f"You first checked it on {sd(i.first_checked_at.date())}.")
    return Verdict("GENUINE_NEW", "R14", tuple(reasons), tuple(sentences))


def tamper_of(status: str, seal_found: bool | None, signs: Sequence[str]) -> bool | None:
    """True with a reported sign; False when finished, a seal was seen and no sign reported; else None."""
    if status != "done":
        return None
    if signs:
        return True
    return False if seal_found else None


def visual_sentence(signs: Sequence[str]) -> str:
    words = [SIGN_WORDS[s] for s in SIGNS if s in signs]
    if not words:
        return ""
    joined = words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]
    return f"The seal shows {joined}."


def facts_text(i: Inputs) -> str:
    """Every number the sentences may say: each history date and the first-check date, as spoken."""
    days = [d for _, d in i.events]
    if i.first_checked_at:
        days.append(i.first_checked_at.date())
    return " ".join(spoken_date(d, i.today) for d in days)
