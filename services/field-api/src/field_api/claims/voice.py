"""The claims seam of the Field Assistant (M5 contract sections 3 and 4): what the rules call for "make a claim",
"claims" / "next claim", "approve" / "reject" and "confirm".

The assistant's rules classify these words themselves (no model call to understand them). The calls below are the
same service functions as the HTTP API, so the same rules hold: the look through the look port, lines by rules, one
claim per look, the supervisor's decision with a read-back, and the server-checked 10 s confirm by the same person,
with the claim's ETag (the assistant keeps the claim's version in its dialog). "Make a claim" drafts the text the
way POST /v1/claims does: one Muse call (purpose ``claim``) through the budget guard within CLAIM_MODEL_DEADLINE_S,
or the template.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from field_api.assistant.model import ModelRouter
from field_api.auth.jwt import Principal
from field_api.claims import service
from field_api.claims.looks import LookPort
from field_api.http.etag import generate_etag


@dataclass(frozen=True)
class ClaimsVoice:
    looks: LookPort
    router: ModelRouter

    def create(self, principal: Principal, look_id: str) -> dict[str, Any]:
        out, _created = service.create_claim(principal, look_id, looks=self.looks, router=self.router)
        return out

    def drafts(self, principal: Principal) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = service.list_claims(principal, "draft", 200)["items"]
        return items

    def decide(self, principal: Principal, claim_id: str, version: int, decision: str,
               reason: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
        return service.decide(principal, claim_id, decision, reason, generate_etag(claim_id, version))

    def confirm(self, principal: Principal, claim_id: str, version: int,
                words: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
        return service.confirm(principal, claim_id, generate_etag(claim_id, version), words)
