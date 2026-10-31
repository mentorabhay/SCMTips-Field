"""The core's brief number check: ``POST {FIELD_CORE_BASE_URL}/v1/briefs/decision/{id}/check {"text": ...}`` with
``Authorization: Bearer <the app's core wearable token>`` and ``X-Device-Id`` -> ``{accepted, reasons[],
template_text}`` (core handover 01a). The token is forwarded for this one call and never stored or logged; no
error or reason carries it.

UNVERIFIED against the real core (docs/META_FIELD.md row 21): the route is being added there; CI checks this
client against the stand-in core's shape with an httpx test transport that lives in test code only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

CORE_ENV = "FIELD_CORE_BASE_URL"
CORE_DEFAULT = "http://127.0.0.1:8001"  # the stand-in core of the dev stack (M4 contract §2)
CHECK_TIMEOUT_S = 2.5


@dataclass(frozen=True)
class CheckResult:
    accepted: bool
    reasons: list[str]
    template_text: str | None


class CoreBriefCheck:
    """``transport`` is for tests (an httpx transport double); production uses the network."""

    def __init__(self, base_url: str | None = None, transport: httpx.BaseTransport | None = None,
                 timeout_s: float = CHECK_TIMEOUT_S) -> None:
        self.base_url = (base_url or os.getenv(CORE_ENV, "").strip() or CORE_DEFAULT).rstrip("/")
        self._transport = transport
        self.timeout_s = timeout_s

    def check(self, decision_id: str, text: str, *, core_token: str, device_id: str) -> CheckResult:
        """The core's verdict. A failure to get one is a refusal with a reason (core:timeout, core:http_401, ...)."""
        path = f"/v1/briefs/decision/{quote(decision_id, safe='')}/check"
        headers = {"Authorization": f"Bearer {core_token}", "X-Device-Id": device_id}
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout_s, transport=self._transport) as client:
                r = client.post(path, json={"text": text}, headers=headers)
        except httpx.TimeoutException:
            return CheckResult(False, ["core:timeout"], None)
        except httpx.HTTPError:
            return CheckResult(False, ["core:transport"], None)
        if not r.is_success:
            return CheckResult(False, [f"core:http_{r.status_code}"], None)
        try:
            body: Any = r.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or not isinstance(body.get("accepted"), bool):
            return CheckResult(False, ["core:bad_response"], None)
        raw = body.get("reasons")
        reasons = [f"core:{str(x)[:120]}" for x in raw[:10]] if isinstance(raw, list) else []
        tpl = body.get("template_text")
        template = tpl if isinstance(tpl, str) and tpl.strip() else None
        if body["accepted"] is not True and not reasons:
            reasons = ["core:refused"]
        return CheckResult(body["accepted"] is True, [] if body["accepted"] is True else reasons, template)


def get_core_check() -> CoreBriefCheck:
    """FastAPI dependency (tests override it with a client over an httpx test transport)."""
    return CoreBriefCheck()
