"""Field Assistant retention (owner amendment A-03: voice text and photos kept 30 days), as the worker role.

field.worker_purge_assistant_content clears heard / said / photo_ref and tool-call arguments of turns older than
the retention window and returns photo refs no turn uses any more; the worker deletes those files. The worker's
tick runs it (FIELD_ASSISTANT_PURGE_S).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any

import psycopg
import pytest
from field_api.assistant.photos import AssistantPhotoStore
from field_sap.sim.adapter import SimAdapter
from field_worker.retention.assistant import purge_assistant_content, retention_days
from field_worker.worker import FieldWorker

pytestmark = pytest.mark.unit
ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
WORKER = os.getenv("FIELD_WORKER_DATABASE_URL", "postgresql://field_worker:devpassword@127.0.0.1:5450/field")
JPEG = b"\xff\xd8\xff\xe0retention-test" + os.urandom(8)


def _sql(tenant: str, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with psycopg.connect(ADMIN, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)", (tenant,))
        cur.execute(sql, params)
        return list(cur.fetchall()) if cur.description else []


@pytest.fixture
def data(tmp_path: Path) -> dict[str, Any]:
    tenant, site = str(uuid.uuid4()), str(uuid.uuid4())
    _sql(tenant, "INSERT INTO field.site (id, tenant_id, code, name, kind, status) VALUES (%s, %s, %s, 'R', 'warehouse',"
                 " 'active')", (site, tenant, f"RT-{uuid.uuid4().hex[:6].upper()}"))
    sess = str(_sql(tenant, "INSERT INTO field.assistant_session (tenant_id, site_id, principal_id, started_at)"
                            " VALUES (%s, %s, 'op-1', NOW() - interval '40 days') RETURNING id", (tenant, site))[0][0])
    store = AssistantPhotoStore(str(tmp_path / "photos"))
    shared = store.put(tenant, JPEG)
    only_old = store.put(tenant, JPEG + b"old")

    def add(days_ago: int, photo: str | None) -> str:
        return str(_sql(tenant, "INSERT INTO field.assistant_turn (tenant_id, site_id, session_id, at, event, heard,"
                                " said, tool_calls, photo_ref, ai) VALUES (%s, %s, %s, NOW() - make_interval(days => %s),"
                                " 'utterance', 'a blue mug', 'Blue mug. How many?',"
                                " '[{\"name\": \"add_sandbox_item\", \"args\": {\"description\": \"blue mug\"}}]',"
                                " %s, 'rules') RETURNING id", (tenant, site, sess, days_ago, photo))[0][0])

    return {"tenant": tenant, "store": store, "shared": shared, "only_old": only_old,
            "old": [add(31, shared), add(45, only_old)], "new": add(2, shared)}


def _turn(tenant: str, tid: str) -> tuple[Any, ...]:
    return tuple(_sql(tenant, "SELECT heard, said, photo_ref, tool_calls, purged_at IS NOT NULL, event, ai"
                              " FROM field.assistant_turn WHERE id = %s", (tid,))[0])


def test_purge_clears_old_content_and_deletes_unused_photos(data: dict[str, Any]) -> None:
    res = purge_assistant_content(WORKER, days=30, store=data["store"])
    for tid in data["old"]:
        heard, said, photo, calls, purged, event, ai = _turn(data["tenant"], tid)
        assert (heard, said, photo, purged, event, ai) == (None, None, None, True, "utterance", "rules")
        assert calls == [{"name": "add_sandbox_item"}]  # arguments (operator words) removed, the record kept
    heard, said, photo, calls, purged, *_ = _turn(data["tenant"], data["new"])
    assert (heard, said, photo, purged) == ("a blue mug", "Blue mug. How many?", data["shared"], False)
    assert not data["store"].exists(data["only_old"])  # no turn uses it any more
    assert data["store"].exists(data["shared"])  # the 2-day-old turn still uses it
    assert res.photos_deleted >= 1
    again = purge_assistant_content(WORKER, days=30, store=data["store"])  # idempotent
    assert again.photos_deleted == 0 or not data["store"].exists(data["only_old"])


def test_retention_days_default_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIELD_ASSISTANT_RETENTION_DAYS", raising=False)
    assert retention_days() == 30
    monkeypatch.setenv("FIELD_ASSISTANT_RETENTION_DAYS", "0")
    with pytest.raises(ValueError):
        retention_days()
    with psycopg.connect(WORKER) as c, c.cursor() as cur, pytest.raises(psycopg.errors.RaiseException):
        cur.execute("SELECT * FROM field.worker_purge_assistant_content(0)")


def test_worker_role_cannot_read_turns_directly() -> None:
    with psycopg.connect(WORKER) as c, c.cursor() as cur:  # NOBYPASSRLS, no tenant set
        cur.execute("SELECT count(*) FROM field.assistant_turn")
        assert cur.fetchone() == (0,)


def test_worker_tick_runs_the_retention_job(data: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIELD_ASSISTANT_PHOTO_DIR", str(data["store"].root))
    w = FieldWorker(erp_port=SimAdapter(base_url="http://127.0.0.1:9"), db_url=WORKER)  # never called here
    calls: list[str] = []
    monkeypatch.setattr(w, "process_posting_queue", lambda: asyncio.sleep(0))
    monkeypatch.setattr(w, "process_tower_queues", lambda: 0)
    monkeypatch.setattr(w, "poll_inbound_deliveries", lambda: asyncio.sleep(0))
    monkeypatch.setattr(w, "purge_expired_idempotency_records", lambda: 0)
    real = w.purge_assistant_content
    monkeypatch.setattr(w, "purge_assistant_content", lambda: calls.append("purge") or real())
    asyncio.run(w.tick(1000.0))
    asyncio.run(w.tick(1001.0))  # within FIELD_ASSISTANT_PURGE_S: not again
    assert calls == ["purge"]
    assert _turn(data["tenant"], data["old"][0])[4] is True
