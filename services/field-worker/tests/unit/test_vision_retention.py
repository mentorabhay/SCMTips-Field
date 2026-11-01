"""Vision look label text retention (M5 contract §6, M5-V03): ``raw_labels`` is cleared after 30 days by the worker
role through field.worker_purge_vision_raw (SECURITY DEFINER); the rest of the look stays as evidence."""

from __future__ import annotations

import os
import uuid
from typing import Any

import psycopg
import pytest
from field_worker.retention.vision import purge_vision_raw

pytestmark = pytest.mark.unit
ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
WORKER = os.getenv("FIELD_WORKER_DATABASE_URL", "postgresql://field_worker:devpassword@127.0.0.1:5450/field")


def _sql(tenant: str, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with psycopg.connect(ADMIN, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)", (tenant,))
        cur.execute(sql, params)
        return list(cur.fetchall()) if cur.description else []


def _look(tenant: str, site: str, task: str, days_ago: int) -> str:
    return str(_sql(tenant, """
        INSERT INTO field.vision_look (tenant_id, site_id, task_id, capture_id, "case", object, source, idempotency_key,
               principal_id, image, instances, raw_labels, counts, proposal, say, created_at)
        VALUES (%s, %s, %s, %s, 'grocery', 'pack', 'model', %s, 'op-1', '{}', '[{"n": 1}]', '{"1": "12 x 25 g"}',
                '{"seen": 1}', '{"receive": 1, "flag": 0}', '1 of 1 packs.', NOW() - make_interval(days => %s))
        RETURNING id""", (tenant, site, task, str(uuid.uuid4()), str(uuid.uuid4()), days_ago))[0][0])


def test_m5_v03_purge_clears_label_text_of_old_looks_only() -> None:
    tenant, site = str(uuid.uuid4()), str(uuid.uuid4())
    _sql(tenant, "INSERT INTO field.site (id, tenant_id, code, name, kind, status) VALUES (%s, %s, %s, 'V', 'warehouse',"
                 " 'active')", (site, tenant, f"VR-{uuid.uuid4().hex[:6].upper()}"))
    task = str(_sql(tenant, "INSERT INTO field.task (tenant_id, site_id, type, status, title) VALUES (%s, %s, 'receive',"
                            " 'pending', 'D') RETURNING id", (tenant, site))[0][0])
    old, new = _look(tenant, site, task, 31), _look(tenant, site, task, 2)
    assert purge_vision_raw(WORKER, days=30) >= 1
    rows = {str(r[0]): r[1:] for r in _sql(tenant, "SELECT id, raw_labels, raw_purged_at IS NOT NULL, instances,"
                                                         " counts, say FROM field.vision_look WHERE task_id = %s", (task,))}
    assert rows[old][:2] == (None, True) and rows[old][2:] == ([{"n": 1}], {"seen": 1}, "1 of 1 packs.")
    assert rows[new][:2] == ({"1": "12 x 25 g"}, False)
    purge_vision_raw(WORKER, days=30)  # again: the young look keeps its text
    assert _sql(tenant, "SELECT raw_labels FROM field.vision_look WHERE id = %s", (new,)) == [({"1": "12 x 25 g"},)]
    with psycopg.connect(WORKER) as c, c.cursor() as cur, pytest.raises(psycopg.errors.RaiseException):
        cur.execute("SELECT field.worker_purge_vision_raw(0)")


def test_m5_v03_worker_role_cannot_read_looks_directly() -> None:
    with psycopg.connect(WORKER) as c, c.cursor() as cur:  # NOBYPASSRLS, no tenant set
        cur.execute("SELECT count(*) FROM field.vision_look")
        row = cur.fetchone()
    assert row is not None and row[0] == 0
