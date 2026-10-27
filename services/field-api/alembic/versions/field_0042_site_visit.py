"""Phase 4 Site Visit & Geofence Migration (Task T4.001 / FR4.009, FR4.010, FR4.011, FR4.012).

Revision ID: field_0042
Revises: field_0041
Create Date: 2026-10-28
"""

from alembic import op

revision = "field_0042"
down_revision = "field_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add geofence columns to field.site
    op.execute(
        """
        ALTER TABLE field.site
            ADD COLUMN IF NOT EXISTS geofence_radius_m integer NOT NULL DEFAULT 150;
        """
    )

    # 2. Create field.site_visit table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.site_visit (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE CASCADE,
            user_id uuid NOT NULL,
            device_id uuid NULL REFERENCES field.device(id) ON DELETE SET NULL,
            permit_ref text NOT NULL CHECK (length(permit_ref) BETWEEN 4 AND 40),
            permit_valid_until timestamptz NOT NULL,
            checkin_at timestamptz NOT NULL DEFAULT NOW(),
            checkin_lat numeric(9, 6) NOT NULL,
            checkin_lon numeric(9, 6) NOT NULL,
            checkin_accuracy_m numeric(6, 1) NOT NULL,
            override_by uuid NULL,
            override_reason text NULL,
            baro_baseline_hpa numeric(7, 2) NULL,
            timer_interval_min integer NOT NULL DEFAULT 20,
            last_heartbeat_at timestamptz NOT NULL DEFAULT NOW(),
            status text NOT NULL DEFAULT 'checked_in' CHECK (status IN (
                'checked_in', 'on_structure', 'overdue', 'escalated', 'checked_out'
            )),
            checkout_at timestamptz NULL,
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            updated_at timestamptz NOT NULL DEFAULT NOW()
        );

        CREATE TRIGGER trg_site_visit_updated_at
            BEFORE UPDATE ON field.site_visit
            FOR EACH ROW EXECUTE FUNCTION field.touch_updated_at();

        CREATE INDEX IF NOT EXISTS idx_site_visit_heartbeat
            ON field.site_visit (tenant_id, status, last_heartbeat_at);

        CREATE INDEX IF NOT EXISTS idx_site_visit_site_checkin
            ON field.site_visit (tenant_id, site_id, checkin_at DESC);

        ALTER TABLE field.site_visit ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.site_visit FORCE ROW LEVEL SECURITY;

        CREATE POLICY tenant_isolation ON field.site_visit
            AS RESTRICTIVE
            USING (tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), NULLIF(current_setting('app.current_tenant_id', true), ''))::uuid)
            WITH CHECK (tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), NULLIF(current_setting('app.current_tenant_id', true), ''))::uuid);

        CREATE POLICY allow_all ON field.site_visit
            FOR ALL
            USING (true)
            WITH CHECK (true);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS field.site_visit CASCADE;

        ALTER TABLE field.site
            DROP COLUMN IF EXISTS geofence_radius_m;
        """
    )
