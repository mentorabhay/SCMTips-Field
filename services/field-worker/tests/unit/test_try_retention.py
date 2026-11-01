"""Try look retention (M5-W01): photos and label text of try looks are kept 24 hours. The worker role clears them through
field.worker_purge_try_looks (SECURITY DEFINER) and deletes the photo files no look refers to any more; rate slots
older than a day go too. Task looks are never touched."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import psycopg
import pytest
from field_api.vision.try_look import TryPhotoStore
from field_worker.retention.try_looks import purge_try_looks

pytestmark = pytest.mark.unit
ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
WORKER = os.getenv("FIELD_WORKER_DATABASE_URL", "postgresql://field_worker:devpassword@127.0.0.1:5450/field")


def _sql(tenant: str, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with psycopg.connect(ADMIN, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false), set_config('app.site_ids', '*', false)", (tenant,))
        cur.execute(sql, params)
        return list(cur.fetchall()) if cur.description else []


def _try_look(tenant: str, uri: str, hours_left: float) -> str:
    return str(_sql(tenant, """
        INSERT INTO field.vision_look (tenant_id, "case", object, source, idempotency_key, principal_id, image, instances,
               raw_labels, counts, proposal, say, kind, photo_uri, photo_expires_at)
        VALUES (%s, 'grocery', 'pack', 'model', %s, 'judge', '{}', '[{"n": 1}]', '{"1": "pack of 6"}', '{"seen": 1}',
                '{"receive": 1, "flag": 0}', '1 of 1 packs.', 'try', %s, NOW() + make_interval(secs => %s))
        RETURNING id""", (tenant, str(uuid.uuid4()), uri, hours_left * 3600))[0][0])


def test_m5_w01_purge_clears_expired_try_photos_and_deletes_unused_files(tmp_path: Path) -> None:
    tenant = str(uuid.uuid4())
    store = TryPhotoStore(str(tmp_path / "try"))
    old_uri = store.put(tenant, b"\xff\xd8\xffold-photo")
    shared_uri = store.put(tenant, b"\xff\xd8\xffshared-photo")
    old = _try_look(tenant, old_uri, -1)
    shared_old = _try_look(tenant, shared_uri, -0.5)
    shared_new = _try_look(tenant, shared_uri, 20)  # the same photo uploaded again later: its file must stay
    _sql(tenant, "INSERT INTO field.try_look_slot (tenant_id, principal_id, created_at) VALUES"
                 " (%s, 'judge', NOW() - interval '2 days'), (%s, 'judge', NOW())", (tenant, tenant))
    result = purge_try_looks(WORKER, store)
    assert result.photos_deleted >= 1
    assert not store.exists(old_uri) and store.exists(shared_uri)
    rows = {str(r[0]): r[1:] for r in _sql(tenant, "SELECT id, photo_uri, raw_labels, photo_purged_at IS NOT NULL,"
                                                    " counts, say FROM field.vision_look WHERE tenant_id = %s", (tenant,))}
    assert rows[old] == (None, None, True, {"seen": 1}, "1 of 1 packs.")
    assert rows[shared_old][:3] == (None, None, True)
    assert rows[shared_new][:3] == (shared_uri, {"1": "pack of 6"}, False)
    assert _sql(tenant, "SELECT count(*) FROM field.try_look_slot WHERE tenant_id = %s", (tenant,)) == [(1,)]
    again = purge_try_looks(WORKER, store)  # nothing left to purge for this tenant: the young look keeps its photo
    assert store.exists(shared_uri) and again.photos_released >= 0


def test_m5_w01_worker_role_cannot_read_try_looks_or_slots_directly() -> None:
    with psycopg.connect(WORKER) as c, c.cursor() as cur:  # NOBYPASSRLS, no tenant set
        cur.execute("SELECT count(*) FROM field.vision_look WHERE kind = 'try'")
        assert cur.fetchone() == (0,)
        cur.execute("SELECT count(*) FROM field.try_look_slot")
        assert cur.fetchone() == (0,)
