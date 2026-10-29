"""Baseline Migration for Simulated ERP (Tasks T1.041 - T1.044 / T1.051 - T1.053).

Revision ID: erpsim_0001
Revises:
Create Date: 2026-10-27
"""

from alembic import op

revision = "erpsim_0001"
down_revision = None
branch_labels = None
depends_on = None

TABLES = [
    "plant",
    "storage_location",
    "material",
    "functional_location",
    "number_range",
    "enqueue_lock",
    "dedupe",
    "stock",
    "document",
    "document_item",
    "inbound_delivery",
    "inbound_delivery_item",
    "outbound_delivery",
    "outbound_delivery_item",
    "physical_inventory_doc",
    "physical_inventory_item",
    "equipment",
    "equipment_install",
    "fault_rule",
]


def upgrade() -> None:
    # Extensions and schema
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute("CREATE SCHEMA IF NOT EXISTS erpsim")

    # 1. Master Tables
    op.execute(
        """
        CREATE TABLE erpsim.plant (
            client text NOT NULL DEFAULT '100',
            plant text NOT NULL,
            name text NOT NULL,
            PRIMARY KEY (client, plant)
        );

        CREATE TABLE erpsim.storage_location (
            client text NOT NULL DEFAULT '100',
            plant text NOT NULL,
            storage_location text NOT NULL,
            name text NOT NULL,
            PRIMARY KEY (client, plant, storage_location)
        );

        CREATE TABLE erpsim.material (
            client text NOT NULL DEFAULT '100',
            material_no text NOT NULL,
            description text NOT NULL,
            base_uom text NOT NULL DEFAULT 'EA',
            PRIMARY KEY (client, material_no)
        );

        CREATE TABLE erpsim.functional_location (
            client text NOT NULL DEFAULT '100',
            func_loc text NOT NULL,
            description text NOT NULL,
            PRIMARY KEY (client, func_loc)
        );
    """
    )

    # 2. Number Range (T1.043)
    op.execute(
        """
        CREATE TABLE erpsim.number_range (
            client text NOT NULL DEFAULT '100',
            object text NOT NULL,
            current bigint NOT NULL,
            lower bigint NOT NULL,
            upper bigint NOT NULL,
            PRIMARY KEY (client, object)
        );
    """
    )

    # 3. Enqueue Lock (T1.044)
    op.execute(
        """
        CREATE TABLE erpsim.enqueue_lock (
            client text NOT NULL DEFAULT '100',
            object_type text NOT NULL,
            object_key text NOT NULL,
            session_id text NOT NULL,
            acquired_at timestamptz NOT NULL DEFAULT NOW(),
            expires_at timestamptz NOT NULL,
            PRIMARY KEY (client, object_type, object_key)
        );
    """
    )

    # 4. Dedupe Store (T1.051)
    op.execute(
        """
        CREATE TABLE erpsim.dedupe (
            client text NOT NULL DEFAULT '100',
            idem_key text NOT NULL,
            request_hash text NOT NULL,
            document_no text NOT NULL,
            fiscal_year text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            PRIMARY KEY (client, idem_key)
        );
    """
    )

    # 5. Inventory Stock (PR1.07)
    op.execute(
        """
        CREATE TABLE erpsim.stock (
            client text NOT NULL DEFAULT '100',
            plant text NOT NULL,
            storage_location text NOT NULL,
            material_no text NOT NULL,
            quantity numeric(12,3) NOT NULL DEFAULT 0.000,
            uom text NOT NULL DEFAULT 'EA',
            updated_at timestamptz NOT NULL DEFAULT NOW(),
            PRIMARY KEY (client, plant, storage_location, material_no)
        );
    """
    )

    # 6. Material Document Header & Items (T1.048)
    op.execute(
        """
        CREATE TABLE erpsim.document (
            client text NOT NULL DEFAULT '100',
            doc_number text NOT NULL,
            fiscal_year text NOT NULL,
            doc_type text NOT NULL,
            movement_type text NOT NULL,
            reversal_of text NULL,
            header_data jsonb NOT NULL DEFAULT '{}'::jsonb,
            status text NOT NULL DEFAULT 'posted',
            created_at timestamptz NOT NULL DEFAULT NOW(),
            PRIMARY KEY (client, doc_number, fiscal_year)
        );

        CREATE TABLE erpsim.document_item (
            client text NOT NULL DEFAULT '100',
            doc_number text NOT NULL,
            fiscal_year text NOT NULL,
            line_no integer NOT NULL,
            material_no text NOT NULL,
            plant text NOT NULL,
            storage_location text NOT NULL,
            quantity numeric(12,3) NOT NULL,
            uom text NOT NULL DEFAULT 'EA',
            movement_type text NOT NULL,
            item_data jsonb NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (client, doc_number, fiscal_year, line_no),
            CONSTRAINT fk_item_doc FOREIGN KEY (client, doc_number, fiscal_year)
                REFERENCES erpsim.document (client, doc_number, fiscal_year) ON DELETE CASCADE
        );
    """
    )

    # 7. Deliveries (T1.045 & T1.046)
    op.execute(
        """
        CREATE TABLE erpsim.inbound_delivery (
            client text NOT NULL DEFAULT '100',
            delivery_document text NOT NULL,
            plant text NOT NULL,
            storage_location text NOT NULL,
            status text NOT NULL DEFAULT 'open',
            header_data jsonb NOT NULL DEFAULT '{}'::jsonb,
            last_change_date_time timestamptz NOT NULL DEFAULT NOW(),
            created_at timestamptz NOT NULL DEFAULT NOW(),
            PRIMARY KEY (client, delivery_document)
        );

        CREATE TABLE erpsim.inbound_delivery_item (
            client text NOT NULL DEFAULT '100',
            delivery_document text NOT NULL,
            item_no text NOT NULL,
            material_no text NOT NULL,
            delivery_qty numeric(12,3) NOT NULL,
            actual_qty numeric(12,3) NOT NULL DEFAULT 0.000,
            uom text NOT NULL DEFAULT 'EA',
            status text NOT NULL DEFAULT 'open',
            PRIMARY KEY (client, delivery_document, item_no),
            CONSTRAINT fk_ibd_item FOREIGN KEY (client, delivery_document)
                REFERENCES erpsim.inbound_delivery (client, delivery_document) ON DELETE CASCADE
        );

        CREATE TABLE erpsim.outbound_delivery (
            client text NOT NULL DEFAULT '100',
            delivery_document text NOT NULL,
            plant text NOT NULL,
            storage_location text NOT NULL,
            status text NOT NULL DEFAULT 'open',
            header_data jsonb NOT NULL DEFAULT '{}'::jsonb,
            last_change_date_time timestamptz NOT NULL DEFAULT NOW(),
            created_at timestamptz NOT NULL DEFAULT NOW(),
            PRIMARY KEY (client, delivery_document)
        );

        CREATE TABLE erpsim.outbound_delivery_item (
            client text NOT NULL DEFAULT '100',
            delivery_document text NOT NULL,
            item_no text NOT NULL,
            material_no text NOT NULL,
            delivery_qty numeric(12,3) NOT NULL,
            picked_qty numeric(12,3) NOT NULL DEFAULT 0.000,
            uom text NOT NULL DEFAULT 'EA',
            status text NOT NULL DEFAULT 'open',
            PRIMARY KEY (client, delivery_document, item_no),
            CONSTRAINT fk_obd_item FOREIGN KEY (client, delivery_document)
                REFERENCES erpsim.outbound_delivery (client, delivery_document) ON DELETE CASCADE
        );
    """
    )

    # 8. Physical Inventory (T1.047)
    op.execute(
        """
        CREATE TABLE erpsim.physical_inventory_doc (
            client text NOT NULL DEFAULT '100',
            pi_document text NOT NULL,
            fiscal_year text NOT NULL,
            plant text NOT NULL,
            storage_location text NOT NULL,
            status text NOT NULL DEFAULT 'created',
            created_at timestamptz NOT NULL DEFAULT NOW(),
            PRIMARY KEY (client, pi_document, fiscal_year)
        );

        CREATE TABLE erpsim.physical_inventory_item (
            client text NOT NULL DEFAULT '100',
            pi_document text NOT NULL,
            fiscal_year text NOT NULL,
            line_no integer NOT NULL,
            material_no text NOT NULL,
            book_qty numeric(12,3) NOT NULL,
            counted_qty numeric(12,3) NULL,
            uom text NOT NULL DEFAULT 'EA',
            status text NOT NULL DEFAULT 'created',
            PRIMARY KEY (client, pi_document, fiscal_year, line_no),
            CONSTRAINT fk_pi_item FOREIGN KEY (client, pi_document, fiscal_year)
                REFERENCES erpsim.physical_inventory_doc (client, pi_document, fiscal_year) ON DELETE CASCADE
        );
    """
    )

    # 9. Equipment & Plant Maintenance (T1.049 / T1.050)
    op.execute(
        """
        CREATE TABLE erpsim.equipment (
            client text NOT NULL DEFAULT '100',
            equipment_no text NOT NULL,
            material_no text NOT NULL,
            serial_no text NOT NULL,
            func_loc text NULL,
            status text NOT NULL DEFAULT 'available',
            created_at timestamptz NOT NULL DEFAULT NOW(),
            PRIMARY KEY (client, equipment_no)
        );

        CREATE TABLE erpsim.equipment_install (
            client text NOT NULL DEFAULT '100',
            install_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            equipment_no text NOT NULL,
            func_loc text NOT NULL,
            action text NOT NULL CHECK (action IN ('install', 'dismantle')),
            timestamp timestamptz NOT NULL DEFAULT NOW()
        );
    """
    )

    # 10. Fault Rules Engine (T1.052)
    op.execute(
        """
        CREATE TABLE erpsim.fault_rule (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            client text NOT NULL DEFAULT '100',
            kind text NOT NULL CHECK (kind IN ('latency', 'http_5xx', 'lock', 'timeout', 'partial')),
            service text NULL,
            operation text NULL,
            doc_key text NULL,
            probability numeric(4,3) NOT NULL DEFAULT 1.000,
            count integer NOT NULL DEFAULT 1,
            ttl_s integer NOT NULL DEFAULT 300,
            seed integer NULL,
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT NOW()
        );
    """
    )

    # 11. Initial Number Ranges
    op.execute(
        """
        INSERT INTO erpsim.number_range (client, object, current, lower, upper) VALUES
        ('100', 'MATERIAL_DOCUMENT', 4900000100, 4900000000, 4999999999),
        ('100', 'INBOUND_DELIVERY', 180000010, 180000000, 189999999),
        ('100', 'OUTBOUND_DELIVERY', 80000010, 80000000, 89999999),
        ('100', 'PI_DOCUMENT', 100000000, 100000000, 109999999),
        ('100', 'EQUIPMENT', 10000000, 10000000, 19999999),
        ('100', 'MAINT_ORDER', 4100000000, 4100000000, 4199999999),
        ('100', 'MAINT_NOTIF', 10000000, 10000000, 19999999),
        ('100', 'MEASUREMENT_DOC', 330000000, 330000000, 339999999)
        ON CONFLICT DO NOTHING;
    """
    )


def downgrade() -> None:
    for tbl in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS erpsim.{tbl} CASCADE;")
