"""Phase 4 Tower Locations & FL Import Job Migration (Task T4.001 / FR4.001, FR4.002, FR4.003, FR4.004).

Revision ID: field_0041
Revises: field_0039
Create Date: 2026-10-28
"""

from alembic import op

revision = "field_0041"
down_revision = "field_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Update location kinds and depth checks to support tower locations
    op.execute(
        """
        ALTER TABLE field.location DROP CONSTRAINT IF EXISTS location_kind_check;
        ALTER TABLE field.location DROP CONSTRAINT IF EXISTS chk_location_kind;
        ALTER TABLE field.location
            ADD CONSTRAINT chk_location_kind
            CHECK (kind IN (
                'zone', 'aisle', 'rack', 'level', 'position', 'tower', 'sector',
                'tower_site', 'shelter', 'rack_slot'
            ));

        ALTER TABLE field.location DROP CONSTRAINT IF EXISTS location_depth_check;
        ALTER TABLE field.location DROP CONSTRAINT IF EXISTS chk_location_depth;
        ALTER TABLE field.location
            ADD CONSTRAINT chk_location_depth
            CHECK (depth BETWEEN 1 AND 8);

        -- Add Phase 4 columns to location
        ALTER TABLE field.location
            ADD COLUMN IF NOT EXISTS height_m numeric(6, 2) NULL,
            ADD COLUMN IF NOT EXISTS sector_code text NULL CHECK (sector_code IS NULL OR sector_code IN ('A', 'B', 'C', 'D')),
            ADD COLUMN IF NOT EXISTS fl_code text NULL;

        CREATE INDEX IF NOT EXISTS idx_location_fl_code
            ON field.location (tenant_id, fl_code);

        CREATE INDEX IF NOT EXISTS idx_location_height
            ON field.location (tenant_id, site_id, height_m);

        CREATE UNIQUE INDEX IF NOT EXISTS uq_location_tenant_erp_ref
            ON field.location (tenant_id, erp_ref)
            WHERE erp_ref IS NOT NULL;
        """
    )

    # 2. Create field.fl_import_job table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.fl_import_job (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            connection_id uuid NOT NULL DEFAULT field.uuid_generate_v7(),
            filter_prefix text NOT NULL,
            mode text NOT NULL DEFAULT 'full' CHECK (mode IN ('full', 'delta')),
            watermark_from timestamptz NULL,
            status text NOT NULL DEFAULT 'staging' CHECK (status IN ('staging', 'preview', 'applying', 'applied', 'discarded', 'failed')),
            counts jsonb NOT NULL DEFAULT '{"new": 0, "changed": 0, "moved": 0, "removed": 0, "rejected": 0}'::jsonb,
            rejected_rows jsonb NOT NULL DEFAULT '[]'::jsonb,
            staging_data jsonb NOT NULL DEFAULT '[]'::jsonb,
            diff_preview jsonb NOT NULL DEFAULT '{}'::jsonb,
            applied_at timestamptz NULL,
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            updated_at timestamptz NOT NULL DEFAULT NOW()
        );

        CREATE TRIGGER trg_fl_import_job_updated_at
            BEFORE UPDATE ON field.fl_import_job
            FOR EACH ROW EXECUTE FUNCTION field.touch_updated_at();

        CREATE INDEX IF NOT EXISTS idx_fl_import_job_tenant_status
            ON field.fl_import_job (tenant_id, status, created_at DESC);

        ALTER TABLE field.fl_import_job ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.fl_import_job FORCE ROW LEVEL SECURITY;

        CREATE POLICY tenant_isolation ON field.fl_import_job
            AS RESTRICTIVE
            USING (tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), NULLIF(current_setting('app.current_tenant_id', true), ''))::uuid)
            WITH CHECK (tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), NULLIF(current_setting('app.current_tenant_id', true), ''))::uuid);

        CREATE POLICY allow_all ON field.fl_import_job
            FOR ALL
            USING (true)
            WITH CHECK (true);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS field.fl_import_job CASCADE;

        DROP INDEX IF EXISTS field.uq_location_tenant_erp_ref;
        DROP INDEX IF EXISTS field.idx_location_height;
        DROP INDEX IF EXISTS field.idx_location_fl_code;

        ALTER TABLE field.location
            DROP COLUMN IF EXISTS fl_code,
            DROP COLUMN IF EXISTS sector_code,
            DROP COLUMN IF EXISTS height_m;

        ALTER TABLE field.location DROP CONSTRAINT IF EXISTS chk_location_kind;
        ALTER TABLE field.location
            ADD CONSTRAINT chk_location_kind
            CHECK (kind IN ('zone', 'aisle', 'rack', 'level', 'position', 'tower', 'sector'));

        ALTER TABLE field.location DROP CONSTRAINT IF EXISTS chk_location_depth;
        ALTER TABLE field.location
            ADD CONSTRAINT chk_location_depth
            CHECK (depth BETWEEN 1 AND 6);
        """
    )
