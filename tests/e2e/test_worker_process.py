"""The real worker process as the NOBYPASSRLS field_worker role (C4: worker.py was a stub).

FieldWorker.poll_inbound_deliveries imports an erp-sim delivery as a receive task; the API confirms
it; FieldWorker.process_posting_queue posts it through ErpPort and the document number is written
back. Run as field_worker, so a missing site scope or grant would make updates silently hit 0 rows.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import httpx
import psycopg
import pytest
from erp_sim.app import app as erp_app
from fastapi.testclient import TestClient
from field_api.app import app
from field_api.auth.jwt import create_dev_token
from field_sap.sim.adapter import SimAdapter
from field_worker.worker import FieldWorker

pytestmark = pytest.mark.unit
ADMIN = os.getenv("FIELD_ADMIN_DATABASE_URL", "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field")
WORKER = os.getenv("FIELD_WORKER_DATABASE_URL", "postgresql://field_worker:devpassword@127.0.0.1:5450/field")
ERPSIM = ADMIN.rsplit("/", 1)[0] + "/erpsim"


def test_worker_process_imports_and_posts_as_field_worker_role() -> None:
    tenant, site = str(uuid.uuid4()), str(uuid.uuid4())
    plant = f"W{uuid.uuid4().hex[:7].upper()}"
    deliv = f"18{uuid.uuid4().int % 10**8:08d}"
    mat = f"WRK-{uuid.uuid4().hex[:6].upper()}"
    with psycopg.connect(ERPSIM, autocommit=True) as c, c.cursor() as cur:
        cur.execute("INSERT INTO erpsim.inbound_delivery (client, delivery_document, plant, storage_location, status)"
                    " VALUES ('100', %s, %s, '0001', 'open')", (deliv, plant))
        cur.execute("INSERT INTO erpsim.inbound_delivery_item (client, delivery_document, item_no, material_no,"
                    " delivery_qty, actual_qty, uom, status) VALUES ('100', %s, '000010', %s, 7, 0, 'EA', 'open')",
                    (deliv, mat))
    with psycopg.connect(ADMIN, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant,))
        cur.execute("INSERT INTO field.site (id, tenant_id, code, name, kind, erp_plant, status)"
                    " VALUES (%s, %s, %s, 'WRK', 'warehouse', %s, 'active')", (site, tenant, f"W-{plant}", plant))

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=erp_app), base_url="http://127.0.0.1:8002") as cl:
            w = FieldWorker(erp_port=SimAdapter(app=erp_app), db_url=WORKER, ibd_client=cl)
            assert await w.poll_inbound_deliveries() >= 1
            api = TestClient(app)
            tok = {"Authorization": "Bearer " + create_dev_token("op-w", tenant, ["field.operator"], site_ids=[site])}
            task = next(t for t in api.get(f"/v1/tasks?site_id={site}", headers=tok).json()["items"]
                        if t["erp_ref"] == deliv)
            line = task["lines"][0]
            api.post(f"/v1/tasks/{task['id']}/lines/{line['id']}/counts",
                     json={"qty": 7, "uom": "EA", "source": "scan"}, headers=tok)
            doc = api.post(f"/v1/tasks/{task['id']}/confirm", json={}, headers=tok).json()["erp_document_id"]
            assert await w.process_posting_queue() >= 2  # other tenants' due jobs are drained too
            with psycopg.connect(ADMIN) as c, c.cursor() as cur:
                cur.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant,))
                cur.execute("SELECT status, doc_number FROM field.erp_document WHERE id = %s", (doc,))
                status, number = cur.fetchone()  # type: ignore[misc]
                cur.execute("SELECT status FROM field.task WHERE id = %s", (task["id"],))
                assert cur.fetchone()[0] == "completed"  # type: ignore[index]
            assert status == "posted" and number
            assert w.get_status()["jobs_processed"] >= 2

    asyncio.run(run())
