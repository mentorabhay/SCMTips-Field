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
- FIELD_CORE_SNAPSHOT_INTERVAL_S (900): every so often, the ERP's stock and open purchase orders of the production
  sites' plants are sent to the same two feeds (field_worker.core_feeds.snapshot, M4 Q10); 0 switches it off. Off as
  well whenever the feeds are off (both URLs needed).
- FIELD_CORE_SNAPSHOT_BATCH (200): rows per push (one delivery row each), 1..1000.
- FIELD_CORE_SNAPSHOT_RESEND_H (24): a row the core already has (same values sent within this many hours) is not sent
  again; after that it is, so a core that lost or replaced it catches up.
- FIELD_CORE_SNAPSHOT_TENANTS (empty = every tenant): comma-separated Field tenant ids whose plants the snapshot reads.
  The two feeds belong to one core organisation; with FIELD_CORE_TARGET=core name its tenant here, so another tenant
  of this installation (the stack's demo tenant) never reaches it. Empty: FIELD_CORE_FEED_TENANTS (below).
- FIELD_CORE_FEED_TENANTS (empty = FIELD_CORE_SNAPSHOT_TENANTS; both empty = every tenant): comma-separated Field
  tenant ids whose goods receipts are sent (M4-C18, the K5 finding). The feeds belong to one core organisation, so
  with FIELD_CORE_TARGET=core one of the two must name it: otherwise nothing is sent and the worker logs the name.
- FIELD_CORE_TARGET: read only for that check (core = the real SCMTIPS core).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _ids(name: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in os.getenv(name, "").split(",") if x.strip())


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
    snapshot_interval_s: float = 900.0
    snapshot_batch: int = 200
    snapshot_resend_h: float = 24.0
    snapshot_tenants: tuple[str, ...] = ()
    feed_tenants: tuple[str, ...] = ()
    core_target: str = ""

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
            snapshot_interval_s=max(0.0, float(os.getenv("FIELD_CORE_SNAPSHOT_INTERVAL_S") or "900")),
            snapshot_batch=min(1000, max(1, int(os.getenv("FIELD_CORE_SNAPSHOT_BATCH") or "200"))),
            snapshot_resend_h=max(0.0, float(os.getenv("FIELD_CORE_SNAPSHOT_RESEND_H") or "24")),
            snapshot_tenants=_ids("FIELD_CORE_SNAPSHOT_TENANTS"),
            feed_tenants=_ids("FIELD_CORE_FEED_TENANTS"),
            core_target=os.getenv("FIELD_CORE_TARGET", "").strip().lower(),
        )

    @property
    def receipt_tenants(self) -> tuple[str, ...]:
        """Tenants whose goods receipts go to the feeds: FIELD_CORE_FEED_TENANTS, else the snapshot's; () = all."""
        return self.feed_tenants or self.snapshot_tenants

    @property
    def enabled(self) -> bool:
        """Both feed URLs set (M4 contract section 4: only then is anything delivered)."""
        return bool(self.inventory_url and self.supply_url)

    @property
    def snapshot_enabled(self) -> bool:
        """The stock and open-PO snapshot runs only with the feeds on and a non-zero interval (M4 Q10)."""
        return self.enabled and self.snapshot_interval_s > 0

    def problems(self) -> list[str]:
        """Variable names that are missing for an enabled configuration (never values)."""
        out: list[str] = []
        if self.enabled and self.core_target == "core" and not self.receipt_tenants:
            out.append("FIELD_CORE_FEED_TENANTS")  # the real core: never every tenant of this installation
        if self.inventory_url and not self.inventory_secret:
            out.append("FIELD_CORE_INVENTORY_FEED_SECRET")
        if self.supply_url and not self.supply_secret:
            out.append("FIELD_CORE_SUPPLY_FEED_SECRET")
        return out

    def target(self, feed: str) -> tuple[str, str]:
        """(url, secret) of a feed: 'inventory' or 'open_supply'."""
        return (self.inventory_url, self.inventory_secret) if feed == "inventory" else (
            self.supply_url, self.supply_secret)
