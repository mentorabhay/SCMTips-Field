"""Comprehensive Demo Data Seeder for E2E Application Simulation.

Seeds:
- Tenant: e8eb2a80-d529-4bdd-b669-d21fe847cb74
- Telecom Tower Sites (Delhi North, Gurugram South) and Central Logistics Warehouse
- Functional Location tree (Towers, Sectors, Levels, Positions)
- Active Installed Equipment Base (RRUs, Antennas, Microwave Dishes)
- 3D Site Graph nodes and climb/walk edges
- Audit Tasks, Matched & Mismatch Findings, and Exception Cases
- Asset Models with BOM items and explode vectors
- Lone-Worker & Climb-Safe telemetry
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import psycopg

DATABASE_URL = (
    os.getenv(
        "FIELD_DATABASE_URL",
        "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field",
    )
    .replace("postgresql+psycopg://", "postgresql://")
    .replace("@localhost:", "@127.0.0.1:")
)

TENANT_ID = "e8eb2a80-d529-4bdd-b669-d21fe847cb74"
SITE_1_ID = "018f4a10-0001-7000-8000-000000000001"
SITE_2_ID = "018f4a10-0002-7000-8000-000000000002"
WH_SITE_ID = "018f4a10-0003-7000-8000-000000000003"
MODEL_ID = "018f4a10-0004-7000-8000-000000000004"
TASK_ID = "018f4a10-0005-7000-8000-000000000005"
CASE_1_ID = "018f4a10-0006-7000-8000-000000000006"
CASE_2_ID = "018f4a10-0007-7000-8000-000000000007"


def seed_all() -> None:
    print(f"Connecting to database to seed comprehensive demo data for tenant {TENANT_ID}...")
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true);", (TENANT_ID,))
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (TENANT_ID,))
            cur.execute("SELECT set_config('app.site_ids', '*', true);")

            now = datetime.now(UTC)

            # 1. Sites
            cur.execute(
                """
                INSERT INTO field.site (id, tenant_id, code, name, kind, status, lat, lon, geofence_radius_m)
                VALUES
                    (%s, %s, 'IN01-TWR-0042', 'Delhi North Telecom Tower #42', 'tower', 'active', 28.7041, 77.1025, 150),
                    (%s, %s, 'IN01-TWR-0088', 'Gurugram South Macro Tower #88', 'tower', 'active', 28.4595, 77.0266, 120),
                    (%s, %s, 'SAMPLE-WH-01', 'Central Logistics Warehouse', 'warehouse', 'active', 28.5355, 77.3910, 300)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    status = EXCLUDED.status;
                """,
                (SITE_1_ID, TENANT_ID,
                 SITE_2_ID, TENANT_ID,
                 WH_SITE_ID, TENANT_ID),
            )

            # 2. Locations on SITE_1 (Delhi North Tower)
            loc_t01 = "018f4a10-0010-7000-8000-000000000001"
            loc_sa = "018f4a10-0010-7000-8000-000000000002"
            loc_l01 = "018f4a10-0010-7000-8000-000000000003"
            loc_p01 = "018f4a10-0010-7000-8000-000000000004"
            loc_p02 = "018f4a10-0010-7000-8000-000000000005"
            loc_l02 = "018f4a10-0010-7000-8000-000000000006"
            loc_p03 = "018f4a10-0010-7000-8000-000000000007"
            loc_sb = "018f4a10-0010-7000-8000-000000000008"
            loc_l03 = "018f4a10-0010-7000-8000-000000000009"
            loc_p04 = "018f4a10-0010-7000-8000-000000000010"

            locs = [
                (loc_t01, SITE_1_ID, None, "T01", "IN01-TWR-0042-T01", "tower", None, 0.0, "T01", 1),
                (loc_sa, SITE_1_ID, loc_t01, "SA", "IN01-TWR-0042-T01-SA", "sector", "A", None, "T01.SA", 2),
                (loc_l01, SITE_1_ID, loc_sa, "L01", "IN01-TWR-0042-T01-SA-L01", "level", "A", 15.0, "T01.SA.L01", 3),
                (loc_p01, SITE_1_ID, loc_l01, "P01", "IN01-TWR-0042-T01-SA-L01-P01", "position", "A", 15.0, "T01.SA.L01.P01", 4),
                (loc_p02, SITE_1_ID, loc_l01, "P02", "IN01-TWR-0042-T01-SA-L01-P02", "position", "A", 15.0, "T01.SA.L01.P02", 4),
                (loc_l02, SITE_1_ID, loc_sa, "L02", "IN01-TWR-0042-T01-SA-L02", "level", "A", 30.0, "T01.SA.L02", 3),
                (loc_p03, SITE_1_ID, loc_l02, "P01", "IN01-TWR-0042-T01-SA-L02-P01", "position", "A", 30.0, "T01.SA.L02.P01", 4),
                (loc_sb, SITE_1_ID, loc_t01, "SB", "IN01-TWR-0042-T01-SB", "sector", "B", None, "T01.SB", 2),
                (loc_l03, SITE_1_ID, loc_sb, "L01", "IN01-TWR-0042-T01-SB-L01", "level", "B", 20.0, "T01.SB.L01", 3),
                (loc_p04, SITE_1_ID, loc_l03, "P01", "IN01-TWR-0042-T01-SB-L01-P01", "position", "B", 20.0, "T01.SB.L01.P01", 4),
            ]

            for lid, sid, pid, code, fl, kind, sec, h, path, dep in locs:
                cur.execute(
                    """
                    INSERT INTO field.location (id, tenant_id, site_id, parent_id, code, fl_code, kind, sector_code, height_m, path, depth)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        code = EXCLUDED.code,
                        fl_code = EXCLUDED.fl_code,
                        kind = EXCLUDED.kind,
                        height_m = EXCLUDED.height_m,
                        path = EXCLUDED.path;
                    """,
                    (lid, TENANT_ID, sid, pid, code, fl, kind, sec, h, path, dep),
                )

            # 3. Installed Equipment
            eq_1 = "018f4a10-0020-7000-8000-000000000001"
            eq_2 = "018f4a10-0020-7000-8000-000000000002"
            eq_3 = "018f4a10-0020-7000-8000-000000000003"
            eq_4 = "018f4a10-0020-7000-8000-000000000004"

            cur.execute(
                """
                INSERT INTO field.equipment (id, tenant_id, serial_no, erp_equipment_no, material, equipment_class, current_location_id, status, pinned_model_version)
                VALUES
                    (%s, %s, '21B3M0411', '10004417', 'RRU-4T-B3', 'RRU', %s, 'installed', '1.3.0'),
                    (%s, %s, '21B3M0412', '10004418', 'RRU-4T-B3', 'RRU', %s, 'installed', '1.3.0'),
                    (%s, %s, '21A9K8812', '10005520', 'ANT-6PORT-HP', 'ANTENNA', %s, 'installed', '2.1.0'),
                    (%s, %s, '21M4D0077', '10006633', 'MW-DISH-0.6M', 'DISH', %s, 'installed', '1.0.0')
                ON CONFLICT (id) DO UPDATE SET
                    current_location_id = EXCLUDED.current_location_id,
                    status = EXCLUDED.status;
                """,
                (eq_1, TENANT_ID, loc_p01,
                 eq_2, TENANT_ID, loc_p02,
                 eq_3, TENANT_ID, loc_p03,
                 eq_4, TENANT_ID, loc_p04),
            )

            # 4. 3D Site Graph Nodes
            gn_ground = "018f4a10-0030-7000-8000-000000000001"
            gn_ladder = "018f4a10-0030-7000-8000-000000000002"
            gn_rest1 = "018f4a10-0030-7000-8000-000000000003"
            gn_secA = "018f4a10-0030-7000-8000-000000000004"
            gn_top = "018f4a10-0030-7000-8000-000000000005"

            cur.execute(
                """
                INSERT INTO field.site_graph_node (id, tenant_id, site_id, name, node_type, subkind, x_m, y_m, z_m)
                VALUES
                    (%s, %s, %s, 'Site Entrance & Shelter', 'waypoint', 'ground', 0.0, 0.0, 0.0),
                    (%s, %s, %s, 'Ladder Foot T01', 'waypoint', 'ladder_foot', 12.0, 8.0, 0.0),
                    (%s, %s, %s, 'Rest Platform 1 (15m)', 'waypoint', 'rest_platform', 12.0, 8.0, 15.0),
                    (%s, %s, %s, 'Sector A Platform (30m)', 'waypoint', 'sector_platform', 12.0, 8.0, 30.0),
                    (%s, %s, %s, 'Tower Mast Top (45m)', 'waypoint', 'antenna', 12.0, 8.0, 45.0)
                ON CONFLICT (id) DO NOTHING;
                """,
                (gn_ground, TENANT_ID, SITE_1_ID,
                 gn_ladder, TENANT_ID, SITE_1_ID,
                 gn_rest1, TENANT_ID, SITE_1_ID,
                 gn_secA, TENANT_ID, SITE_1_ID,
                 gn_top, TENANT_ID, SITE_1_ID),
            )

            # 5. Audit Task & Findings
            cur.execute(
                """
                INSERT INTO field.task (id, tenant_id, site_id, title, type, status)
                VALUES (%s, %s, %s, 'Annual Telecom Tower Audit 2026', 'audit', 'in_progress')
                ON CONFLICT (id) DO UPDATE SET status = 'in_progress';
                """,
                (TASK_ID, TENANT_ID, SITE_1_ID),
            )

            # Audit findings: matched, mismatch, tower-only
            f_matched = "018f4a10-0040-7000-8000-000000000001"
            f_mismatch = "018f4a10-0040-7000-8000-000000000002"
            f_tower_only = "018f4a10-0040-7000-8000-000000000003"

            cur.execute(
                """
                INSERT INTO field.audit_finding (
                    id, tenant_id, task_id, site_id, location_id, class,
                    expected_serial, found_serial, status, decision, dedupe_key
                ) VALUES
                    (%s, %s, %s, %s, %s, 'matched', '21B3M0411', '21B3M0411', 'open', 'waived', 'dedupe-demo-matched'),
                    (%s, %s, %s, %s, %s, 'serial_mismatch', '21B3M0412', '21B3M9999', 'open', NULL, 'dedupe-demo-mismatch'),
                    (%s, %s, %s, %s, %s, 'tower_only', NULL, '21M4D0077', 'open', NULL, 'dedupe-demo-tower-only')
                ON CONFLICT (id) DO NOTHING;
                """,
                (f_matched, TENANT_ID, TASK_ID, SITE_1_ID, loc_p01,
                 f_mismatch, TENANT_ID, TASK_ID, SITE_1_ID, loc_p02,
                 f_tower_only, TENANT_ID, TASK_ID, SITE_1_ID, loc_p04),
            )

            # 6. S1 & S2 Exception Cases
            cur.execute(
                """
                INSERT INTO field.exception_case (
                    id, tenant_id, site_id, type, dedupe_key, status, severity,
                    rule_id, subject, facts, value_at_risk, assignee
                ) VALUES
                    (
                        %s, %s, %s, 'serial_mismatch', 'case-mismatch-p02', 'open', 'S2',
                        'RULE-NAMEPLATE-MISMATCH',
                        '{"serial_expected": "21B3M0412", "serial_found": "21B3M9999", "location": "IN01-TWR-0042-T01-SA-L01-P02"}'::jsonb,
                        '{"ocr_confidence": 0.96, "spark_verified": true}'::jsonb,
                        14500.00, 'supervisor-01'
                    ),
                    (
                        %s, %s, %s, 'climb_violation', 'case-climb-ascent-01', 'open', 'S1',
                        'RULE-CLIMB-VELOCITY-MAX',
                        '{"technician": "tech-rahul-01", "structure": "IN01-TWR-0042", "speed_mps": 0.94}'::jsonb,
                        '{"elevation_m": 28.5, "speed_threshold": 0.8}'::jsonb,
                        50000.00, 'lead-safety-01'
                    )
                ON CONFLICT (id) DO NOTHING;
                """,
                (CASE_1_ID, TENANT_ID, SITE_1_ID,
                 CASE_2_ID, TENANT_ID, SITE_1_ID),
            )

            # 7. Asset 3D Model
            cur.execute(
                """
                INSERT INTO field.asset_model (
                    id, tenant_id, equipment_class, version, glb_storage_path, sha256_hash,
                    triangle_count, file_size_bytes, status, published_by, published_at
                ) VALUES (
                    %s, %s, 'RRU', '1.3.0',
                    'models/rru_model.glb', 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
                    142500, 18450000, 'published',
                    %s, %s
                ) ON CONFLICT (id) DO UPDATE SET status = 'published';
                """,
                (MODEL_ID, TENANT_ID, uuid.uuid5(uuid.NAMESPACE_DNS, "supervisor-01"), now),
            )

            # BOM parts
            bom_parts = [
                (str(uuid.uuid4()), MODEL_ID, TENANT_ID, "PN-RRU-01", "Chassis Base Shell", 1, False, None, "root/chassis", ["Node_Chassis"], 1, 0.0, -0.5, 0.0),
                (str(uuid.uuid4()), MODEL_ID, TENANT_ID, "PN-PA-B3", "RF Power Amplifier Module", 2, True, "PN-RRU-01", "root/chassis/pa", ["Node_PA_Board"], 2, -0.8, 0.0, 0.2),
                (str(uuid.uuid4()), MODEL_ID, TENANT_ID, "PN-DPX-03", "Filter Duplexer Unit", 1, True, "PN-RRU-01", "root/chassis/dpx", ["Node_Filter"], 3, 0.8, 0.0, 0.2),
                (str(uuid.uuid4()), MODEL_ID, TENANT_ID, "PN-BB-CTRL", "Digital Baseband Card", 1, True, "PN-RRU-01", "root/chassis/bb", ["Node_DSP"], 4, 0.0, 0.6, 0.1),
                (str(uuid.uuid4()), MODEL_ID, TENANT_ID, "PN-SINK-AL", "Solar Shield Heat Sink", 1, False, "PN-RRU-01", "root/chassis/sink", ["Node_Heatsink"], 5, 0.0, 0.0, 0.9),
                (str(uuid.uuid4()), MODEL_ID, TENANT_ID, "PN-SFP-10G", "Optical SFP+ Transceiver", 2, True, "PN-BB-CTRL", "root/chassis/bb/sfp", ["Node_Optics"], 6, -0.4, -0.4, -0.3),
            ]
            for bid, mid, tid, pn, desc, qty, ser, parent, path, nodes, bal, vx, vy, vz in bom_parts:
                cur.execute(
                    """
                    INSERT INTO field.asset_model_bom (
                        id, model_id, tenant_id, part_no, description,
                        qty, is_serialised, parent_part_no, node_path, node_names,
                        balloon_no, explode_vector_x, explode_vector_y, explode_vector_z
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING;
                    """,
                    (bid, mid, tid, pn, desc, qty, ser, parent, path, nodes, bal, vx, vy, vz),
                )

            conn.commit()
    print("Demo data seeded successfully!")


if __name__ == "__main__":
    seed_all()
