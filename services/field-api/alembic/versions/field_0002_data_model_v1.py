"""Data Model v1 with Forced RLS and Hierarchy Triggers (Tasks T1.025 - T1.028).

Revision ID: field_0002
Revises: field_0001
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0002"
down_revision = "field_0001"
branch_labels = None
depends_on = None

TABLES = [
    "site",
    "location",
    "material",
    "device",
    "task",
    "task_line",
    "capture",
    "erp_document",
    "posting_job",
    "outbox",
    "idempotency_record",
]

SITE_SCOPED_TABLES = [
    "site",
    "location",
    "task",
    "task_line",
    "capture",
    "erp_document",
]


def upgrade() -> None:
    # 1. field.site
    op.execute(
        """
        CREATE TABLE field.site (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            code text NOT NULL,
            name text NOT NULL,
            kind text NOT NULL CHECK (kind IN ('warehouse', 'tower', 'plant', 'yard', 'other')),
            erp_plant text NULL,
            erp_storage_locations text[] NOT NULL DEFAULT '{}',
            timezone text NOT NULL DEFAULT 'UTC',
            lat numeric(9,6) NULL,
            lon numeric(9,6) NULL,
            status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            updated_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_site_tenant_code UNIQUE (tenant_id, code),
            CONSTRAINT chk_site_code CHECK (code ~ '^[A-Z0-9-]{2,32}$')
        );
        CREATE TRIGGER trg_site_updated_at BEFORE UPDATE ON field.site FOR EACH ROW EXECUTE FUNCTION field.touch_updated_at();
    """
    )

    # 2. field.location
    op.execute(
        """
        CREATE TABLE field.location (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE RESTRICT,
            parent_id uuid NULL REFERENCES field.location(id) ON DELETE RESTRICT,
            kind text NOT NULL CHECK (kind IN ('zone', 'aisle', 'rack', 'level', 'position', 'tower', 'sector')),
            code text NOT NULL,
            path text NOT NULL,
            depth smallint NOT NULL CHECK (depth BETWEEN 1 AND 6),
            erp_ref text NULL,
            erp_ref_type text NULL CHECK (erp_ref_type IS NULL OR erp_ref_type IN ('storage_bin', 'functional_location')),
            status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            updated_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_location_tenant_site_path UNIQUE (tenant_id, site_id, path),
            CONSTRAINT chk_location_code CHECK (code ~ '^[A-Z0-9-]{1,24}$')
        );
        CREATE TRIGGER trg_location_updated_at BEFORE UPDATE ON field.location FOR EACH ROW EXECUTE FUNCTION field.touch_updated_at();
    """
    )

    # 3. Location hierarchy validation trigger function
    op.execute(
        """
        CREATE OR REPLACE FUNCTION field.location_validate()
        RETURNS TRIGGER AS $$
        DECLARE
            v_curr uuid;
            v_depth smallint := 1;
        BEGIN
            -- Validate parent site matches
            IF NEW.parent_id IS NOT NULL THEN
                IF (SELECT site_id FROM field.location WHERE id = NEW.parent_id) != NEW.site_id THEN
                    RAISE EXCEPTION 'Parent location must belong to identical site';
                END IF;
            END IF;

            -- Validate no cycles
            v_curr := NEW.parent_id;
            WHILE v_curr IS NOT NULL LOOP
                IF v_curr = NEW.id THEN
                    RAISE EXCEPTION 'FIELD-LOC-422-CYCLE: Location hierarchy cannot contain cycles';
                END IF;
                SELECT parent_id INTO v_curr FROM field.location WHERE id = v_curr;
                v_depth := v_depth + 1;
                IF v_depth > 6 THEN
                    RAISE EXCEPTION 'FIELD-LOC-422-MAX-DEPTH: Location hierarchy depth cannot exceed 6';
                END IF;
            END LOOP;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_location_validate BEFORE INSERT OR UPDATE OF parent_id ON field.location FOR EACH ROW EXECUTE FUNCTION field.location_validate();
    """
    )

    # 4. field.material
    op.execute(
        """
        CREATE TABLE field.material (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            erp_material_no text NOT NULL,
            plant text NOT NULL,
            description text NOT NULL,
            base_uom text NOT NULL,
            batch_managed boolean NOT NULL DEFAULT false,
            serial_profile text NULL,
            gtin text NULL,
            source text NOT NULL DEFAULT 'erp_sync',
            deleted_in_erp_at timestamptz NULL,
            status text NOT NULL DEFAULT 'active',
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            updated_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_material_tenant_plant_mat UNIQUE (tenant_id, plant, erp_material_no)
        );
        CREATE TRIGGER trg_material_updated_at BEFORE UPDATE ON field.material FOR EACH ROW EXECUTE FUNCTION field.touch_updated_at();
    """
    )

    # 5. field.device
    op.execute(
        """
        CREATE TABLE field.device (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            kind text NOT NULL CHECK (kind IN ('phone', 'glasses')),
            serial_no text NOT NULL,
            model text NOT NULL,
            os_version text NULL,
            app_version text NULL,
            status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked', 'lost')),
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            updated_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_device_tenant_serial UNIQUE (tenant_id, serial_no)
        );
        CREATE TRIGGER trg_device_updated_at BEFORE UPDATE ON field.device FOR EACH ROW EXECUTE FUNCTION field.touch_updated_at();
    """
    )

    # 6. field.task
    op.execute(
        """
        CREATE TABLE field.task (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE RESTRICT,
            type text NOT NULL,
            status text NOT NULL DEFAULT 'pending',
            priority text NOT NULL DEFAULT 'medium',
            title text NOT NULL,
            assigned_to text NULL,
            due_at timestamptz NULL,
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            updated_at timestamptz NOT NULL DEFAULT NOW()
        );
        CREATE TRIGGER trg_task_updated_at BEFORE UPDATE ON field.task FOR EACH ROW EXECUTE FUNCTION field.touch_updated_at();
    """
    )

    # 7. field.task_line
    op.execute(
        """
        CREATE TABLE field.task_line (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE RESTRICT,
            task_id uuid NOT NULL REFERENCES field.task(id) ON DELETE CASCADE,
            line_no integer NOT NULL,
            material_id uuid NULL REFERENCES field.material(id),
            expected_qty numeric(12,3) NOT NULL DEFAULT 0,
            uom text NOT NULL DEFAULT 'EA',
            captured_qty numeric(12,3) NOT NULL DEFAULT 0,
            status text NOT NULL DEFAULT 'pending',
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            updated_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_task_line_task_line_no UNIQUE (tenant_id, task_id, line_no)
        );
        CREATE TRIGGER trg_task_line_updated_at BEFORE UPDATE ON field.task_line FOR EACH ROW EXECUTE FUNCTION field.touch_updated_at();
    """
    )

    # 8. field.capture
    op.execute(
        """
        CREATE TABLE field.capture (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE RESTRICT,
            device_id uuid NULL REFERENCES field.device(id),
            task_id uuid NULL REFERENCES field.task(id),
            is_probe boolean NOT NULL DEFAULT false,
            raw_text text NULL,
            parsed_data jsonb NOT NULL DEFAULT '{}'::jsonb,
            confidence numeric(4,3) NOT NULL DEFAULT 1.000,
            status text NOT NULL DEFAULT 'verified',
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT NOW()
        );
    """
    )

    # 9. field.erp_document
    op.execute(
        """
        CREATE TABLE field.erp_document (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE RESTRICT,
            doc_type text NOT NULL,
            doc_number text NOT NULL,
            fiscal_year text NOT NULL,
            movement_type text NOT NULL,
            reversal_of_id uuid NULL REFERENCES field.erp_document(id),
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            status text NOT NULL DEFAULT 'posted',
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            updated_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_erp_doc_tenant_num_year UNIQUE (tenant_id, doc_number, fiscal_year)
        );
        CREATE TRIGGER trg_erp_doc_updated_at BEFORE UPDATE ON field.erp_document FOR EACH ROW EXECUTE FUNCTION field.touch_updated_at();
    """
    )

    # 10. field.posting_job
    op.execute(
        """
        CREATE TABLE field.posting_job (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            erp_doc_id uuid NULL REFERENCES field.erp_document(id),
            queue_key text NOT NULL,
            status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed')),
            attempts integer NOT NULL DEFAULT 0,
            next_attempt_at timestamptz NOT NULL DEFAULT NOW(),
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            updated_at timestamptz NOT NULL DEFAULT NOW()
        );
        CREATE INDEX idx_posting_job_queue ON field.posting_job (queue_key, status, next_attempt_at);
    """
    )

    # 11. field.outbox
    op.execute(
        """
        CREATE TABLE field.outbox (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            event_type text NOT NULL,
            aggregate_id uuid NOT NULL,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            published_at timestamptz NULL,
            created_at timestamptz NOT NULL DEFAULT NOW()
        );
        CREATE INDEX idx_outbox_unpublished ON field.outbox (published_at) WHERE published_at IS NULL;
    """
    )

    # 12. field.idempotency_record
    op.execute(
        """
        CREATE TABLE field.idempotency_record (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            idempotency_key text NOT NULL,
            fingerprint text NOT NULL,
            status text NOT NULL CHECK (status IN ('in_progress', 'completed')),
            status_code integer NULL,
            headers jsonb NOT NULL DEFAULT '{}'::jsonb,
            body bytea NULL,
            media_type text NULL,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_idempotency_tenant_key UNIQUE (tenant_id, idempotency_key)
        );
        CREATE INDEX idx_idempotency_created ON field.idempotency_record (created_at);
    """
    )

    # 13. Apply FORCED Row Level Security (RLS) on all tables (Task T1.026)
    for tbl in TABLES:
        op.execute(f"ALTER TABLE field.{tbl} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE field.{tbl} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON field.{tbl}
            AS RESTRICTIVE
            FOR ALL
            USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
        """
        )

    # 14. Apply Site Data Scope Policies (Task T1.027)
    for tbl in SITE_SCOPED_TABLES:
        site_col = "id" if tbl == "site" else "site_id"
        op.execute(
            f"""
            CREATE POLICY site_scope ON field.{tbl}
            FOR ALL
            USING (
                nullif(current_setting('app.site_ids', true), '') = '*'
                OR {site_col}::text = ANY(string_to_array(nullif(current_setting('app.site_ids', true), ''), ','))
            );
        """
        )

    # 15. Role grants: field_app & field_worker (T1.024 / T1.025 - no DELETE on erp_document)
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'field_app') THEN
                GRANT USAGE ON SCHEMA field TO field_app, field_worker;
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA field TO field_app, field_worker;
                REVOKE DELETE ON field.erp_document FROM field_app, field_worker;
            END IF;
        END $$;
    """
    )


def downgrade() -> None:
    for tbl in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS field.{tbl} CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS field.location_validate() CASCADE;")
