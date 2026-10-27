"""Trail Point Table Migration with Forced RLS (Task T3.002 / FR3.065).

Revision ID: field_0037
Revises: field_0036
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0037"
down_revision = "field_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.trail_point (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            device_id uuid NOT NULL REFERENCES field.device(id) ON DELETE CASCADE,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE CASCADE,
            x_m numeric(8,3) NOT NULL,
            y_m numeric(8,3) NOT NULL,
            z_m numeric(8,3) NOT NULL DEFAULT 0.000,
            speed_mps numeric(5,2) NOT NULL DEFAULT 0.00,
            in_forklift_zone boolean NOT NULL DEFAULT false,
            timestamp timestamptz NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_trail_device_time
            ON field.trail_point (tenant_id, device_id, timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_trail_site_time
            ON field.trail_point (tenant_id, site_id, timestamp DESC);

        ALTER TABLE field.trail_point ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.trail_point FORCE ROW LEVEL SECURITY;

        CREATE POLICY tenant_isolation ON field.trail_point
        AS RESTRICTIVE FOR ALL
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS field.trail_point CASCADE;
        """
    )
