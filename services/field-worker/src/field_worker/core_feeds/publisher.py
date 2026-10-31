"""Outbox -> core feeds: stage, sign, deliver, retry, dead-letter (M4 F4; handover 01a).

Every worker tick (field_worker.worker.FieldWorker.tick), when both feed URLs are set:

1. Stage. Each ``erp.posted`` outbox event of a goods receipt (doc_type GoodsReceipt, movement 101) posted within
   FIELD_CORE_FEED_LOOKBACK_H and not staged yet becomes two field.core_feed_delivery rows, one per feed, with the
   exact JSON body to send. The rows are read from the ERP through ErpReadPort (the posted document and the
   on-hand after it), never computed. UNIQUE (tenant, event_id, feed) makes this idempotent on the event id: a
   second worker, a restart or a replay never makes a second delivery. Sandbox receipts are skipped unless
   FIELD_CORE_FEED_SANDBOX is on; a receipt without a PO reference skips the open-supply push.
2. Deliver. Due rows are leased, POSTed with X-SCMTIPS-Timestamp / X-SCMTIPS-Signature (fresh timestamp each try,
   same body) and Idempotency-Key ``<event_id>:<feed>``. 2xx: delivered. 400/413/415/422: dead at once (the core
   will never take that body). Anything else (network error, 401, 404, 429, 5xx): retried with exponential backoff
   and jitter until FIELD_CORE_FEED_MAX_ATTEMPTS, then dead. Dead rows stay in the table for an operator.

The feed URL and secret are resolved at delivery time, so pointing at the real core later re-routes pending rows.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import psycopg
import structlog
from field_sap.ports.erp_port import ErpError, ErpReadPort

from field_worker.core_feeds.codes import CodeMap, load_code_map
from field_worker.core_feeds.config import FeedConfig
from field_worker.core_feeds.rows import read_rows
from field_worker.core_feeds.signing import signed_headers

logger = structlog.get_logger(__name__)

FEEDS = ("inventory", "open_supply")
PERMANENT = frozenset({400, 413, 415, 422})
BATCH = 20


def backoff_s(attempts: int, base: float, cap: float, rnd: Callable[[], float] = random.random) -> float:
    """Exponential backoff after ``attempts`` failed tries with +-20 % jitter, never above ``cap``."""
    return float(min(cap, base * (2.0 ** max(0, attempts - 1)) * (0.8 + 0.4 * rnd())))


class CoreFeedPublisher:
    def __init__(self, erp_port: ErpReadPort, db_url: str, config: FeedConfig | None = None,
                 client_factory: Callable[[float], httpx.AsyncClient] | None = None,
                 codes: CodeMap | None = None) -> None:
        self.erp_port = erp_port
        self.db_url = db_url
        self.config = config or FeedConfig.from_env()
        self.codes = codes or load_code_map(self.config.code_map_path)
        self._client_factory = client_factory or (lambda t: httpx.AsyncClient(timeout=t))
        self._warned = False

    # -- helpers -------------------------------------------------------------------------------------------
    def _conn(self, tenant: str) -> psycopg.Connection[Any]:
        conn = psycopg.connect(self.db_url, autocommit=True)
        conn.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)",
                     (tenant,))
        return conn

    def tenants(self) -> list[str]:
        with psycopg.connect(self.db_url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("SELECT DISTINCT t FROM field.worker_core_feed_tenants(make_interval(secs => %s)) AS t",
                        (self.config.lookback_h * 3600,))
            return [str(r[0]) for r in cur.fetchall()]

    async def run_once(self) -> tuple[int, int]:
        """(receipts staged, pushes attempted). Nothing at all unless both feed URLs are set."""
        if not self.config.enabled:
            return 0, 0
        missing = self.config.problems()
        if missing:
            if not self._warned:
                logger.error("core_feeds_misconfigured", missing=missing)  # names only, never values
                self._warned = True
            return 0, 0
        staged = sent = 0
        for tenant in self.tenants():
            staged += await self.stage_new_receipts(tenant)
            sent += await self.deliver_due(tenant)
        return staged, sent

    # -- 1. stage ------------------------------------------------------------------------------------------
    def _unstaged(self, tenant: str) -> list[tuple[str, str, str, str | None]]:
        with self._conn(tenant) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT o.id::text, o.payload->'data'->>'doc_no', o.payload->'data'->>'doc_year',
                       (SELECT d.site_id::text FROM field.posting_job j JOIN field.erp_document d ON d.id = j.erp_doc_id
                         WHERE j.id = o.aggregate_id)
                  FROM field.outbox o
                 WHERE o.tenant_id = %s AND o.event_type = 'erp.posted'
                   AND o.payload->'data'->>'doc_type' = 'GoodsReceipt'
                   AND o.created_at > NOW() - make_interval(secs => %s)
                   AND NOT EXISTS (SELECT 1 FROM field.core_feed_delivery x WHERE x.tenant_id = o.tenant_id
                                    AND x.event_id = o.id)
                 ORDER BY o.created_at LIMIT %s
                """,
                (tenant, self.config.lookback_h * 3600, BATCH),
            )
            return [(str(r[0]), str(r[1] or ""), str(r[2] or ""), r[3]) for r in cur.fetchall()]

    def _insert(self, tenant: str, site: str | None, event: str, doc: str, year: str, feed: str,
                rows: list[dict[str, Any]], status: str, reason: str | None = None, error: str | None = None) -> None:
        body = json.dumps(rows, separators=(",", ":"), ensure_ascii=False)
        with self._conn(tenant) as conn:
            conn.execute(
                """
                INSERT INTO field.core_feed_delivery (tenant_id, site_id, event_id, feed, doc_number, fiscal_year, body,
                       row_count, status, max_attempts, skip_reason, last_error)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, event_id, feed) DO NOTHING
                """,
                (tenant, site, event, feed, doc, year, body, len(rows), status, self.config.max_attempts, reason,
                 (error or "")[:500] or None),
            )

    async def stage_new_receipts(self, tenant: str) -> int:
        staged = 0
        for event, doc_no, year, site in self._unstaged(tenant):
            try:
                doc, rows = await read_rows(self.erp_port, doc_no, year, self.codes)
            except ErpError as e:
                if e.retryable:
                    logger.warning("core_feed_erp_read_retry", event_id=event, error=e.code)
                    continue
                for feed in FEEDS:
                    self._insert(tenant, site, event, doc_no, year, feed, [], "dead", error=f"ERP read: {e}")
                continue
            except NotImplementedError as e:  # the S/4 adapter (UNVERIFIED) cannot read yet
                for feed in FEEDS:
                    self._insert(tenant, site, event, doc_no, year, feed, [], "dead", error=f"ERP read: {e}")
                continue
            if doc.sandbox and not self.config.include_sandbox:
                for feed in FEEDS:
                    self._insert(tenant, site, event, doc_no, year, feed, [], "skipped", reason="sandbox receipt")
            else:
                for feed, feed_rows, why in (("inventory", rows.inventory, "no goods receipt items"),
                                             ("open_supply", rows.open_supply, "no PO reference")):
                    self._insert(tenant, site, event, doc_no, year, feed, feed_rows,
                                 "pending" if feed_rows else "skipped", reason=None if feed_rows else why)
            staged += 1
            logger.info("core_feed_staged", event_id=event, doc_number=doc_no, stock_rows=len(rows.inventory),
                        po_rows=len(rows.open_supply))
        return staged

    # -- 2. deliver ----------------------------------------------------------------------------------------
    def _claim(self, tenant: str) -> list[tuple[str, str, str, int, int, str]]:
        lease = self.config.timeout_s + 30
        with self._conn(tenant) as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE field.core_feed_delivery d
                   SET attempts = d.attempts + 1, next_attempt_at = NOW() + make_interval(secs => %s), updated_at = NOW()
                 WHERE d.id IN (SELECT id FROM field.core_feed_delivery
                                 WHERE tenant_id = %s AND status = 'pending' AND next_attempt_at <= NOW()
                                 ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT %s)
             RETURNING d.id::text, d.feed, d.body, d.attempts, d.max_attempts, d.event_id::text
                """,
                (lease, tenant, BATCH),
            )
            return [(str(r[0]), str(r[1]), str(r[2]), int(r[3]), int(r[4]), str(r[5])) for r in cur.fetchall()]

    def _record(self, tenant: str, row_id: str, status: str, http_status: int | None, error: str | None,
                retry_at: datetime | None = None) -> None:
        with self._conn(tenant) as conn:
            conn.execute(
                """
                UPDATE field.core_feed_delivery
                   SET status = %s, last_status = %s, last_error = %s, updated_at = NOW(),
                       delivered_at = CASE WHEN %s = 'delivered' THEN NOW() ELSE delivered_at END,
                       next_attempt_at = COALESCE(%s, next_attempt_at)
                 WHERE id = %s
                """,
                (status, http_status, (error or "")[:500] or None, status, retry_at, row_id),
            )

    async def deliver_due(self, tenant: str) -> int:
        claimed = self._claim(tenant)
        if not claimed:
            return 0
        async with self._client_factory(self.config.timeout_s) as client:
            for row_id, feed, body, attempts, max_attempts, event in claimed:
                url, secret = self.config.target(feed)
                raw = body.encode("utf-8")
                status: int | None = None
                error: str | None = None
                try:
                    resp = await client.post(url, content=raw, headers=signed_headers(secret, raw, f"{event}:{feed}"))
                    status = resp.status_code
                    if 200 <= status < 300:
                        self._record(tenant, row_id, "delivered", status, None)
                        logger.info("core_feed_delivered", event_id=event, feed=feed, attempts=attempts)
                        continue
                    error = f"HTTP {status}: {resp.text[:300]}"
                except httpx.HTTPError as e:
                    error = f"{type(e).__name__}: {e}"[:300]
                if status in PERMANENT or attempts >= max_attempts:
                    self._record(tenant, row_id, "dead", status, error)
                    logger.error("core_feed_dead_letter", event_id=event, feed=feed, attempts=attempts, status=status)
                else:
                    wait = backoff_s(attempts, self.config.backoff_s, self.config.backoff_max_s)
                    self._record(tenant, row_id, "pending", status, error, datetime.now(UTC) + timedelta(seconds=wait))
                    logger.warning("core_feed_retry", event_id=event, feed=feed, attempts=attempts, status=status,
                                   retry_in_s=round(wait, 1))
        return len(claimed)
