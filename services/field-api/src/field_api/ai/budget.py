"""AI budget guard (owner amendment A-02; docs/SETUP/FIELD_TEST_GUIDE.md).

Before any paid call, ``reserve()`` records a reservation for the worst-case cost of that call
(prompt tokens + max output tokens at the configured price). It refuses when:
- AI_CLOUD_ENABLED is not "true";
- the model has no price in config/ai_pricing.yaml (the guard never guesses a price);
- the provider's lifetime spend + open reservations + this call would exceed its cap
  (AI_BUDGET_LLAMA_USD / AI_BUDGET_BASETEN_USD / AI_BUDGET_META_USD), or today's (UTC) spend across
  providers would exceed AI_DAILY_CAP_USD.
- the model id contains "image" (Muse Image is prohibited in India, owner amendment A-04): refused even when
  someone has given it a price.
After the call, ``settle()`` replaces the reservation by the actual cost (or ``fail()`` by the cost
the provider still billed, default 0). Reservations that are never settled keep counting.

Providers: ``llama`` (the retired Llama API spike), ``baseten`` (fallback), ``meta`` (Meta Model API,
the M3 Field Assistant). A price may carry ``cached_input_per_mtok``: prompt tokens the provider reports
as served from its prompt cache (usage.prompt_tokens_details.cached_tokens) are billed at that rate; a
model without it bills cached tokens at the normal input rate. The reservation always assumes no cache
hit (worst case).

Unconfirmed prices (M5, owner amendment A-06): a price entry may say ``confirmed: false`` (a placeholder the owner
has not checked on the provider's console), and a token-priced model may carry ``image_input: {confirmed: false,
tokens_per_image: N}`` (how many prompt tokens one input image costs is not published). ``reserve`` refuses such a
model (AI_PRICE_UNCONFIRMED), and a call with ``images > 0`` to a model whose image input is unconfirmed, unless
AI_ALLOW_UNCONFIRMED_PRICES=true (default false). Entries without the keys are confirmed, so every earlier caller
(text calls, and the assistant's photo turn, which does not pass ``images``) behaves exactly as before. A model can
also be priced per image (``per_image_usd``, SAM 3.1 is billed per image): reservation and settlement add
images x per_image_usd. With ``images`` the reservation counts ``tokens_per_image`` prompt tokens per image (worst
case); settlement uses the provider's own prompt-token count, which includes the images.

All checks and the insert run under one transaction-level advisory lock, so concurrent callers
cannot overspend. Caps are read per call: lowering a cap in .env.local takes effect on restart.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

import psycopg
import yaml

from field_api.db import get_conn

PROVIDERS = ("llama", "baseten", "meta")
CAP_ENV: Mapping[str, str] = MappingProxyType(
    {"llama": "AI_BUDGET_LLAMA_USD", "baseten": "AI_BUDGET_BASETEN_USD", "meta": "AI_BUDGET_META_USD"}
)
DAILY_ENV = "AI_DAILY_CAP_USD"
LOCK_KEY = 0x41494255  # "AIBU": one global lock for budget decisions
PROHIBITED_MODEL_WORDS = ("image",)  # A-04: Muse Image is never called
ALLOW_UNCONFIRMED_ENV = "AI_ALLOW_UNCONFIRMED_PRICES"
DEFAULT_TOKENS_PER_IMAGE = 3000  # reservation per input image when the price entry gives no estimate
PRICING_FILE = Path(os.getenv("FIELD_AI_PRICING_FILE", Path(__file__).resolve().parents[5] / "config" / "ai_pricing.yaml"))


class BudgetRefused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Price:
    input_per_mtok: Decimal
    output_per_mtok: Decimal
    cached_input_per_mtok: Decimal | None = None
    per_image_usd: Decimal = Decimal(0)
    confirmed: bool = True
    image_input_confirmed: bool = True
    tokens_per_image: int = DEFAULT_TOKENS_PER_IMAGE

    def cost(self, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0, images: int = 0) -> Decimal:
        """USD for one call. ``input_tokens`` is the provider's prompt_tokens (cached ones included);
        ``cached_input_tokens`` of them are billed at the cached rate when the model has one; ``images`` adds
        images x per_image_usd (a per-image model)."""
        if not 0 <= cached_input_tokens <= max(input_tokens, 0):
            raise ValueError("cached_input_tokens must be between 0 and input_tokens")
        if images < 0:
            raise ValueError("images must be >= 0")
        cached_rate = self.input_per_mtok if self.cached_input_per_mtok is None else self.cached_input_per_mtok
        fresh = input_tokens - cached_input_tokens
        return ((self.input_per_mtok * fresh + cached_rate * cached_input_tokens
                 + self.output_per_mtok * output_tokens) / Decimal(1_000_000) + self.per_image_usd * images)


@dataclass(frozen=True)
class Reservation:
    id: str
    provider: str
    model: str
    reserved_usd: Decimal
    price: Price
    images: int = 0


def _cap(name: str) -> Decimal:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        raise BudgetRefused("AI_CAP_UNSET", f"{name} is not set; no paid call without a cap")
    val = Decimal(raw)
    if val < 0:
        raise BudgetRefused("AI_CAP_INVALID", f"{name} must be >= 0")
    return val


def load_prices(path: Path = PRICING_FILE) -> dict[str, dict[str, Price]]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, dict[str, Price]] = {}
    for provider in PROVIDERS:
        models = data.get(provider) or {}
        out[provider] = {str(m): _price_from(p) for m, p in models.items()}
    return out


def _flag(v: Any, name: str) -> bool:
    if v is None:
        return True
    if not isinstance(v, bool):
        raise ValueError(f"{name} must be true or false")
    return v


def _price_from(p: Mapping[str, Any]) -> Price:
    cached = p.get("cached_input_per_mtok")
    image_input = p.get("image_input") or {}
    if not isinstance(image_input, Mapping):
        raise ValueError("image_input must be a mapping")
    tokens_per_image = int(image_input.get("tokens_per_image", DEFAULT_TOKENS_PER_IMAGE))
    price = Price(Decimal(str(p["input_per_mtok"])), Decimal(str(p["output_per_mtok"])),
                  None if cached is None else Decimal(str(cached)),
                  per_image_usd=Decimal(str(p.get("per_image_usd", 0))),
                  confirmed=_flag(p.get("confirmed"), "confirmed"),
                  image_input_confirmed=_flag(image_input.get("confirmed"), "image_input.confirmed"),
                  tokens_per_image=tokens_per_image)
    if (price.input_per_mtok < 0 or price.output_per_mtok < 0 or (cached is not None and Decimal(str(cached)) < 0)
            or price.per_image_usd < 0 or tokens_per_image < 0):
        raise ValueError("prices must be >= 0")
    return price


def unconfirmed_allowed() -> bool:
    """AI_ALLOW_UNCONFIRMED_PRICES=true lets the guard use placeholder prices (default false: refused)."""
    return os.getenv(ALLOW_UNCONFIRMED_ENV, "false").strip().lower() == "true"


class BudgetGuard:
    def __init__(self, db_url: str | None = None, prices: dict[str, dict[str, Price]] | None = None) -> None:
        self._db_url = db_url
        self._prices = prices

    def _price(self, provider: str, model: str) -> Price:
        prices = self._prices if self._prices is not None else load_prices()
        p = prices.get(provider, {}).get(model)
        if p is None:
            raise BudgetRefused("AI_PRICE_UNKNOWN", f"no price for {provider}/{model} in config/ai_pricing.yaml")
        return p

    @staticmethod
    def _spent(cur: psycopg.Cursor[Any], provider: str | None, today_only: bool) -> Decimal:
        sql = "SELECT COALESCE(SUM(COALESCE(cost_usd, reserved_usd)), 0) FROM ops.ai_usage WHERE status <> 'failed'"
        args: list[Any] = []
        if provider:
            sql += " AND provider = %s"
            args.append(provider)
        if today_only:
            sql += " AND created_at >= date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"
        cur.execute(sql, args)
        row = cur.fetchone()
        failed_sql = "SELECT COALESCE(SUM(cost_usd), 0) FROM ops.ai_usage WHERE status = 'failed'"
        if provider:
            failed_sql += " AND provider = %s"
        if today_only:
            failed_sql += " AND created_at >= date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"
        cur.execute(failed_sql, args)
        frow = cur.fetchone()
        return Decimal(row[0] if row else 0) + Decimal(frow[0] if frow else 0)

    def reserve(
        self, provider: str, model: str, *, input_tokens: int, max_output_tokens: int, purpose: str,
        tenant_id: str | None = None, request_id: str | None = None, images: int = 0,
    ) -> Reservation:
        if os.getenv("AI_CLOUD_ENABLED", "false").strip().lower() != "true":
            raise BudgetRefused("AI_CLOUD_DISABLED", "AI_CLOUD_ENABLED is not true")
        if provider not in PROVIDERS:
            raise BudgetRefused("AI_PROVIDER_UNKNOWN", f"unknown provider {provider!r}")
        if input_tokens < 0 or max_output_tokens <= 0 or images < 0:
            raise BudgetRefused("AI_REQUEST_INVALID", "token counts must be positive")
        if any(w in model.lower() for w in PROHIBITED_MODEL_WORDS):
            raise BudgetRefused("AI_MODEL_PROHIBITED", f"{model!r}: image models are prohibited (A-04)")
        price = self._price(provider, model)
        if not unconfirmed_allowed():
            if not price.confirmed:
                raise BudgetRefused("AI_PRICE_UNCONFIRMED", f"the price of {provider}/{model} in config/ai_pricing.yaml"
                                    f" is a placeholder (confirmed: false); set {ALLOW_UNCONFIRMED_ENV}=true to use it")
            if images > 0 and not price.image_input_confirmed:
                raise BudgetRefused("AI_PRICE_UNCONFIRMED", f"image input of {provider}/{model} is not confirmed in"
                                    f" config/ai_pricing.yaml; set {ALLOW_UNCONFIRMED_ENV}=true to use it")
        # A per-image model (SAM 3.1) bills the image itself; a token model bills the image as prompt tokens.
        image_tokens = 0 if price.per_image_usd > 0 else images * price.tokens_per_image
        est = price.cost(input_tokens + image_tokens, max_output_tokens, images=images)
        cap, daily = _cap(CAP_ENV[provider]), _cap(DAILY_ENV)
        with get_conn(self._db_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
            total, today = self._spent(cur, provider, False), self._spent(cur, None, True)
            if total + est > cap:
                raise BudgetRefused("AI_BUDGET_EXHAUSTED", f"{provider}: ${total:.4f} of ${cap} used; call needs ${est:.4f}")
            if today + est > daily:
                raise BudgetRefused("AI_DAILY_CAP", f"today ${today:.4f} of ${daily}; call needs ${est:.4f}")
            cur.execute(
                "INSERT INTO ops.ai_usage (provider, model, purpose, status, reserved_usd, tenant_id, request_id)"
                " VALUES (%s, %s, %s, 'reserved', %s, %s, %s) RETURNING id",
                (provider, model, purpose, est, tenant_id, request_id),
            )
            row = cur.fetchone()
            conn.commit()
        assert row is not None
        return Reservation(str(row[0]), provider, model, est, price, images)

    def settle(self, r: Reservation, *, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0) -> Decimal:
        cost = r.price.cost(input_tokens, output_tokens, cached_input_tokens, images=r.images)
        self._close(r, "settled", cost, input_tokens, output_tokens, cached_input_tokens)
        return cost

    def fail(self, r: Reservation, *, billed_usd: Decimal = Decimal(0)) -> None:
        self._close(r, "failed", billed_usd, None, None, None)

    def _close(self, r: Reservation, status: str, cost: Decimal, tin: int | None, tout: int | None,
               tcached: int | None) -> None:
        with get_conn(self._db_url) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE ops.ai_usage SET status = %s, cost_usd = %s, input_tokens = %s, output_tokens = %s,"
                " cached_input_tokens = %s, settled_at = NOW() WHERE id = %s AND status = 'reserved'",
                (status, cost, tin, tout, tcached, r.id),
            )
            if cur.rowcount != 1:
                raise RuntimeError(f"reservation {r.id} is not open")
            conn.commit()

    def usage(self) -> dict[str, Any]:
        with get_conn(self._db_url) as conn, conn.cursor() as cur:
            out: dict[str, Any] = {"providers": {}, "today_usd": str(self._spent(cur, None, True))}
            for p in PROVIDERS:
                cap = os.getenv(CAP_ENV[p])
                out["providers"][p] = {"spent_usd": str(self._spent(cur, p, False)), "cap_usd": cap}
            out["daily_cap_usd"] = os.getenv(DAILY_ENV)
            out["cloud_enabled"] = os.getenv("AI_CLOUD_ENABLED", "false").strip().lower() == "true"
        return out
