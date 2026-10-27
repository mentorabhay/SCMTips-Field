"""Serial Event and Equipment Table Migration with Forced RLS (Task T4.020, T4.022 / FR4.033, FR4.034).

Revision ID: field_0043
Revises: field_0042
Create Date: 2026-10-28
"""

from alembic import op

revision = "field_0043"
down_revision = "field_0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create field.equipment table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.equipment (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            erp_equipment_no text NULL,
            serial_no text NOT NULL,
            material text NOT NULL,
            part_no text NULL,
            equipment_class text NOT NULL DEFAULT 'UNKNOWN',
            asset_model_id uuid NULL,
            current_location_id uuid NULL REFERENCES field.location(id) ON DELETE SET NULL,
            status text NOT NULL DEFAULT 'installed' CHECK (status IN ('in_store', 'in_transit', 'installed', 'dismantled', 'scrapped', 'unknown')),
            erp_changed_at timestamptz NULL,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            updated_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_equipment_tenant_erp UNIQUE (tenant_id, erp_equipment_no),
            CONSTRAINT uq_equipment_tenant_mat_serial UNIQUE (tenant_id, material, serial_no)
        );

        CREATE INDEX IF NOT EXISTS idx_equipment_location
            ON field.equipment (tenant_id, current_location_id);
        CREATE INDEX IF NOT EXISTS idx_equipment_serial
            ON field.equipment (tenant_id, serial_no);

        ALTER TABLE field.equipment ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.equipment FORCE ROW LEVEL SECURITY;

        CREATE POLICY tenant_isolation ON field.equipment
            FOR ALL
            USING (tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), NULLIF(current_setting('app.current_tenant_id', true), ''))::uuid)
            WITH CHECK (tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), NULLIF(current_setting('app.current_tenant_id', true), ''))::uuid);
        """
    )

    # 2. Create field.serial_event table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.serial_event (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            equipment_id uuid NOT NULL REFERENCES field.equipment(id) ON DELETE CASCADE,
            serial_no text NOT NULL,
            seq bigint NOT NULL,
            type text NOT NULL CHECK (type IN ('issue', 'install', 'dismantle', 'move', 'return', 'audit_seen', 'reversal')),
            from_location_id uuid NULL REFERENCES field.location(id) ON DELETE SET NULL,
            to_location_id uuid NULL REFERENCES field.location(id) ON DELETE SET NULL,
            source_plant text NULL,
            source_storage_location text NULL,
            occurred_at timestamptz NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT NOW(),
            erp_document_id uuid NULL REFERENCES field.erp_document(id) ON DELETE SET NULL,
            reverses_event_id uuid NULL REFERENCES field.serial_event(id) ON DELETE SET NULL,
            capture_id uuid NULL REFERENCES field.capture(id) ON DELETE SET NULL,
            idempotency_key text NOT NULL,
            CONSTRAINT uq_serial_event_eq_seq UNIQUE (tenant_id, equipment_id, seq),
            CONSTRAINT uq_serial_event_idemp UNIQUE (tenant_id, idempotency_key)
        );

        CREATE INDEX IF NOT EXISTS idx_serial_event_history
            ON field.serial_event (tenant_id, serial_no, occurred_at, seq);
        CREATE INDEX IF NOT EXISTS idx_serial_event_to_loc
            ON field.serial_event (tenant_id, to_location_id);

        ALTER TABLE field.serial_event ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.serial_event FORCE ROW LEVEL SECURITY;

        CREATE POLICY tenant_isolation ON field.serial_event
            FOR ALL
            USING (tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), NULLIF(current_setting('app.current_tenant_id', true), ''))::uuid)
            WITH CHECK (tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), NULLIF(current_setting('app.current_tenant_id', true), ''))::uuid);

        CREATE OR REPLACE FUNCTION field.forbid_serial_event_modification()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'field.serial_event is append-only: updates and deletes are forbidden [FIELD-EVT-403-IMMUTABLE]';
        END;
        $$;

        DROP TRIGGER IF EXISTS trg_serial_event_no_modify ON field.serial_event;
        CREATE TRIGGER trg_serial_event_no_modify
            BEFORE UPDATE OR DELETE ON field.serial_event
            FOR EACH ROW EXECUTE FUNCTION field.forbid_serial_event_modification();
        """
    )

    # 3. Create field.installed_base view
    op.execute(
        """
        CREATE OR REPLACE VIEW field.installed_base WITH (security_invoker = true) AS
        SELECT
            e.tenant_id,
            e.serial_no,
            e.id AS equipment_id,
            e.erp_equipment_no,
            e.material,
            l.site_id,
            l.id AS location_id,
            l.sector_code,
            l.height_m AS level_height_m,
            l.fl_code AS erp_ref,
            COALESCE(se.occurred_at, e.created_at) AS since
        FROM field.equipment e
        LEFT JOIN field.location l ON e.current_location_id = l.id
        LEFT JOIN LATERAL (
            SELECT occurred_at FROM field.serial_event s
            WHERE s.tenant_id = e.tenant_id AND s.equipment_id = e.id AND s.type IN ('install', 'move', 'audit_seen')
            ORDER BY s.seq DESC LIMIT 1
        ) se ON true
        WHERE e.status = 'installed';
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS field.installed_base;")
    op.execute("DROP TRIGGER IF EXISTS trg_serial_event_no_modify ON field.serial_event;")
    op.execute("DROP FUNCTION IF EXISTS field.forbid_serial_event_modification();")
    op.execute("DROP TABLE IF EXISTS field.serial_event CASCADE;")
    op.execute("DROP TABLE IF EXISTS field.equipment CASCADE;")
