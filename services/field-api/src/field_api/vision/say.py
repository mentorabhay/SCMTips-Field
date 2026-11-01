"""What the glasses say after a look (stage e): a template over the deterministic check, number-checked.

Every number in ``say`` must be one of the look's own figures (counts, pack, expiry, proposal): the local number
check of the M4 brief router (``briefs.numbers.values``) reads the digits and number words of the sentence, and a
sentence with any other number is replaced by the short template, and that one, if it ever failed too, by a sentence
without numbers. Batch codes and dates are never spoken (they are on the screen).
"""

from __future__ import annotations

from decimal import Decimal

from field_api.briefs.numbers import values
from field_api.vision.reconcile import Check, Expectation, plural

RULES_SAY = "I couldn't count them this time. Say the count, for example: receive, then the number."
NO_NUMBERS_SAY = "Look done. The counts are on the screen."
# M5-S01 two-step look: the first answer once SAM's instances are counted, then the label read.
PENDING_SAY = "Reading the labels."
LABELS_FAILED_SAY = "I couldn't read the labels. Say your numbers."


def allowed_numbers(check: Check, exp: Expectation) -> set[Decimal]:
    nums: set[int] = set()
    for v in check.counts.values():
        if v is not None:
            nums.add(v)
    for v in (check.proposal.get("receive"), check.proposal.get("flag")):
        if isinstance(v, int):
            nums.add(v)
    if check.units_difference is not None:
        nums.add(abs(check.units_difference))
    nums.update({check.unread, check.expired, check.near, len(check.flagged)})
    if check.pack is not None:
        nums.add(int(check.pack["expected_pieces_per_unit"]))
        if check.pack["pieces_difference"] is not None:
            nums.add(abs(int(check.pack["pieces_difference"])))
        for k, value, diff in check.pack_groups:
            nums.update({k, value, abs(diff)})
    if check.expiry is not None:
        nums.add(int(check.expiry["window_days"]))
        nums.add(len(check.expiry["batches"]))
    if exp.expected_pieces_per_unit is not None:
        nums.add(exp.expected_pieces_per_unit)
    return {Decimal(n).normalize() for n in nums}


def numbers_ok(text: str, allowed: set[Decimal]) -> bool:
    return values(text) <= allowed


def count_sentence(seen: int, expected: int | None, noun: str) -> str:
    """"20 of 20 packs." with an expected quantity, else "8 packs." (the first sentence of every counted say)."""
    if expected is not None:
        return f"{seen} of {expected} {plural(noun, int(expected))}."
    return f"{seen} {plural(noun, seen)}."


def first_say(seen: int, expected: int | None, exp: Expectation) -> str:
    """The first answer of a two-step look (M5-S01): the count only, then "Reading the labels.". Damage, pack size
    and expiry come from the label read, so nothing else is said yet. Number-checked against the count."""
    text = f"{count_sentence(seen, expected, exp.object_noun)} {PENDING_SAY}"
    allowed = {Decimal(n).normalize() for n in (seen, expected) if n is not None}
    return text if numbers_ok(text, allowed) else f"Counted. {PENDING_SAY}"


def next_say(final_say: str, first: str) -> str:
    """What the app speaks when the look is final, after it spoke ``first``: the final ``say`` without the count
    sentence it already heard (when the count is unchanged), else the whole final ``say``. A part of a checked
    sentence set, so every number in it is still one of the look's own figures."""
    lead = first.removesuffix(PENDING_SAY).strip()
    if lead and final_say.startswith(lead + " "):
        rest = final_say[len(lead):].strip()
        if rest:
            return rest
    return final_say


def compose(check: Check, exp: Expectation) -> str:
    """The full sentence set: count, damage, pack groups (at most two), expiry, unread labels, the proposal."""
    c = check.counts
    if c["seen"] is None:
        return RULES_SAY
    seen = int(c["seen"])
    noun = exp.object_noun
    parts: list[str] = [count_sentence(seen, c["expected"], noun)]
    if c["damaged"]:
        parts.append(f"{c['damaged']} damaged.")
    for k, value, diff in check.pack_groups[:2]:
        parts.append(f"{k} {plural(noun, k)} {'hold' if k != 1 else 'holds'} {value}, not "
                     f"{exp.expected_pieces_per_unit}: {abs(diff)} {plural('piece', abs(diff))} "
                     f"{'short' if diff < 0 else 'over'}.")
    if len(check.pack_groups) > 2:
        parts.append("More pack sizes differ; see the screen.")
    if check.expired:
        parts.append(f"{check.expired} expired.")
    if check.near:
        parts.append(f"{check.near} {'expire' if check.near != 1 else 'expires'} within {exp.window_days} days.")
    if check.expiry is not None and len(check.expiry["batches"]) > 1:
        parts.append(f"{len(check.expiry['batches'])} batches.")
    if check.unread:
        parts.append(f"{check.unread} {plural('label', check.unread)} not read.")
    parts.append(f"Receive {check.proposal['receive']}, flag {check.proposal['flag']}?")
    return " ".join(parts)


def short(check: Check) -> str:
    return f"{check.counts['seen']} seen. Receive {check.proposal['receive']}, flag {check.proposal['flag']}?"


def say_for(check: Check, exp: Expectation) -> str:
    """The checked sentence: the full one, else the short one, else one without numbers."""
    if check.counts["seen"] is None:
        return RULES_SAY
    allowed = allowed_numbers(check, exp)
    for text in (compose(check, exp), short(check)):
        if numbers_ok(text, allowed):
            return text
    return NO_NUMBERS_SAY
