"""Rules mode (M3 contract §4, ``ai: "rules"``): fixed answers, at once and without the network.

Since M4 (owner's field test, 31 Oct 2026: Start Work waited 6-7 s on model timeouts) rules answer FIRST: every
event and every utterance these rules classify is answered here with no model call; only what they cannot
classify (and "what is this" about a photo without a code) goes to the model, and any model failure comes back
here.

Covers: greeting + work list, "what do we have", "most urgent", "start <type or number>", "what's next",
"how many left", "what is this" (code lookup only), the sandbox unknown-code dialog ("What is it?" -> name ->
"How many?" -> add through the sandbox port), "summary", "repeat", "help", what done means, pause / resume /
session end, step done, and the job words the phone may forward (post, all here, count N, cancel). On sandbox
sites (M4) also "new home receipt" and "count shelf <bin>" / "count a shelf" (then "Which shelf?"), which create
the task through the sandbox ports and open it; "nothing assigned" offers both. Work never stops because of the
AI. No network: only the database (task list, records) and the injected ports.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from field_api.assistant.prompts import DONE, DONE_SHORT, clip_say
from field_api.assistant.tools import SANDBOX_TASK_TYPES, AssistantTools
from field_api.assistant.work import count_by_type, remaining_lines, type_word
from field_api.auth.permissions import has_permission

SKIP = "skip"

_UNITS = MappingProxyType({
    "zero": 0, "none": 0, "nothing": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "dozen": 12,
})
_TENS = MappingProxyType({"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
                          "eighty": 80, "ninety": 90})
_ORDINALS = MappingProxyType({"first": 0, "1st": 0, "one": 0, "second": 1, "2nd": 1, "two": 1, "third": 2, "3rd": 2,
                              "three": 2, "fourth": 3, "4th": 3, "four": 3, "fifth": 4, "5th": 4, "five": 4})
_TYPE_SYNONYMS = (
    ("putaway", r"put[ -]?aways?|store|storing|stow"),
    ("receive", r"receipts?|receiv\w*|deliver(y|ies)|inbound|goods receipt"),
    ("pick", r"picks?|picking|outbound|order"),
    ("count", r"counts?|counting|inventory|stock ?take|cycle count"),
    ("audit", r"audits?|sector audit"),
    ("swap", r"swaps?|replace\w*|exchange"),
)

INTENTS = (
    ("cancel", r"^(cancel|stop|never ?mind|forget it|no thanks?)\b"),
    ("confirm", r"\bconfirm\b"),
    # M5 supplier claims (stream X): before "start" ("open a claim") and "next" ("next claim")
    ("make_claim", r"\b(?:make|raise|create|file|open|start|log) (?:a |an |the )?(?:new )?(?:supplier )?claim\b|"
                   r"^claim (?:it|this|that)$"),
    ("claims_next", r"^(?:(?:ok(?:ay)?|please|so) )*(?:(?:read|show|give me|what'?s|what are|any|open|my) )*"
                    r"(?:the )?(?:next |first |open |draft |waiting )?claims?(?: please)?$|\bnext claim\b"),
    ("approve", r"^(?:(?:ok(?:ay)?|yes|so) )*(?:i )?approve\b(?: (?:it|this|that|the claim|claim))?(?: please)?$"),
    ("reject", r"^(?:(?:ok(?:ay)?|so) )*(?:i )?reject\b(?: (?:it|this|that|the claim|claim))?"
               r"(?: ?(?:because|reason|as)\b ?(?P<arg>.*))?$"),
    # M4 sandbox: before "start" (which opens an existing job) and "count" (which counts in the open job)
    ("new_receipt", r"\b(?:new|another|create|make)\b(?: a| an)?(?: new)?(?: home)? (?:goods )?receipt\b|"
                    r"\bhome receipt\b"),
    ("new_count", r"^(?:(?:ok(?:ay)?|please|let'?s|can you) )*(?:(?:start|begin|do|create|make|open) )?"
                  r"(?:(?:a|an|the) )?(?:new )?count (?:(?:of|for) )?(?:(?:a|an|the|one|this|that) )?(?:new )?"
                  r"(?:shelf|shelves|bin)\b\s*(?P<arg>.*)$"),
    ("new_count", r"\b(?:new|another|create|make)\b(?: a| an)?(?: new)?(?: shelf| bin)? count\b"
                  r"(?: (?:of|for) (?:(?:the|a) )?(?:shelf |bin )?(?P<arg>.*))?$"),
    ("repeat", r"^(repeat|say (that|it) again|again|pardon|come again|what did you say)\b"),
    ("help", r"^help\b|what can (i|you) (say|do)"),
    ("summary", r"\bsummary\b|\brecap\b|how did (i|we) do|what did (i|we) do"),
    ("done_def", r"what (does|is) done|when (am i|is it|are we) done|what does done mean|how do i finish|"
                 r"definition of done"),
    ("left", r"how many (are |is )?(left|remaining|more|to go)|how much (is )?left|^(left|remaining)$"),
    ("next", r"what'?s next|what next|next step|where (do i go|next|now)|what now|^next$|"
             r"what (should i|do i) (do|look at)( next)?$"),
    ("what_is", r"what'?s (this|that|it)\b|what is (this|that|it)\b|identify|what am i looking at"),
    ("urgent", r"urgent|most important|\bpriority\b|what (should i do |do i do )?first|where do i start"),
    ("start", r"^(?:ok(?:ay)?,? )?(?:please )?(?:start|open|begin|let'?s (?:do|start))\b\s*(?P<arg>.*)$"),
    ("post", r"^(post( it)?|finish( it| the job| job)?|i'?m (done|finished)|done with (this|the job)|wrap (it )?up)$"),
    ("all_here", r"^all here$|everything('?s| is) here"),
    ("count", r"^count (?P<arg>\S.*)$"),
    ("work", r"what do (we|i) have|what'?s (on )?(for )?(today|my list|the list)|my (jobs|work|tasks)|"
             r"open (jobs|work|tasks)|what (jobs|work|tasks)|list (the )?(jobs|work|tasks)|\btoday\b"),
    ("greet", r"^(hi|hello|hey|good (morning|afternoon|evening))\b"),
)
_COMPILED = tuple((name, re.compile(rx)) for name, rx in INTENTS)
_DIGIT_WORDS = MappingProxyType({"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
                                "six": "6", "seven": "7", "eight": "8", "nine": "9"})
_YES = re.compile(r"^(yes|yeah|yep|yup|sure|correct|right|ok(ay)?|do it|add it|please do|go ahead)\b(?!.*\bnot?\b)")


def normalise(text: str | None) -> str:
    t = (text or "").lower().replace("’", "'")
    t = re.sub(r"[^\w' -]+", " ", t)
    return " ".join(t.split())


def intent(text: str | None) -> tuple[str, str]:
    """(intent name, argument) for one utterance; ('unknown', '') if no rule matches."""
    t = normalise(text)
    if not t:
        return "unknown", ""
    for name, rx in _COMPILED:
        m = rx.search(t)
        if m:
            arg = m.groupdict().get("arg") or ""
            return name, arg.strip()
    return "unknown", ""


def bin_key(text: str | None) -> str:
    """A bin code as spoken or printed, reduced for matching: digit words to digits, separators and filler words
    dropped, upper case ("zero three dash zero five" -> "0305", "HOME-A" -> "HOMEA", "shelf a" -> "A")."""
    words = normalise(text).replace("-", " ").split()
    out = [_DIGIT_WORDS.get(w, w) for w in words if w not in ("dash", "hyphen", "minus", "shelf", "bin", "the",
                                                                    "number", "no", "code")]
    return re.sub(r"[^0-9a-z]", "", "".join(out)).upper()


def match_bin(text: str | None, bins: list[str]) -> str | None:
    """The one bin ``text`` names: exact (after bin_key), else the only bin whose key ends with it."""
    k = bin_key(text)
    if not k:
        return None
    keyed = [(b, bin_key(b)) for b in bins]
    exact = [b for b, bk in keyed if bk == k]
    if len(exact) == 1:
        return exact[0]
    tail = [b for b, bk in keyed if bk.endswith(k)]
    return tail[0] if len(tail) == 1 else None


def is_yes(text: str | None) -> bool:
    return bool(_YES.search(normalise(text)))


def parse_quantity(text: str | None) -> Decimal | str | None:
    """A spoken quantity: digits ("12", "2.5") or words up to the thousands ("twenty five", "a dozen"); SKIP for
    "skip" / "don't know"; None if there is no number."""
    t = normalise(text)
    if re.search(r"\b(skip|don'?t know|no idea|not sure|unknown)\b", t):
        return SKIP
    m = re.search(r"\d+(?:[.,]\d+)?", (text or "").lower())
    if m:
        return Decimal(m.group(0).replace(",", "."))
    total, current, seen = 0, 0, False
    for w in t.replace("-", " ").split():
        if w in _UNITS:
            current += _UNITS[w]
            seen = True
        elif w in _TENS:
            current += _TENS[w]
            seen = True
        elif w == "hundred":
            current = max(current, 1) * 100
            seen = True
        elif w == "thousand":
            total += max(current, 1) * 1000
            current = 0
            seen = True
        elif w in ("and", "a", "an") or not seen:
            continue
        else:
            break
    return Decimal(total + current) if seen else None


_NAME_PREFIX = re.compile(r"^(it'?s|it is|this is|that'?s|that is|they'?re|they are|i think it'?s|a|an|some|the)\s+")


def clean_name(text: str | None) -> str:
    t = " ".join((text or "").strip().strip(".!?").split())
    low = t.lower()
    changed = True
    while changed:
        changed = False
        m = _NAME_PREFIX.match(low)
        if m:
            t, low, changed = t[m.end():], low[m.end():], True
    return t[:80].strip()


def _qty_text(q: Decimal | None) -> str:
    if q is None:
        return "no quantity"
    return f"{q.normalize():f}"


def _fmt_qty(v: Any) -> str:
    try:
        return f"{Decimal(str(v)).normalize():f}"
    except Exception:
        return str(v)


@dataclass
class Reply:
    say: str
    card: dict[str, str]
    actions: list[dict[str, Any]] = field(default_factory=list)
    dialog: dict[str, Any] | None = None
    task_id: str | None = None

    def clipped(self) -> Reply:
        self.say = clip_say(self.say)
        return self


def _sentence(text: Any) -> str:
    t = " ".join(str(text or "").split())
    return t if not t or t[-1] in ".!?" else t + "."


def _card(title: str, body: str = "") -> dict[str, str]:
    return {"title": title, "body": body}


LISTEN_CMD = MappingProxyType({"type": "listen", "mode": "command"})
LISTEN_FREE = MappingProxyType({"type": "listen", "mode": "free"})


class RulesEngine:
    def __init__(self, tools: AssistantTools, last_said: str | None = None) -> None:
        self.tools = tools
        self.last_said = last_said

    # ------------------------------------------------------------------ entry
    def answer(self, event: str, text: str | None, code: str | None, has_photo: bool) -> Reply:
        dialog = self.tools.ctx.dialog
        if event == "session_start":
            return self.work_list(greeting=True)
        if event == "session_end":
            return self.summary(ending=True)
        if event == "pause":
            return Reply("Paused. Say resume when you're ready.", _card("Paused"), dialog=dialog)
        if event == "resume":
            r = self.next_step(prefix="Welcome back.")
            r.dialog = dialog
            return r
        if event == "step_done":
            return self.next_step(prefix="Done.")
        if event == "unknown_code":
            return self.unknown_code(code or "")
        if event == "scan":
            if dialog and dialog.get("kind") == "new_count" and code:
                picked = self._bin_of(code)
                if picked:
                    return self.create_count(picked)
            return self.code_reply(code or "", from_scan=True)
        if event == "photo":
            if code:
                return self.code_reply(code)
            return Reply("I can't recognise a photo without the AI. Look at the barcode so I can read it.",
                         _card("Look at the barcode"), [dict(LISTEN_CMD)], dialog=dialog)
        # utterance
        if dialog and dialog.get("kind") == "sandbox_item":
            return self.sandbox_dialog(text, dialog)
        name, arg = intent(text)
        if dialog and dialog.get("kind") == "new_count":
            answered = self.count_bin_dialog(text, name)
            if answered is not None:
                return answered
        if dialog and dialog.get("kind") in ("claim", "claim_confirm") and name == "unknown":
            return self.claim_reprompt(dialog)
        if name == "what_is":
            if code:
                return self.code_reply(code)
            if has_photo:
                return Reply("I can't recognise a photo without the AI. Look at the barcode so I can read it.",
                             _card("Look at the barcode"))
            return Reply("Look at the barcode and I'll tell you what it is.", _card("Look at the barcode"))
        handlers: dict[str, Callable[[], Reply]] = {
            "cancel": lambda: Reply("OK.", _card("Cancelled"), [{"type": "command", "command": "cancel"}]
                                    if self.tools.ctx.task_id else []),
            "confirm": lambda: (self.claim_confirm(text) if dialog and dialog.get("kind") == "claim_confirm" else
                                Reply("Say post first, then confirm on the review step. I can't confirm for you.",
                                      _card("Confirm is yours", "Posting needs your own confirm on the phone."))),
            "make_claim": self.make_claim,
            "claims_next": lambda: self.next_claim(advance="next" in normalise(text)),
            "approve": lambda: self.claim_decide("approve", None),
            "reject": lambda: self.claim_decide("reject", arg or None),
            "repeat": lambda: Reply(self.last_said or "There is nothing to repeat yet.", _card("Repeat")),
            "help": self.help,
            "summary": self.summary,
            "done_def": self.done_definition,
            "left": self.how_many_left,
            "next": self.next_step,
            "urgent": self.most_urgent,
            "start": lambda: self.start(arg),
            "post": self.post,
            "all_here": lambda: (Reply("All here.", _card("All here"), [{"type": "command", "command": "all_here"}])
                                 if self.tools.ctx.task_id else self.need_job()),
            "count": lambda: self.count(arg),
            "work": self.work_list,
            "greet": lambda: self.work_list(greeting=True),
            "new_receipt": self.new_receipt,
            "new_count": lambda: self.new_count(arg),
        }
        handler = handlers.get(name)
        if handler is not None:
            return handler()
        return Reply("Sorry, I didn't catch that. Say what's next, how many left, or help.",
                     _card("Try", "what's next · how many left · what is this · start receipt · summary"),
                     [dict(LISTEN_CMD)])

    # ------------------------------------------------------------------ M5 supplier claims (stream X)
    def _may(self, permission: str) -> bool:
        return has_permission(self.tools.ctx.principal.permissions, permission)

    def _claims_refusal(self, permission: str, who: str) -> Reply | None:
        if not self.tools.can_claim:
            return Reply("Claims are not available in this build.", _card("No claims"))
        if not self._may(permission):
            return Reply(f"Claims are {who}.", _card("Not for your role"), [dict(LISTEN_CMD)])
        return None

    def make_claim(self) -> Reply:
        refused = self._claims_refusal("field.claim.create", "made by the receiving team")
        if refused is not None:
            return refused
        look_id = self.tools.ctx.look_id
        port = self.tools.ctx.ports.claims
        if not look_id or port is None:
            return Reply("Take a look first, then say make a claim.", _card("No look yet"), [dict(LISTEN_CMD)])
        principal = self.tools.ctx.principal
        r = self.tools.claim_call("make_claim", {"look_id": look_id}, lambda: port.create(principal, look_id))
        if not r["ok"]:
            return Reply(f"No claim made. {_sentence(r['error'])}", _card("No claim", str(r["error"])))
        c = r["result"]
        return Reply(f"Claim drafted for a supervisor. {clip_say(c['text'], 1)}", _card("Claim draft", c["text"]),
                     task_id=self.tools.ctx.task_id)

    def _claim_dialog(self) -> dict[str, Any] | None:
        d = self.tools.ctx.dialog
        return d if d and d.get("kind") in ("claim", "claim_confirm") and d.get("claim_id") else None

    def next_claim(self, advance: bool = False) -> Reply:
        refused = self._claims_refusal("field.claim.decide", "approved by a supervisor")
        if refused is not None:
            return refused
        port = self.tools.ctx.ports.claims
        assert port is not None
        principal = self.tools.ctx.principal
        r = self.tools.claim_call("next_claim", {}, lambda: port.drafts(principal))
        if not r["ok"]:
            return Reply(f"I can't read the claims. {_sentence(r['error'])}", _card("Claims"))
        drafts: list[dict[str, Any]] = r["result"]
        if not drafts:
            return Reply("No claims are waiting.", _card("No claims"), [dict(LISTEN_CMD)])
        current = (self._claim_dialog() or {}).get("claim_id")
        ids = [d["claim_id"] for d in drafts]
        i = ids.index(current) + 1 if advance and current in ids else 0
        if i >= len(drafts):
            return Reply("No more claims are waiting.", _card("No more claims"), [dict(LISTEN_CMD)])
        c = drafts[i]
        title = f"Claim {i + 1} of {len(drafts)}"
        return Reply(f"{title}; say approve or reject. {clip_say(c['text'], 1)}", _card(title, c["text"]),
                     [dict(LISTEN_CMD)], dialog={"kind": "claim", "claim_id": c["claim_id"], "version": c["version"]})

    def _claim_refused(self, r: dict[str, Any], prefix: str) -> Reply:
        code = str(r.get("code") or "")
        if code.startswith("FIELD-ETAG") or code == "FIELD-CLM-409-STATE":
            return Reply(f"{prefix} The claim changed; say next claim to hear it again.", _card("Claim changed"),
                         [dict(LISTEN_CMD)])
        return Reply(f"{prefix} {_sentence(r.get('error'))}", _card("Claim", str(r.get("error"))), [dict(LISTEN_CMD)])

    def claim_decide(self, decision: str, reason: str | None) -> Reply:
        refused = self._claims_refusal("field.claim.decide", "approved by a supervisor")
        if refused is not None:
            return refused
        d = self._claim_dialog()
        port = self.tools.ctx.ports.claims
        if d is None or port is None:
            return Reply("Say next claim first, so I know which claim.", _card("Which claim?"), [dict(LISTEN_CMD)])
        principal, cid, version = self.tools.ctx.principal, str(d["claim_id"]), int(d.get("version") or 0)
        r = self.tools.claim_call("claim_decision", {"claim_id": cid, "decision": decision},
                                  lambda: port.decide(principal, cid, version, decision, reason))
        if not r["ok"]:
            return self._claim_refused(r, "Not decided.")
        answer, out = r["result"]
        return Reply(answer["say"], _card(f"{decision.title()}: say confirm", out["text"]), [dict(LISTEN_CMD)],
                     dialog={"kind": "claim_confirm", "claim_id": cid, "version": out["version"],
                             "decision": decision})

    def claim_confirm(self, words: str | None) -> Reply:
        d = self._claim_dialog()
        port = self.tools.ctx.ports.claims
        if d is None or port is None or not self._may("field.claim.decide"):
            return Reply("Say next claim first, so I know which claim.", _card("Which claim?"), [dict(LISTEN_CMD)])
        principal, cid, version = self.tools.ctx.principal, str(d["claim_id"]), int(d.get("version") or 0)
        r = self.tools.claim_call("claim_confirm", {"claim_id": cid},
                                  lambda: port.confirm(principal, cid, version, words))
        if not r["ok"]:
            if r.get("code") == "FIELD-CLM-422-CONFIRM-EXPIRED":
                return Reply("Too late to confirm; the claim is waiting again. Say next claim to hear it.",
                             _card("Not confirmed", "Confirm within 10 seconds."), [dict(LISTEN_CMD)])
            return self._claim_refused(r, "Not confirmed.")
        answer, out = r["result"]
        return Reply(answer["say"], _card(f"Claim {out['status']}", out["text"]), [dict(LISTEN_CMD)])

    def claim_reprompt(self, dialog: dict[str, Any]) -> Reply:
        if dialog.get("kind") == "claim_confirm":
            return Reply("Say confirm, or cancel.", _card("Say confirm"), [dict(LISTEN_CMD)], dialog=dialog)
        return Reply("Say approve or reject, or next claim.", _card("Approve or reject"), [dict(LISTEN_CMD)],
                     dialog=dialog)

    # ------------------------------------------------------------------ work
    # ------------------------------------------------------------------ sandbox: new receipts and counts (M4)
    @property
    def _offers_new_work(self) -> bool:
        return self.tools.ctx.site_mode == "sandbox" and self.tools.can_create

    def no_work(self, prefix: str = "") -> Reply:
        """Nothing open: on a sandbox site, offer a new home receipt or a shelf count (owner's test, 31 Oct)."""
        if self._offers_new_work:  # two sentences at most, with or without the prefix sentence
            say = (f"{prefix}Nothing is assigned here; say new home receipt, or count a shelf." if prefix
                   else "Nothing is assigned here right now. Say new home receipt, or count a shelf.")
            return Reply(say,
                         _card("Nothing assigned", "new home receipt · count a shelf"), [dict(LISTEN_CMD)])
        return Reply(prefix + "No open jobs at this site right now.", _card("No open jobs"), [dict(LISTEN_CMD)])

    def _sandbox_refusal(self, what: str) -> Reply | None:
        if self.tools.ctx.site_mode != "sandbox":
            return Reply(f"This is a production site, so {what} come from the ERP. Ask what we have to hear the "
                         "open jobs.", _card("Production site", f"New {what} only on a sandbox site"),
                         [dict(LISTEN_CMD)])
        if not self.tools.can_create:
            return Reply(f"I can't create {what} in this build.", _card("Not available"))
        return None

    def new_receipt(self) -> Reply:
        refused = self._sandbox_refusal("receipts")
        if refused is not None:
            return refused
        r = self.tools.new_receipt()
        if not r.get("ok"):
            return Reply(f"I couldn't create the receipt. {_sentence(r.get('error'))}",
                         _card("No receipt", str(r.get("error"))))
        return Reply("New home receipt open. Look at each box's barcode and I'll add it.",
                     _card(f"Delivery {r['ref_doc_no']}", DONE.get("receive", "")),
                     [{"type": "open_task", "task_id": r["task_id"]}], task_id=r["task_id"])

    def _bins_say(self, bins: list[str]) -> str:
        if 0 < len(bins) <= 4:
            return "Say " + (", ".join(bins[:-1]) + " or " + bins[-1] if len(bins) > 1 else bins[0]) + "."
        return "Look at the shelf label and say its code."

    def _bin_of(self, text: str) -> str | None:
        return match_bin(text, self.tools.site_bins())

    def new_count(self, arg: str) -> Reply:
        refused = self._sandbox_refusal("counts")
        if refused is not None:
            return refused
        bins = self.tools.site_bins()
        if not bins:
            return Reply("This site has no shelves set up, so I can't start a count.", _card("No shelves"))
        if not arg.strip():
            if len(bins) == 1:
                return self.create_count(bins[0])
            return Reply("Which shelf? " + self._bins_say(bins), _card("Which shelf?", "\n".join(bins[:20])),
                         [dict(LISTEN_FREE)], dialog={"kind": "new_count"})
        picked = match_bin(arg, bins)
        if picked is None:
            return Reply(f"I don't know shelf {arg} here. " + self._bins_say(bins),
                         _card("Which shelf?", "\n".join(bins[:20])), [dict(LISTEN_FREE)], dialog={"kind": "new_count"})
        return self.create_count(picked)

    def count_bin_dialog(self, text: str | None, name: str) -> Reply | None:
        """The answer to "Which shelf?"; None hands a different request back to the normal rules."""
        if name == "cancel":
            return Reply("OK, no count.", _card("Cancelled"))
        if name == "new_count":
            return None
        picked = self._bin_of(text or "")
        if picked is not None:
            return self.create_count(picked)
        if name != "unknown":
            return None  # another request: the dialog closes
        bins = self.tools.site_bins()
        return Reply("Which shelf? " + self._bins_say(bins), _card("Which shelf?", "\n".join(bins[:20])),
                     [dict(LISTEN_FREE)], dialog={"kind": "new_count"})

    def create_count(self, storage_bin: str) -> Reply:
        r = self.tools.new_count(storage_bin)
        if not r.get("ok"):
            return Reply(f"I couldn't start the count. {_sentence(r.get('error'))}",
                         _card("No count", str(r.get("error"))))
        return Reply(f"Count of shelf {storage_bin} open. Look at each box's barcode and say how many.",
                     _card(f"Count {storage_bin}", DONE.get("count", "")),
                     [{"type": "open_task", "task_id": r["task_id"]}], task_id=r["task_id"])

    # ------------------------------------------------------------------ work
    def work_list(self, greeting: bool = False) -> Reply:
        work = self.tools.work()
        hello = "Hi, you" if greeting else "You"
        if not work:
            return self.no_work("Hi. " if greeting else "")
        top = work[0]
        n = len(work)
        say = (f"{hello} have {n} {'job' if n == 1 else 'jobs'}: {count_by_type(work)}. "
               f"Most urgent is {top['title']}; say start to open it.")
        body = "\n".join(f"{i}. {t['title']} — {t['subtitle']}" for i, t in enumerate(work[:10], start=1))
        return Reply(say, _card(f"{n} open {'job' if n == 1 else 'jobs'}", body), [dict(LISTEN_CMD)])

    def most_urgent(self) -> Reply:
        work = self.tools.work()
        if not work:
            return self.no_work()
        t = work[0]
        why = " It's already started." if t["status"] == "in_progress" else ""
        return Reply(f"Most urgent is {t['title']}.{why} Say start to open it.",
                     _card(t["title"], t["subtitle"] or ""), [dict(LISTEN_CMD)])

    def _find(self, arg: str) -> tuple[dict[str, Any] | None, str]:
        work = self.tools.work()
        a = normalise(arg)
        a = re.sub(r"^(the|a|my|job|number|no)\s+", "", a).strip()
        if not work:
            return None, "No open jobs at this site right now."
        if a in ("", "it", "that", "this", "job", "work", "next", "next one", "the job", "one", "now"):
            return work[0], ""
        digits = re.findall(r"\d{2,}", a)
        if digits:
            d = digits[0]
            for t in work:
                ref = str(t.get("ref_doc_no") or "")
                if ref == d or ref.endswith(d) or d in str(t.get("title") or ""):
                    return t, ""
            return None, f"No open job matches {d}."
        for ttype, rx in _TYPE_SYNONYMS:
            if re.search(rf"\b(?:{rx})\b", a):
                for t in work:
                    if t["type"] == ttype:
                        return t, ""
                return None, f"There is no open {type_word(ttype)} here."
        first = a.split(" ")[0]
        if first in _ORDINALS:
            i = _ORDINALS[first]
            if i < len(work):
                return work[i], ""
            return None, f"There are only {len(work)} open jobs."
        return None, "I didn't catch which job. Say start receipt, start count, or a document number."

    def start(self, arg: str) -> Reply:
        t, why = self._find(arg)
        if t is None:
            return Reply(why, _card("Which job?"), [dict(LISTEN_CMD)])
        if t["id"] == self.tools.ctx.task_id:
            return Reply(f"You're on {t['title']}. {DONE_SHORT.get(t['type'], '')}", _card(t["title"]), task_id=t["id"])
        return Reply(f"Opening {t['title']}. {DONE_SHORT.get(t['type'], '')}",
                     _card(t["title"], DONE.get(t["type"], "")),
                     [{"type": "open_task", "task_id": t["id"]}], task_id=t["id"])

    def need_job(self) -> Reply:
        return Reply("Open a job first. Say start, or ask what we have today.", _card("No job open"), [dict(LISTEN_CMD)])

    def post(self) -> Reply:
        t = self.tools.current_task()
        if t is None:
            return self.need_job()
        left = remaining_lines(t)
        if left and t["type"] in ("putaway", "pick", "audit", "swap", "count"):
            n = len(left)
            return Reply(f"{n} {'line is' if n == 1 else 'lines are'} still open. {DONE_SHORT.get(t['type'], '')}",
                         _card(t["title"], DONE.get(t["type"], "")), task_id=t["id"])
        return Reply("Check the review, then say confirm.", _card(t["title"], "Review, then confirm."),
                     [{"type": "command", "command": "post"}], task_id=t["id"])

    def count(self, arg: str) -> Reply:
        if not self.tools.ctx.task_id:
            return self.need_job()
        q = parse_quantity(arg)
        if not isinstance(q, Decimal):
            return Reply("Say count and a number, like count four.", _card("Count"))
        return Reply(f"Count {_qty_text(q)}.", _card("Count", _qty_text(q)),
                     [{"type": "command", "command": "count", "value": float(q)}], task_id=self.tools.ctx.task_id)

    # ------------------------------------------------------------------ in a job
    def _line_hint(self, t: dict[str, Any], ln: dict[str, Any]) -> str:
        desc = ln.get("description") or ln.get("material") or "the item"
        b, pos = ln.get("bin"), ln.get("position")
        qty = f"{_fmt_qty(ln['expected_qty'])} {ln.get('uom') or ''}".strip() if "expected_qty" in ln else ""
        ttype = t["type"]
        if ttype == "count":  # blind: never a quantity
            return f"Next: bin {b}, {desc}. Count what you see." if b else f"Next: {desc}. Count what you see."
        if ttype == "putaway":
            return f"Next: take {desc} to bin {b} and scan the bin." if b else f"Next: store {desc}."
        if ttype == "pick":
            return f"Next stop: bin {b}, pick {qty} of {desc}." if b else f"Next: pick {qty} of {desc}."
        if ttype == "audit":
            return f"Next: {pos or desc}. Scan the unit's serial."
        if ttype == "swap":
            return f"Remove unit {ln.get('expected_serial')} at {pos}. Scan it, then the new unit."
        return f"Next: {desc}, {qty}. Scan it, then say the count." if qty else f"Next: {desc}. Scan it."

    def next_step(self, prefix: str = "") -> Reply:
        t = self.tools.current_task()
        pre = (prefix + " ") if prefix else ""
        if t is None:
            work = self.tools.work()
            if not work:
                return self.no_work(pre)
            return Reply(pre + f"Next job: {work[0]['title']}. Say start to open it.",
                         _card(work[0]["title"], work[0]["subtitle"] or ""), [dict(LISTEN_CMD)])
        left = remaining_lines(t)
        if not left:
            return Reply(pre + "Every line is done. Say post to finish.", _card(t["title"], "Every line is done."),
                         task_id=t["id"])
        ln = left[0]
        hint = self._line_hint(t, ln)
        if prefix:  # two sentences at most: drop the second sentence of the hint
            hint = hint.split(". ")[0].rstrip(".") + "."
        body = " · ".join(str(x) for x in (ln.get("bin"), ln.get("position"), ln.get("material"), ln.get("description"))
                          if x)
        return Reply(pre + hint, _card(f"Line {ln.get('line_no')}", body), task_id=t["id"])

    def how_many_left(self) -> Reply:
        t = self.tools.current_task()
        if t is None:
            n = len(self.tools.work())
            if not n:
                return self.no_work()
            return Reply(f"{n} open {'job' if n == 1 else 'jobs'} at this site.", _card("Open jobs", str(n)))
        lines = t.get("lines") or []
        left = remaining_lines(t)
        say = f"{len(left)} of {len(lines)} {'line' if len(lines) == 1 else 'lines'} left."
        if t["type"] in ("receive", "pick") and left:
            pieces = sum(Decimal(str(ln.get("expected_qty") or 0)) for ln in left)
            say += f" {_fmt_qty(pieces)} pieces to go."
        return Reply(say, _card(t["title"], say), task_id=t["id"])

    def done_definition(self) -> Reply:
        t = self.tools.current_task()
        if t is None:
            return Reply("Every job is done when each line is handled and you post and confirm it.",
                         _card("Done means", "\n".join(f"{k}: {v}" for k, v in DONE.items())))
        return Reply(DONE.get(t["type"], "Handle each line, then post."), _card(t["title"], DONE.get(t["type"], "")),
                     task_id=t["id"])

    def help(self) -> Reply:
        body = "what do we have · what's most urgent · start receipt · what's next · how many left · what is this · summary"
        if self._offers_new_work:
            return Reply("Ask what we have, what's next, how many left, or what is this. On this home site you can "
                         "also say new home receipt, or count a shelf.",
                         _card("You can say", body + " · new home receipt · count a shelf"), [dict(LISTEN_CMD)])
        return Reply("Ask what we have today, what's next, how many left, or what is this. Say start and a job to "
                     "open it.", _card("You can say", body), [dict(LISTEN_CMD)])

    def summary(self, ending: bool = False) -> Reply:
        s = self.tools.session_summary()
        docs = s["documents"]
        say = (f"This session: {s['jobs_done']} of {s['jobs']} jobs done and {len(docs)} SAP "
               f"{'document' if len(docs) == 1 else 'documents'}.")
        if ending:
            say = "Session ended. " + say
        body = f"Turns: {s['turns']}\nJobs: {s['jobs']} (done {s['jobs_done']})\nDocuments: {', '.join(docs) or '-'}"
        return Reply(say, _card("Session summary", body))

    # ------------------------------------------------------------------ codes and the sandbox dialog
    def code_reply(self, code: str, from_scan: bool = False) -> Reply:
        if not code.strip():
            return Reply("Look at the barcode and I'll tell you what it is.", _card("Look at the barcode"))
        lk = self.tools.lookup_code(code)
        cur = self.tools.ctx.task_id
        lines = lk["task_lines"]
        here = next((ln for ln in lines if ln["task_id"] == cur), None) if cur else None
        elsewhere = lines[0] if lines and not here else None
        kind = lk["kind"]
        if kind == "unknown":
            if from_scan and lk["site_mode"] == "sandbox":
                return self.unknown_code(code)
            return Reply(f"I don't know code {code} here.", _card("Unknown code", code))
        if kind == "material":
            m = lk["material"] or {}
            say = f"That's {m.get('description') or m.get('material')}."
            title = str(m.get("material") or code)
        elif kind == "bin":
            say, title = f"That's bin {lk['bin'] or code}.", f"Bin {lk['bin'] or code}"
        else:
            say, title = f"That's unit {code}.", f"Serial {code}"
        actions: list[dict[str, Any]] = []
        if here:
            say += f" It's line {here['line_no']} of this job."
            actions.append({"type": "refresh_task", "task_id": cur, "focus_code": code})
        elif elsewhere:
            say += f" It's in {elsewhere['task_title']}."
        return Reply(say, _card(title, kind), actions, task_id=cur)

    def unknown_code(self, code: str) -> Reply:
        code = code.strip()
        if not code:
            return Reply("I didn't get the code. Look at the barcode again.", _card("No code"))
        lk = self.tools.lookup_code(code)
        if lk["kind"] != "unknown":
            return self.code_reply(code)
        if lk["site_mode"] != "sandbox":
            return Reply(f"I don't know code {code}. New items can only be added on a sandbox site.",
                         _card("Unknown code", code))
        if not self.tools.can_add:
            return Reply("I don't know this code, and I can't add items in this build.", _card("Unknown code", code))
        t = self.tools.current_task()
        if t is None or t["type"] not in SANDBOX_TASK_TYPES:
            return Reply("I don't know this code. Open a receipt or a count first, then look at it again.",
                         _card("Unknown code", code))
        return Reply("I don't know this one. What is it?", _card("New item", code), [dict(LISTEN_FREE)],
                     dialog={"kind": "sandbox_item", "code": code, "task_id": t["id"], "step": "name"},
                     task_id=t["id"])

    def sandbox_dialog(self, text: str | None, dialog: dict[str, Any]) -> Reply:
        name_, _ = intent(text)
        task_id = str(dialog.get("task_id") or "") or None
        if name_ == "cancel":
            return Reply("OK, not added.", _card("Not added"), task_id=task_id)
        if dialog.get("step") in ("name", "model"):
            name = clean_name(text)
            if not name:
                return Reply("What is it?", _card("New item", str(dialog.get("code"))), [dict(LISTEN_FREE)],
                             dialog=dialog, task_id=task_id)
            return Reply(f"{name[:1].upper()}{name[1:]}. How many?", _card("New item", name), [dict(LISTEN_FREE)],
                         dialog={**dialog, "step": "qty", "name": name}, task_id=task_id)
        q = parse_quantity(text)
        if q is None:
            return Reply("How many? Say a number, like four, or say skip.", _card("How many?"), [dict(LISTEN_FREE)],
                         dialog=dialog, task_id=task_id)
        qty = None if q == SKIP else q
        assert qty is None or isinstance(qty, Decimal)
        r = self.tools.add_sandbox_item(str(dialog.get("code")), str(dialog.get("name") or ""), qty,
                                        answered_dialog=True)
        if not r.get("ok"):
            return Reply(f"I couldn't add it. {r.get('error')}", _card("Not added", str(r.get("error"))),
                         task_id=task_id)
        say = f"Added {r['description']}, {_qty_text(qty)}." if qty is not None else f"Added {r['description']}."
        return Reply(say, _card("Added", f"{r['description']} · {r['material']}"),
                     [{"type": "refresh_task", "task_id": r["task_id"], "focus_code": r["code"]}],
                     task_id=r["task_id"])
