"""SCMTIPS Field worker process (T1.023 / FR1.008) — real loop (C4; was a stub returning 0).

Run:  uv run python -m field_worker

Every FIELD_WORKER_TICK_S (1 s):
  - drains due posting jobs per tenant through PostingQueueWorker (ordered, advisory-locked, ErpPort)
Every FIELD_IBD_POLL_S (spec default 300 s; set lower for a field test):
  - imports open inbound deliveries for each active ERP site (receive tasks)
Every 10 min:
  - purges expired idempotency records

Connects as field_worker (NOBYPASSRLS) via FIELD_WORKER_DATABASE_URL and discovers tenants through
SECURITY DEFINER functions (migration field_0057). The ERP adapter is chosen by FIELD_ERP_ADAPTER:
``sim`` (erp-sim at FIELD_ERP_SIM_URL) or ``s4`` (refused: the S/4 adapter is a stub, UNVERIFIED).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import socket
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import psycopg
import structlog
from field_sap.ports.erp_port import ErpPort
from field_sap.sim.adapter import SimAdapter

from field_worker.posting.equipment_queue import process_next_tower_job
from field_worker.posting.queue import PostingQueueWorker
from field_worker.warehouse.ibd_import import poll_and_import_inbound_deliveries

logger = structlog.get_logger(__name__)

WORKER_DB = os.getenv("FIELD_WORKER_DATABASE_URL", "postgresql://field_worker:devpassword@127.0.0.1:5450/field")
ERP_URL = os.getenv("FIELD_ERP_SIM_URL", "http://127.0.0.1:8002")
TICK_S = float(os.getenv("FIELD_WORKER_TICK_S", "1"))
IBD_POLL_S = float(os.getenv("FIELD_IBD_POLL_S", "300"))
PURGE_S = 600.0


def build_erp_port() -> ErpPort:
    kind = os.getenv("FIELD_ERP_ADAPTER", "sim")
    if kind == "sim":
        return SimAdapter(base_url=ERP_URL)
    raise SystemExit(f"FIELD_ERP_ADAPTER={kind!r} is not available: the S/4 adapter is a stub (UNVERIFIED)")


class FieldWorker:
    def __init__(
        self, erp_port: ErpPort | None = None, db_url: str = WORKER_DB, ibd_client: httpx.AsyncClient | None = None
    ) -> None:
        self.db_url = db_url
        self.ibd_client = ibd_client
        self.erp_port = erp_port or build_erp_port()
        self.posting = PostingQueueWorker(erp_port=self.erp_port, db_url=db_url)
        self.is_running = False
        self.jobs_processed = 0
        self.tasks_imported = 0
        self._last_ibd = 0.0
        self._last_purge = 0.0
        self.last_heartbeat: str | None = None

    def _query(self, sql: str) -> list[tuple[Any, ...]]:
        with psycopg.connect(self.db_url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(sql)
            return list(cur.fetchall())

    async def process_posting_queue(self) -> int:
        n = 0
        for (tenant,) in self._query("SELECT field.worker_pending_tenants()"):
            while await self.posting.process_one_job(str(tenant)):
                n += 1
        self.jobs_processed += n
        return n

    def process_tower_queues(self) -> int:
        """Tower equipment install/dismantle queues (EQUIP:<tower FL>) through the SAP equipment adapter."""
        n = 0
        for (tenant,) in self._query("SELECT field.worker_pending_tenants()"):
            with psycopg.connect(self.db_url, autocommit=True) as conn, conn.cursor() as cur:
                cur.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)",
                            (str(tenant),))
                cur.execute("SELECT DISTINCT queue_key FROM field.posting_job WHERE status = 'pending'"
                            " AND queue_key LIKE 'EQUIP:%' AND next_attempt_at <= NOW()")
                queues = [r[0] for r in cur.fetchall()]
            for q in queues:
                res = process_next_tower_job(str(tenant), q, db_url=self.db_url, ignore_backoff=False)
                if res and res.get("status") == "completed":
                    n += 1
        self.jobs_processed += n
        return n

    async def poll_inbound_deliveries(self) -> int:
        created = 0
        for tenant, site, plant, slocs in self._query("SELECT * FROM field.worker_erp_sites()"):
            try:
                c, _lines, _conf = await poll_and_import_inbound_deliveries(
                    tenant_id=str(tenant), site_id=str(site), plant=plant, storage_locations=list(slocs or []) or None,
                    erp_url=ERP_URL, db_url=self.db_url, client=self.ibd_client,
                )
                created += c
            except Exception:  # one site's ERP failure must not stop the others
                logger.exception("ibd_poll_failed", site_id=str(site))
        self.tasks_imported += created
        return created

    def purge_expired_idempotency_records(self) -> int:
        rows = self._query("SELECT field.worker_purge_idempotency()")
        return int(rows[0][0]) if rows else 0

    async def tick(self, now: float) -> None:
        """One pass over every loop. A failing loop is logged and must not starve the others."""
        await self._guard("posting", self.process_posting_queue())
        await self._guard("tower", asyncio.to_thread(self.process_tower_queues))
        if now - self._last_ibd >= IBD_POLL_S:
            self._last_ibd = now
            await self._guard("ibd_import", self.poll_inbound_deliveries())
        if now - self._last_purge >= PURGE_S:
            self._last_purge = now
            await self._guard("idempotency_purge", asyncio.to_thread(self.purge_expired_idempotency_records))
        self.last_heartbeat = datetime.now(UTC).isoformat()
        await asyncio.to_thread(self.record_heartbeat)

    def record_heartbeat(self) -> None:
        """Upsert ops.service_heartbeat so GET /v1/system/status can see this worker is alive."""
        with psycopg.connect(self.db_url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ops.service_heartbeat (service, instance, beat_at, details)"
                " VALUES ('field-worker', %s, NOW(), %s::jsonb)"
                " ON CONFLICT (service) DO UPDATE SET instance = EXCLUDED.instance, beat_at = NOW(),"
                " details = EXCLUDED.details",
                (f"{socket.gethostname()}:{os.getpid()}",
                 json.dumps({"jobs_processed": self.jobs_processed, "tasks_imported": self.tasks_imported})),
            )

    @staticmethod
    async def _guard(loop: str, aw: Any) -> None:
        try:
            await aw
        except Exception:
            logger.exception("worker_loop_failed", loop=loop)

    async def run(self) -> None:
        self.is_running = True
        logger.info("field_worker_started", erp=ERP_URL, ibd_poll_s=IBD_POLL_S)
        while self.is_running:
            try:
                await self.tick(time.monotonic())
            except Exception:
                logger.exception("worker_tick_failed")
            await asyncio.sleep(TICK_S)
        logger.info("field_worker_stopped")

    def stop(self) -> None:
        self.is_running = False

    def get_status(self) -> dict[str, Any]:
        return {"status": "running" if self.is_running else "idle", "jobs_processed": self.jobs_processed,
                "tasks_imported": self.tasks_imported, "last_heartbeat": self.last_heartbeat}


def main() -> None:
    worker = FieldWorker()
    loop = asyncio.new_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows: Ctrl+C raises KeyboardInterrupt instead
            loop.add_signal_handler(sig, worker.stop)
    try:
        loop.run_until_complete(worker.run())
    except KeyboardInterrupt:
        worker.stop()
