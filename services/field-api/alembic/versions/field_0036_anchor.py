"""Anchor Table Migration with Forced RLS (Task T3.002 / FR3.065).

Revision ID: field_0036
Revises: field_0035
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0036"
down_revision = "field_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.anchor (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE CASCADE,
            anchor_type text NOT NULL CHECK (anchor_type IN ('ble', 'wifi', 'uwb', 'qr', 'rfid')),
            identifier text NOT NULL,
            x_m numeric(8,3) NOT NULL DEFAULT 0.000,
            y_m numeric(8,3) NOT NULL DEFAULT 0.000,
            z_m numeric(8,3) NOT NULL DEFAULT 0.000,
            tx_power numeric(5,2) NULL,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_anchor_tenant_site_ident UNIQUE (tenant_id, site_id, identifier)
        );

        CREATE INDEX IF NOT EXISTS idx_anchor_site
            ON field.anchor (tenant_id, site_id);

        ALTER TABLE field.anchor ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.anchor FORCE ROW LEVEL SECURITY;

        CREATE POLICY tenant_isolation ON field.anchor
        AS RESTRICTIVE FOR ALL
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS field.anchor CASCADE;
        """
    )
