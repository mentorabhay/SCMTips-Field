"""AI budget guard (owner amendment A-02; docs/SETUP/FIELD_TEST_GUIDE.md).

Before any paid call, ``reserve()`` records a reservation for the worst-case cost of that call
(prompt tokens + max output tokens at the configured price). It refuses when:
- AI_CLOUD_ENABLED is not "true";
- the model has no price in config/ai_pricing.yaml (the guard never guesses a price);
- the provider's lifetime spend + open reservations + this call would exceed its cap
  (AI_BUDGET_LLAMA_USD / AI_BUDGET_BASETEN_USD), or today's (UTC) spend across providers would
  exceed AI_DAILY_CAP_USD.
After the call, ``settle()`` replaces the reservation by the actual cost (or ``fail()`` by the cost
the provider still billed, default 0). Reservations that are never settled keep counting.

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

PROVIDERS = ("llama", "baseten")
CAP_ENV: Mapping[str, str] = MappingProxyType({"llama": "AI_BUDGET_LLAMA_USD", "baseten": "AI_BUDGET_BASETEN_USD"})
DAILY_ENV = "AI_DAILY_CAP_USD"
LOCK_KEY = 0x41494255  # "AIBU": one global lock for budget decisions
PRICING_FILE = Path(os.getenv("FIELD_AI_PRICING_FILE", Path(__file__).resolve().parents[5] / "config" / "ai_pricing.yaml"))


class BudgetRefused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Price:
    input_per_mtok: Decimal
    output_per_mtok: Decimal

    def cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        return (self.input_per_mtok * input_tokens + self.output_per_mtok * output_tokens) / Decimal(1_000_000)


@dataclass(frozen=True)
class Reservation:
    id: str
    provider: str
    model: str
    reserved_usd: Decimal
    price: Price


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
        out[provider] = {
            str(m): Price(Decimal(str(p["input_per_mtok"])), Decimal(str(p["output_per_mtok"]))) for m, p in models.items()
        }
    return out


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
        tenant_id: str | None = None, request_id: str | None = None,
    ) -> Reservation:
        if os.getenv("AI_CLOUD_ENABLED", "false").strip().lower() != "true":
            raise BudgetRefused("AI_CLOUD_DISABLED", "AI_CLOUD_ENABLED is not true")
        if provider not in PROVIDERS:
            raise BudgetRefused("AI_PROVIDER_UNKNOWN", f"unknown provider {provider!r}")
        if input_tokens < 0 or max_output_tokens <= 0:
            raise BudgetRefused("AI_REQUEST_INVALID", "token counts must be positive")
        price = self._price(provider, model)
        est = price.cost(input_tokens, max_output_tokens)
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
        return Reservation(str(row[0]), provider, model, est, price)

    def settle(self, r: Reservation, *, input_tokens: int, output_tokens: int) -> Decimal:
        cost = r.price.cost(input_tokens, output_tokens)
        self._close(r, "settled", cost, input_tokens, output_tokens)
        return cost

    def fail(self, r: Reservation, *, billed_usd: Decimal = Decimal(0)) -> None:
        self._close(r, "failed", billed_usd, None, None)

    def _close(self, r: Reservation, status: str, cost: Decimal, tin: int | None, tout: int | None) -> None:
        with get_conn(self._db_url) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE ops.ai_usage SET status = %s, cost_usd = %s, input_tokens = %s, output_tokens = %s,"
                " settled_at = NOW() WHERE id = %s AND status = 'reserved'",
                (status, cost, tin, tout, r.id),
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
