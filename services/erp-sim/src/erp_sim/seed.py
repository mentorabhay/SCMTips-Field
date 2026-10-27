"""ERP Sim Deterministic SAMPLE Data Seeder (Task T1.053).

Loads:
- Plant 1010
- Storage locations 101A (Unrestricted) and 101Q (Quality Inspection)
- 50 materials SAMPLE-MAT-0001..0050
- Initial stock for each material
- 20 open inbound deliveries (180000001..180000020)
- 10 outbound deliveries (80000001..80000010)
- 5 functional locations SAMPLE-TWR-0001..0005
- 12 equipment items
"""

import argparse
import json

from erp_sim.db import get_conn


def seed_sample_data(client: str = "100") -> dict[str, int]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            # 1. Plants
            cur.execute(
                """
                INSERT INTO erpsim.plant (client, plant, name)
                VALUES (%s, '1010', 'Main Production & Distribution Facility')
                ON CONFLICT (client, plant) DO NOTHING;
            """,
                (client,),
            )

            # 2. Storage Locations
            cur.execute(
                """
                INSERT INTO erpsim.storage_location (client, plant, storage_location, name)
                VALUES
                    (%s, '1010', '101A', 'Unrestricted Central Stock'),
                    (%s, '1010', '101Q', 'Quality Inspection Holding')
                ON CONFLICT (client, plant, storage_location) DO NOTHING;
            """,
                (client, client),
            )

            # 3. 50 Materials & Stock
            for i in range(1, 51):
                mat_no = f"SAMPLE-MAT-{i:04d}"
                desc = f"Industrial Component Grade {i}"
                cur.execute(
                    """
                    INSERT INTO erpsim.material (client, material_no, description, base_uom)
                    VALUES (%s, %s, %s, 'EA')
                    ON CONFLICT (client, material_no) DO NOTHING;
                """,
                    (client, mat_no, desc),
                )

                # Seed stock: 100.000 EA in 101A
                cur.execute(
                    """
                    INSERT INTO erpsim.stock (client, plant, storage_location, material_no, quantity, uom)
                    VALUES (%s, '1010', '101A', %s, 100.000, 'EA')
                    ON CONFLICT (client, plant, storage_location, material_no)
                    DO UPDATE SET quantity = 100.000;
                """,
                    (client, mat_no),
                )

            # 4. Functional Locations (5 towers)
            for t in range(1, 6):
                floc = f"SAMPLE-TWR-{t:04d}"
                cur.execute(
                    """
                    INSERT INTO erpsim.functional_location (client, func_loc, description)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (client, func_loc) DO NOTHING;
                """,
                    (client, floc, f"Transmission Tower Sector Site {t}"),
                )

            # 5. Inbound Deliveries (20)
            for d in range(1, 21):
                ibd_no = f"1800000{d:02d}"
                cur.execute(
                    """
                    INSERT INTO erpsim.inbound_delivery (client, delivery_document, plant, storage_location, status, header_data)
                    VALUES (%s, %s, '1010', '101A', 'open', %s)
                    ON CONFLICT (client, delivery_document) DO NOTHING;
                """,
                    (client, ibd_no, json.dumps({"Vendor": "SAMPLE-VENDOR-01"})),
                )

                # 2 items per inbound delivery
                mat_1 = f"SAMPLE-MAT-{(d * 2 - 1):04d}"
                mat_2 = f"SAMPLE-MAT-{(d * 2):04d}"
                cur.execute(
                    """
                    INSERT INTO erpsim.inbound_delivery_item (client, delivery_document, item_no, material_no, delivery_qty, actual_qty, uom, status)
                    VALUES
                        (%s, %s, '000010', %s, 24.000, 0.000, 'EA', 'open'),
                        (%s, %s, '000020', %s, 12.000, 0.000, 'EA', 'open')
                    ON CONFLICT (client, delivery_document, item_no) DO NOTHING;
                """,
                    (client, ibd_no, mat_1, client, ibd_no, mat_2),
                )

            # 6. Outbound Deliveries (10)
            for o in range(1, 11):
                obd_no = f"800000{o:02d}"
                cur.execute(
                    """
                    INSERT INTO erpsim.outbound_delivery (client, delivery_document, plant, storage_location, status, header_data)
                    VALUES (%s, %s, '1010', '101A', 'open', %s)
                    ON CONFLICT (client, delivery_document) DO NOTHING;
                """,
                    (client, obd_no, json.dumps({"ShipTo": "SAMPLE-CUSTOMER-01"})),
                )
                mat_o = f"SAMPLE-MAT-{o:04d}"
                cur.execute(
                    """
                    INSERT INTO erpsim.outbound_delivery_item (client, delivery_document, item_no, material_no, delivery_qty, picked_qty, uom, status)
                    VALUES (%s, %s, '000010', %s, 5.000, 0.000, 'EA', 'open')
                    ON CONFLICT (client, delivery_document, item_no) DO NOTHING;
                """,
                    (client, obd_no, mat_o),
                )

            # 7. Equipment (12)
            for e in range(1, 13):
                eq_no = f"100000{e:02d}"
                mat_e = f"SAMPLE-MAT-{((e - 1) % 10 + 1):04d}"
                floc_e = f"SAMPLE-TWR-{((e - 1) % 5 + 1):04d}" if e <= 8 else None
                cur.execute(
                    """
                    INSERT INTO erpsim.equipment (client, equipment_no, material_no, serial_no, func_loc, status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (client, equipment_no) DO NOTHING;
                """,
                    (
                        client,
                        eq_no,
                        mat_e,
                        f"SN-SAMPLE-{e:04d}",
                        floc_e,
                        "installed" if floc_e else "available",
                    ),
                )

            conn.commit()

    return {"materials": 50, "inbound_deliveries": 20, "outbound_deliveries": 10, "equipment": 12}


def reset_database(client: str = "100") -> None:
    """Truncate transactional tables and reseed deterministically."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
                TRUNCATE TABLE
                    erpsim.dedupe,
                    erpsim.enqueue_lock,
                    erpsim.document_item,
                    erpsim.document,
                    erpsim.inbound_delivery_item,
                    erpsim.inbound_delivery,
                    erpsim.outbound_delivery_item,
                    erpsim.outbound_delivery,
                    erpsim.physical_inventory_item,
                    erpsim.physical_inventory_doc,
                    erpsim.equipment_install,
                    erpsim.equipment,
                    erpsim.stock,
                    erpsim.material,
                    erpsim.storage_location,
                    erpsim.plant,
                    erpsim.functional_location,
                    erpsim.fault_rule
                CASCADE;
            """
        )
        # Reset number range current values
        cur.execute(
            """
                UPDATE erpsim.number_range
                SET current = lower
                WHERE client = %s;
            """,
            (client,),
        )
        conn.commit()

    seed_sample_data(client)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed ERP Sim")
    parser.add_argument("--profile", default="sample", help="Profile to seed")
    parser.add_argument("--reset", action="store_true", help="Reset before seeding")
    args = parser.parse_args()

    if args.reset:
        reset_database()
        print("ERP Sim reset and seeded cleanly.")
    else:
        counts = seed_sample_data()
        print(f"ERP Sim seeded: {counts}")
