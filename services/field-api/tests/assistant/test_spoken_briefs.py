"""POST /v1/briefs/spoken (M4 contract §4, F3): Muse rewrites the core's template brief with its figures as markers,
field-api puts the figures back and runs the local checks (the number check and the core's own rule, ported), retries
once when they refuse, then asks the core's check; the template is spoken whenever anything refuses or fails.

Muse is the recorded-response double of the chat-completions API (conftest.RecordedAPI, test code only); the core is
an httpx MockTransport serving the stand-in core's check shape {accepted, reasons[], template_text} (core handover
01a). Neither the real Meta API for this prompt nor the real core's check has been called (META_FIELD rows 20, 21).
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from field_api.ai.budget import BudgetGuard
from field_api.app import app
from field_api.assistant.model import ModelRouter, get_router
from field_api.briefs import core_rule, markers, numbers
from field_api.briefs import service as brief_service
from field_api.briefs.core import CoreBriefCheck, get_core_check
from field_api.briefs.service import BRIEF_DEADLINE_S
from hypothesis import given, settings
from hypothesis import strategies as st

pytestmark = pytest.mark.unit
api = TestClient(app)
CORE_TOKEN = "core-wearable-" + "z" * 24  # not a credential: a marker the tests look for everywhere
DEVICE = "dev-glasses-01"
TEMPLATE = ("Rare-earth magnet export curbs hit the drone motor line. Option 1: expedite air freight, 42,000 USD, "
            "stock in 3 days. Option 2: qualify an alternate supplier, 6 weeks.")
REWRITE = ("Export curbs on rare-earth magnets now hit the drone motor line. Option 1 is to expedite air freight for "
           "42,000 USD, with stock in 3 days. Option 2 is to qualify an alternate supplier, which takes 6 weeks.")
MASKED = ("Rare-earth magnet export curbs hit the drone motor line. Option [F1]: expedite air freight, [F2] USD, "
          "stock in [F3] days. Option [F4]: qualify an alternate supplier, [F5] weeks.")
MARKED_REWRITE = ("Export curbs on rare-earth magnets now hit the drone motor line. Option [F1] is to expedite air freight "
                  "for [F2] USD, with stock in [F3] days. Option [F4] is to qualify an alternate supplier, which takes "
                  "[F5] weeks.")  # what Muse answers to MASKED; unmasked, it is REWRITE
# The core's spoken template for a magnet-export-curbs decision (core short.decision_spoken, the shared fixtures).
CORE_SPOKEN = ("A decision: Response to: Export licence checks on rare-earth magnets hold brushle\u2026. The recommended "
               "option is the alternate source. Its net cost against the plan is -$1,908.90. Approving commits "
               "$12,480.00. The fill rate would be 96.4 %. It is waiting for approval, with a deadline of 2026-11-14. "
               "It needs two approvers. Approving asks for your second factor.")


@dataclass
class Core:
    """The stand-in core's check route; each script item: a JSON body (200), an int status, or an exception."""

    script: list[Any] = field(default_factory=list)
    requests: list[httpx.Request] = field(default_factory=list)

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        item = self.script.pop(0) if self.script else {"accepted": True, "reasons": [], "template_text": TEMPLATE}
        if isinstance(item, type) and issubclass(item, Exception):
            raise item("scripted", request=req)
        if isinstance(item, int):
            return httpx.Response(item, json={"title": "scripted"})
        if isinstance(item, str):
            return httpx.Response(200, content=item.encode())
        return httpx.Response(200, json=item)


@pytest.fixture
def core() -> Core:
    return Core()


@pytest.fixture(autouse=True)
def wired(ai_on: None, make_router: Callable[..., ModelRouter], core: Core) -> Iterator[None]:
    router = make_router()
    app.dependency_overrides[get_router] = lambda: router
    app.dependency_overrides[get_core_check] = lambda: CoreBriefCheck("http://core.example.invalid",
                                                                      httpx.MockTransport(core.handler))
    yield
    app.dependency_overrides.pop(get_router, None)
    app.dependency_overrides.pop(get_core_check, None)


def brief(s: dict[str, Any], status: int = 200, *, token: str | None = CORE_TOKEN, device: str | None = DEVICE,
          decision_id: str = "DEC-RE-001", template: str = TEMPLATE, bearer: str | None = None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {bearer or s['op']}", "Idempotency-Key": str(uuid.uuid4())}
    if token is not None:
        headers["X-Core-Token"] = token
    if device is not None:
        headers["X-Device-Id"] = device
    r = api.post("/v1/briefs/spoken", json={"decision_id": decision_id, "template_text": template}, headers=headers)
    assert r.status_code == status, r.text
    out: dict[str, Any] = r.json()
    if status == 200:
        assert set(out) == {"text", "source", "reasons"}
    return out


def test_rewrite_accepted_by_the_core_is_spoken(site: dict[str, Any], recorded_api: Any, core: Core,
                                                h: SimpleNamespace) -> None:
    recorded_api.script = [h.answer(MARKED_REWRITE, prompt=400, cached=0, completion=300)]
    r = brief(site)
    assert r == {"text": REWRITE, "source": "model", "reasons": []}
    sent = recorded_api.requests[0]
    assert sent["model"] == "muse-spark-1.2" and "tools" not in sent and sent["reasoning_effort"] == "minimal"
    assert sent["messages"][1] == {"role": "user", "content": MASKED}  # the model never sees a figure
    assert markers.mask(TEMPLATE).text == MASKED
    assert "Keep every marker exactly once" in sent["messages"][0]["content"]
    assert len(recorded_api.requests) == 1
    assert len(core.requests) == 1
    req = core.requests[0]
    assert (req.method, req.url.path) == ("POST", "/v1/briefs/decision/DEC-RE-001/check")
    assert req.headers["authorization"] == f"Bearer {CORE_TOKEN}" and req.headers["x-device-id"] == DEVICE
    assert req.headers["x-requested-with"] == "lr"  # the core answers 403 without it (core reply TO_FIELD §1 item 6)
    assert json.loads(req.content) == {"text": REWRITE}
    assert CORE_TOKEN not in recorded_api.sent_text()  # the model never sees the core token
    with psycopg.connect(os.environ["FIELD_ADMIN_DATABASE_URL"]) as c, c.cursor() as cur:
        cur.execute("SELECT purpose, status, cost_usd FROM ops.ai_usage WHERE tenant_id = %s", (site["tenant"],))
        rows = cur.fetchall()
    assert len(rows) == 1 and rows[0][:2] == ("brief", "settled")
    assert Decimal(rows[0][2]) == (Decimal(400) * Decimal("1.25") + Decimal(300) * Decimal("4.25")) / 10**6


def test_core_refusal_speaks_the_cores_template(site: dict[str, Any], recorded_api: Any, core: Core,
                                                h: SimpleNamespace) -> None:
    recorded_api.script = [h.answer(REWRITE)]
    core.script = [{"accepted": False, "reasons": ["number_not_in_template:7"], "template_text": "CORE TEMPLATE 1."}]
    assert brief(site) == {"text": "CORE TEMPLATE 1.", "source": "template",
                           "reasons": ["core:number_not_in_template:7"]}
    core.script = [{"accepted": False, "reasons": [], "template_text": ""}]
    recorded_api.script = [h.answer(REWRITE)]
    assert brief(site) == {"text": TEMPLATE, "source": "template", "reasons": ["core:refused"]}


def test_a_model_that_writes_the_templates_figures_itself_is_still_spoken(site: dict[str, Any], recorded_api: Any,
                                                                          core: Core, h: SimpleNamespace) -> None:
    recorded_api.script = [h.answer(REWRITE)]
    assert brief(site) == {"text": REWRITE, "source": "model", "reasons": []}
    assert json.loads(core.requests[0].content) == {"text": REWRITE}


@pytest.mark.parametrize(("rewrite", "reasons"), [
    (REWRITE.replace("42,000", "45,000"), ["local:number_not_in_template:45000", "local:number_dropped:42000"]),
    (REWRITE.replace("6 weeks", "about six weeks or 7"), ["local:number_not_in_template:7"]),
    (REWRITE.replace(" with stock in 3 days.", "."), ["local:number_dropped:3"]),
    # the same number in words passed the old local check, and the core refuses it ("two" is not in the template)
    (REWRITE.replace("Option 2", "Option two"), ["local:Numbers written in words cannot be checked: two."]),
    (MARKED_REWRITE.replace("[F3]", "[F9]"), ["local:unknown_marker:F9"]),
])
def test_local_number_check_runs_before_the_core(site: dict[str, Any], recorded_api: Any, core: Core,
                                                        h: SimpleNamespace, rewrite: str, reasons: list[str]) -> None:
    recorded_api.script = [h.answer(rewrite), h.answer(rewrite)]
    r = brief(site)
    text = markers.unmask(rewrite, markers.mask(TEMPLATE))[0]
    first = ([x for x in reasons if x.startswith("local:unknown_marker:")] + numbers.check(text, TEMPLATE)
             + [f"local:{p}" for p in core_rule.refusals(text, TEMPLATE)])
    assert all(x in first for x in reasons), first
    assert r == {"text": TEMPLATE, "source": "template", "reasons": [*first, *(f"retry:{x}" for x in first)]}
    assert core.requests == []  # a local refusal never costs a core call
    assert len(recorded_api.requests) == 2
    again = recorded_api.requests[1]["messages"]
    assert again[:2] == recorded_api.requests[0]["messages"]
    assert again[2] == {"role": "assistant", "content": rewrite}
    assert again[3]["role"] == "user" and "[F1], [F2], [F3], [F4], [F5] exactly once each, in this order" in \
        again[3]["content"]


def test_the_hosted_refusal_is_refused_locally_and_the_retry_is_spoken(site: dict[str, Any], recorded_api: Any,
                                                                       core: Core, h: SimpleNamespace) -> None:
    """Hosted release scm-1a36ab0-569772d (2 Nov): the core refused Muse's brief for the magnet-export-curbs decision
    ("The figures are not the template's figures in the template's order with their signs"). A rewrite that drops
    the cents of the committed amount passes the old value check but not the core's rule; field-api now refuses it
    itself, asks once more with markers, and speaks the second answer, with the template's figures, after the core
    accepts it."""
    first = CORE_SPOKEN.replace("$12,480.00", "$12,480")
    assert numbers.check(first, CORE_SPOKEN) == []  # what let it through before
    masked = markers.mask(CORE_SPOKEN)
    second = ("A decision on export licence checks that hold rare-earth magnet and brushless motor shipments. The "
              "recommended option is the alternate source, with a net cost against the plan of [F1]. Approving "
              "commits [F2], and the fill rate would be [F3]. It is waiting for approval, with a deadline of [F4], "
              "needs two approvers, and approving asks for your second factor.")
    recorded_api.script = [h.answer(first), h.answer(second)]
    core.script = [{"accepted": True, "reasons": [], "template_text": CORE_SPOKEN}]
    r = brief(site, template=CORE_SPOKEN)
    spoken = markers.unmask(second, masked)[0]
    assert r == {"text": spoken, "source": "model", "reasons": []}
    assert "-$1,908.90. Approving commits $12,480.00, and the fill rate would be 96.4 %." in spoken
    assert core_rule.refusals(spoken, CORE_SPOKEN) == []
    assert json.loads(core.requests[0].content) == {"text": spoken} and len(core.requests) == 1
    assert [q["reasoning_effort"] for q in recorded_api.requests] == ["minimal", "minimal"]
    assert recorded_api.requests[0]["messages"][1]["content"] == masked.text
    assert "$" not in json.dumps(recorded_api.requests[0])  # the model never sees the template's figures


def test_no_retry_when_too_little_of_the_deadline_is_left(site: dict[str, Any], recorded_api: Any, core: Core,
                                                          h: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(brief_service, "RETRY_MIN_S", 60.0)
    recorded_api.script = [h.answer(CORE_SPOKEN.replace("-$1,908.90", "$1,908.90"))]
    r = brief(site, template=CORE_SPOKEN)
    assert r == {"text": CORE_SPOKEN, "source": "template",
                 "reasons": [f"local:{core_rule.ORDER_PROBLEM}", "retry:no_time"]}
    assert len(recorded_api.requests) == 1 and core.requests == []


def test_a_failed_retry_speaks_the_template_with_both_reasons(site: dict[str, Any], recorded_api: Any, core: Core,
                                                              h: SimpleNamespace) -> None:
    recorded_api.script = [h.answer(MARKED_REWRITE.replace("[F2] USD", "45,000 USD")), 500]
    r = brief(site)
    assert r["source"] == "template" and r["text"] == TEMPLATE
    assert r["reasons"][:2] == ["local:number_not_in_template:45000", "local:number_dropped:42000"]
    assert r["reasons"][-1] == "retry:model:meta:AI_HTTP_500" and core.requests == []


@pytest.mark.parametrize(("item", "reason"), [
    (401, "core:http_401"), (404, "core:http_404"), (503, "core:http_503"), (httpx.ReadTimeout, "core:timeout"),
    (httpx.ConnectError, "core:transport"), ("not json", "core:bad_response"), ({"ok": True}, "core:bad_response"),
])
def test_core_errors_speak_the_template(site: dict[str, Any], recorded_api: Any, core: Core, h: SimpleNamespace,
                                        item: Any, reason: str) -> None:
    recorded_api.script = [h.answer(REWRITE)]
    core.script = [item]
    assert brief(site) == {"text": TEMPLATE, "source": "template", "reasons": [reason]}


def test_model_off_or_over_budget_speaks_the_template_without_calls(site: dict[str, Any], recorded_api: Any,
                                                                   core: Core, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_CLOUD_ENABLED", "false")
    assert brief(site) == {"text": TEMPLATE, "source": "template", "reasons": ["model:meta:AI_CLOUD_DISABLED"]}
    monkeypatch.setenv("AI_CLOUD_ENABLED", "true")
    spent = Decimal(BudgetGuard(prices={}).usage()["providers"]["meta"]["spent_usd"])
    monkeypatch.setenv("AI_BUDGET_META_USD", str(spent))
    assert brief(site)["reasons"] == ["model:meta:AI_BUDGET_EXHAUSTED"]
    monkeypatch.delenv("MODEL_API_KEY")
    assert brief(site)["reasons"] == ["model:meta:AI_NO_KEY"]
    app.dependency_overrides[get_router] = lambda: ModelRouter([])  # e.g. a refused (image) model id
    assert brief(site)["reasons"] == ["model:no_model_configured"]
    assert recorded_api.requests == [] and core.requests == []


@pytest.mark.parametrize(("item", "reason"), [
    (httpx.ReadTimeout, "model:meta:AI_TIMEOUT"), (500, "model:meta:AI_HTTP_500"),
    ({"choices": [{"finish_reason": "length", "message": {"content": None, "role": "assistant"}}],
      "usage": {"prompt_tokens": 300, "completion_tokens": 1024}}, "model:meta:AI_TRUNCATED"),
    ("EMPTY", "model:empty_answer"), ("LONG", "local:too_long"),
])
def test_model_failures_speak_the_template(site: dict[str, Any], recorded_api: Any, core: Core, h: SimpleNamespace,
                                           item: Any, reason: str) -> None:
    recorded_api.script = [h.answer("  ") if item == "EMPTY" else h.answer("word " * 200) if item == "LONG" else item]
    assert brief(site) == {"text": TEMPLATE, "source": "template", "reasons": [reason]}
    assert core.requests == []


def test_model_gets_the_four_second_deadline(site: dict[str, Any], h: SimpleNamespace, core: Core) -> None:
    seen: list[float] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.extend(v for v in req.extensions["timeout"].values() if v is not None)
        raise httpx.ReadTimeout("slow", request=req)

    from field_api.assistant.model import ChatModel, ProviderConfig

    guard = BudgetGuard(prices={"llama": {}, "baseten": {}, "meta": {"muse-spark-1.2": h.META_PRICE}})
    router = ModelRouter([ChatModel(ProviderConfig("meta", "https://api.meta.ai/v1", "muse-spark-1.2",
                                                   "MODEL_API_KEY"), guard, httpx.MockTransport(handler))])
    app.dependency_overrides[get_router] = lambda: router
    assert brief(site)["reasons"] == ["model:meta:AI_TIMEOUT"]
    assert BRIEF_DEADLINE_S == 4.0 and seen and BRIEF_DEADLINE_S - 0.5 < max(seen) <= BRIEF_DEADLINE_S


@pytest.mark.parametrize(("token", "device", "reasons"), [
    (None, DEVICE, ["missing:x_core_token"]), (CORE_TOKEN, None, ["missing:x_device_id"]),
    ("  ", "", ["missing:x_core_token", "missing:x_device_id"]),
])
def test_missing_headers_speak_the_template_without_any_call(site: dict[str, Any], recorded_api: Any, core: Core,
                                                             token: str | None, device: str | None,
                                                             reasons: list[str]) -> None:
    assert brief(site, token=token, device=device) == {"text": TEMPLATE, "source": "template", "reasons": reasons}
    assert recorded_api.requests == [] and core.requests == []


def test_core_token_is_never_stored_or_logged(site: dict[str, Any], recorded_api: Any, core: Core,
                                              h: SimpleNamespace, capfd: pytest.CaptureFixture[str]) -> None:
    recorded_api.script = [h.answer(REWRITE), 500]
    core.script = [401]
    brief(site)
    brief(site)
    out, err = capfd.readouterr()
    assert CORE_TOKEN not in out + err and "brief_spoken" in out + err
    with psycopg.connect(os.environ["FIELD_ADMIN_DATABASE_URL"]) as c, c.cursor() as cur:
        cur.execute("SELECT coalesce(string_agg(row_to_json(r)::text, ''), '') FROM ops.ai_usage r"
                    " WHERE tenant_id = %s", (site["tenant"],))
        usage = (cur.fetchone() or ("",))[0]
        cur.execute("SELECT coalesce(string_agg(convert_from(coalesce(body, ''), 'UTF8') || headers::text"
                    " || fingerprint, ''), '') FROM field.idempotency_record WHERE tenant_id = %s", (site["tenant"],))
        stored = (cur.fetchone() or ("",))[0]
    assert stored and CORE_TOKEN not in usage + stored


def test_permission_validation_and_idempotency(site: dict[str, Any], recorded_api: Any) -> None:
    for role in ("op", "tech", "sup"):
        assert brief(site, bearer=site[role], token=None)["source"] == "template"
    brief(site, 403, bearer=site["viewer"])
    assert api.post("/v1/briefs/spoken", json={"decision_id": "D1", "template_text": "x"}).status_code == 401
    for bad in ("../etc", "", "x" * 129):
        brief(site, 422, decision_id=bad)
    brief(site, 422, template="")
    r = api.post("/v1/briefs/spoken", json={"decision_id": "D1", "template_text": "x"},
                 headers={"Authorization": f"Bearer {site['op']}", "X-Test-Omit-Idempotency-Key": "1"})
    assert r.status_code == 400 and r.json()["code"] == "FIELD-IDEM-400-MISSING-KEY"


def test_decision_id_is_path_quoted(site: dict[str, Any], recorded_api: Any, core: Core, h: SimpleNamespace) -> None:
    recorded_api.script = [h.answer(REWRITE)]
    brief(site, decision_id="tenant:DEC.42")
    assert core.requests[0].url.raw_path == b"/v1/briefs/decision/tenant%3ADEC.42/check"


# ---------------------------------------------------------------- the local number check (pure)
def test_number_values_in_digits_and_words() -> None:
    v = numbers.values("1,200 USD, 12.5%, twenty five units, one hundred and two days, two and three, the one we "
                       "use, 1,20,000 INR, 03 Nov, two lakh")
    want = {"1200", "12.5", "25", "102", "2", "3", "120000", "200000"}
    assert {f"{x:f}" for x in v} == want
    assert numbers.check("Option two costs 1,200.", "Option 2 costs 1200.") == []


@settings(max_examples=200, deadline=None)
@given(st.lists(st.integers(0, 10**7), min_size=1, max_size=6, unique=True), st.integers(0, 10**7))
def test_a_rewrite_with_a_new_number_is_always_refused(template_nums: list[int], extra: int) -> None:
    template = "Brief: " + ", ".join(f"item {n}" for n in template_nums) + "."
    assert numbers.check(template, template) == []
    rewrite = template + f" Also {extra}."
    reasons = numbers.check(rewrite, template)
    assert (reasons == []) == (extra in template_nums)
