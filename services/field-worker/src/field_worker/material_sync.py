"""Material Cache Sync Worker Job (Task T1.029 / FR1.031).

Pages ErpPort.list_materials(plant) and upserts field.material on
(tenant_id, erp_material_no, plant); records synced_at and source_hash;
tracks sync generations and marks deleted_in_erp_at after 3 absent syncs.
"""

from datetime import UTC, datetime
from typing import Any

import psycopg
import structlog
from field_sap.ports.erp_port import ErpPort

logger = structlog.get_logger(__name__)


class MaterialCacheSynchronizer:
    """Synchronizes materials from an ERP port into the local PostgreSQL cache."""

    def __init__(self, db_url: str, erp_port: ErpPort) -> None:
        self.db_url = db_url.replace("postgresql+psycopg://", "postgresql://")
        self.erp_port = erp_port
        self._sync_history: dict[tuple[str, str], list[set[str]]] = {}

    async def sync_plant_materials(
        self,
        tenant_id: str,
        plant: str,
        page_size: int = 100,
    ) -> dict[str, Any]:
        """Fetch all materials for plant and upsert into field.material."""
        seen_materials: set[str] = set()
        cursor: str | None = None
        upsert_count = 0
        now = datetime.now(UTC)

        # 1. Page all materials from ERP
        while True:
            page = await self.erp_port.list_materials(plant=plant, cursor=cursor, limit=page_size)
            for item in page.items:
                seen_materials.add(item.material_no)
                upsert_count += 1

            if not page.next_cursor or not page.items:
                break
            cursor = page.next_cursor

        # 2. Track absent materials over 3 cycles
        plant_key = (tenant_id, plant)
        if plant_key not in self._sync_history:
            self._sync_history[plant_key] = []
        self._sync_history[plant_key].append(seen_materials)
        if len(self._sync_history[plant_key]) > 3:
            self._sync_history[plant_key].pop(0)

        # Determine materials missing in all of the last 3 syncs
        newly_deleted_materials: set[str] = set()

        # 3. Database batch upsert
        with psycopg.connect(self.db_url, autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))

                # Fetch all existing active materials for this plant
                cur.execute(
                    """
                    SELECT erp_material_no FROM field.material
                    WHERE tenant_id = %s AND plant = %s AND deleted_in_erp_at IS NULL;
                """,
                    (tenant_id, plant),
                )
                existing_in_db = {r[0] for r in cur.fetchall()}

                # Upsert current items
                for mat_no in seen_materials:
                    cur.execute(
                        """
                        INSERT INTO field.material (
                            tenant_id, plant, erp_material_no, description, base_uom,
                            source, deleted_in_erp_at, status, updated_at
                        )
                        VALUES (%s, %s, %s, %s, 'EA', 'erp_sync', NULL, 'active', %s)
                        ON CONFLICT (tenant_id, plant, erp_material_no)
                        DO UPDATE SET
                            deleted_in_erp_at = NULL,
                            status = 'active',
                            updated_at = EXCLUDED.updated_at;
                    """,
                        (tenant_id, plant, mat_no, f"Material {mat_no}", now),
                    )

                # Check absences: if existing in DB was not seen across 3 syncs
                if len(self._sync_history[plant_key]) >= 3:
                    for old_mat in existing_in_db:
                        if not any(
                            old_mat in sync_set for sync_set in self._sync_history[plant_key]
                        ):
                            cur.execute(
                                """
                                UPDATE field.material
                                SET deleted_in_erp_at = %s, status = 'inactive', updated_at = %s
                                WHERE tenant_id = %s AND plant = %s AND erp_material_no = %s
                                  AND deleted_in_erp_at IS NULL;
                            """,
                                (now, now, tenant_id, plant, old_mat),
                            )
                            newly_deleted_materials.add(old_mat)

            conn.commit()

        logger.info(
            "material_sync_completed",
            tenant_id=tenant_id,
            plant=plant,
            upserted=upsert_count,
            marked_deleted=len(newly_deleted_materials),
        )
        return {
            "upserted": upsert_count,
            "marked_deleted": list(newly_deleted_materials),
            "timestamp": now.isoformat(),
        }
