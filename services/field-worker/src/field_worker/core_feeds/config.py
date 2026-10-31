"""Settings of the goods-receipt feeds (environment, names only; values in .env.local, A-02).

- FIELD_CORE_INVENTORY_FEED_URL, FIELD_CORE_INVENTORY_FEED_SECRET: the core's stock feed (webhook push, upsert).
- FIELD_CORE_SUPPLY_FEED_URL, FIELD_CORE_SUPPLY_FEED_SECRET: the core's open-supply feed (the PO line).
  Nothing is staged or sent unless both URLs are set; a URL without its secret is a configuration error (never
  sent unsigned).
- FIELD_CORE_FEED_MAX_ATTEMPTS (8): attempts before a delivery is dead-lettered (status dead).
- FIELD_CORE_FEED_BACKOFF_S (5) / FIELD_CORE_FEED_BACKOFF_MAX_S (600): exponential backoff with +-20 % jitter.
- FIELD_CORE_FEED_TIMEOUT_S (10): HTTP timeout per push.
- FIELD_CORE_FEED_LOOKBACK_H (24): goods receipts posted longer ago are not picked up (e.g. when the feeds are
  switched on later, history is not replayed).
- FIELD_CORE_FEED_SANDBOX (false): send receipts of sandbox (home / training) sites too.
- FIELD_CORE_CODE_MAP: optional JSON file mapping ERP codes to the core's codes (field_worker.core_feeds.codes).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class FeedConfig:
    inventory_url: str = ""
    inventory_secret: str = ""
    supply_url: str = ""
    supply_secret: str = ""
    max_attempts: int = 8
    backoff_s: float = 5.0
    backoff_max_s: float = 600.0
    timeout_s: float = 10.0
    lookback_h: float = 24.0
    include_sandbox: bool = False
    code_map_path: str = ""

    @classmethod
    def from_env(cls) -> FeedConfig:
        return cls(
            inventory_url=os.getenv("FIELD_CORE_INVENTORY_FEED_URL", "").strip(),
            inventory_secret=os.getenv("FIELD_CORE_INVENTORY_FEED_SECRET", "").strip(),
            supply_url=os.getenv("FIELD_CORE_SUPPLY_FEED_URL", "").strip(),
            supply_secret=os.getenv("FIELD_CORE_SUPPLY_FEED_SECRET", "").strip(),
            max_attempts=max(1, int(os.getenv("FIELD_CORE_FEED_MAX_ATTEMPTS") or "8")),
            backoff_s=float(os.getenv("FIELD_CORE_FEED_BACKOFF_S") or "5"),
            backoff_max_s=float(os.getenv("FIELD_CORE_FEED_BACKOFF_MAX_S") or "600"),
            timeout_s=float(os.getenv("FIELD_CORE_FEED_TIMEOUT_S") or "10"),
            lookback_h=float(os.getenv("FIELD_CORE_FEED_LOOKBACK_H") or "24"),
            include_sandbox=_flag("FIELD_CORE_FEED_SANDBOX"),
            code_map_path=os.getenv("FIELD_CORE_CODE_MAP", "").strip(),
        )

    @property
    def enabled(self) -> bool:
        """Both feed URLs set (M4 contract section 4: only then is anything delivered)."""
        return bool(self.inventory_url and self.supply_url)

    def problems(self) -> list[str]:
        """Variable names that are missing for an enabled configuration (never values)."""
        out: list[str] = []
        if self.inventory_url and not self.inventory_secret:
            out.append("FIELD_CORE_INVENTORY_FEED_SECRET")
        if self.supply_url and not self.supply_secret:
            out.append("FIELD_CORE_SUPPLY_FEED_SECRET")
        return out

    def target(self, feed: str) -> tuple[str, str]:
        """(url, secret) of a feed: 'inventory' or 'open_supply'."""
        return (self.inventory_url, self.inventory_secret) if feed == "inventory" else (
            self.supply_url, self.supply_secret)
