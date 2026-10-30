"""Unit tests for MaterialCacheSynchronizer (Task T1.029 / FR1.031)."""

import os
import uuid

import psycopg
import pytest
from field_sap.ports.erp_port import MaterialItem, MaterialPage
from field_worker.material_sync import MaterialCacheSynchronizer

DATABASE_URL = os.getenv(
    "FIELD_DATABASE_URL",
    "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field",
).replace("postgresql+psycopg://", "postgresql://")


class MockErpPort:
    def __init__(self, materials_sequence: list[list[str]]) -> None:
        self.materials_sequence = materials_sequence
        self.call_count = 0

    async def list_materials(
        self,
        plant: str,
        cursor: str | None = None,
        limit: int = 100,
    ) -> MaterialPage:
        idx = min(self.call_count, len(self.materials_sequence) - 1)
        mat_nos = self.materials_sequence[idx]
        items = tuple(
            MaterialItem(
                material_no=m,
                description=f"Desc {m}",
                plant=plant,
                base_uom="EA",
            )
            for m in mat_nos
        )
        return MaterialPage(items=items, next_cursor=None, total_count=len(items))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_material_cache_sync_three_missed_cycles():
    tenant_id = str(uuid.uuid4())
    plant = "1000"

    # Cycle 0: MAT-A, MAT-B
    # Cycle 1: MAT-A (MAT-B absent 1)
    # Cycle 2: MAT-A (MAT-B absent 2)
    # Cycle 3: MAT-A (MAT-B absent 3 -> marked deleted)
    port = MockErpPort(
        [
            ["MAT-A", "MAT-B"],
            ["MAT-A"],
            ["MAT-A"],
            ["MAT-A"],
        ]
    )

    syncer = MaterialCacheSynchronizer(db_url=DATABASE_URL, erp_port=port)

    # Sync 0
    res0 = await syncer.sync_plant_materials(tenant_id=tenant_id, plant=plant)
    assert res0["upserted"] == 2
    port.call_count += 1

    # Check MAT-B is active
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, true), set_config('app.site_ids', '*', true)", (tenant_id,))
        cur.execute(
            "SELECT deleted_in_erp_at FROM field.material WHERE tenant_id = %s AND erp_material_no = 'MAT-B';",
            (tenant_id,),
        )
        val = cur.fetchone()[0]
        assert val is None

    # Sync 1
    await syncer.sync_plant_materials(tenant_id=tenant_id, plant=plant)
    port.call_count += 1

    # Sync 2
    await syncer.sync_plant_materials(tenant_id=tenant_id, plant=plant)
    port.call_count += 1

    # Sync 3 (3rd consecutive absence)
    res3 = await syncer.sync_plant_materials(tenant_id=tenant_id, plant=plant)
    assert "MAT-B" in res3["marked_deleted"]

    # Verify in DB
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, true), set_config('app.site_ids', '*', true)", (tenant_id,))
        cur.execute(
            "SELECT status, deleted_in_erp_at FROM field.material WHERE tenant_id = %s AND erp_material_no = 'MAT-B';",
            (tenant_id,),
        )
        row = cur.fetchone()
        assert row[0] == "inactive"
        assert row[1] is not None
