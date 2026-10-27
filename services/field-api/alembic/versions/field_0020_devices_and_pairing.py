"""Device Extensions and Glasses Pairing Migration (Task T2.046 / FR2.003, FR2.054).

Revision ID: field_0020
Revises: field_0003
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0020"
down_revision = "field_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Extend field.device table
    op.execute(
        """
        ALTER TABLE field.device
            ADD COLUMN IF NOT EXISTS firmware_version text NULL,
            ADD COLUMN IF NOT EXISTS paired_with uuid NULL REFERENCES field.device(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS battery_pct integer NULL CHECK (battery_pct >= 0 AND battery_pct <= 100),
            ADD COLUMN IF NOT EXISTS thermal_status text NULL,
            ADD COLUMN IF NOT EXISTS queue_depth integer NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS glasses_state text NULL,
            ADD COLUMN IF NOT EXISTS last_seen_at timestamptz NULL,
            ADD COLUMN IF NOT EXISTS revoked_at timestamptz NULL,
            ADD COLUMN IF NOT EXISTS config_version integer NOT NULL DEFAULT 1;
        """
    )

    # 2. Create field.device_pairing table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.device_pairing (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            phone_id uuid NOT NULL REFERENCES field.device(id) ON DELETE CASCADE,
            glasses_id uuid NOT NULL REFERENCES field.device(id) ON DELETE CASCADE,
            status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'unpaired')),
            paired_at timestamptz NOT NULL DEFAULT NOW(),
            unpaired_at timestamptz NULL,
            created_at timestamptz NOT NULL DEFAULT NOW()
        );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_active_glasses_pairing
            ON field.device_pairing (tenant_id, glasses_id)
            WHERE status = 'active';
        """
    )

    # 3. Forced RLS on device_pairing
    op.execute("ALTER TABLE field.device_pairing ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE field.device_pairing FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON field.device_pairing
        AS RESTRICTIVE
        FOR ALL
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS field.device_pairing CASCADE;")
    op.execute(
        """
        ALTER TABLE field.device
            DROP COLUMN IF EXISTS firmware_version,
            DROP COLUMN IF EXISTS paired_with,
            DROP COLUMN IF EXISTS battery_pct,
            DROP COLUMN IF EXISTS thermal_status,
            DROP COLUMN IF EXISTS queue_depth,
            DROP COLUMN IF EXISTS glasses_state,
            DROP COLUMN IF EXISTS last_seen_at,
            DROP COLUMN IF EXISTS revoked_at,
            DROP COLUMN IF EXISTS config_version;
        """
    )
