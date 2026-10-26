"""Interim Role Grants Table with Forced RLS (Task T1.030 / CS-02).

Revision ID: field_0003
Revises: field_0002
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0003"
down_revision = "field_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE field.role_grant (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            principal_id text NOT NULL,
            role text NOT NULL CHECK (role IN (
                'field.operator',
                'field.technician',
                'field.supervisor',
                'inventory.controller',
                'field.integration',
                'field.viewer',
                'field.admin'
            )),
            site_ids text[] NOT NULL DEFAULT '{"*"}',
            granted_by text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_role_grant_tenant_principal_role UNIQUE (tenant_id, principal_id, role)
        );
    """
    )

    # Enable & Force RLS
    op.execute("ALTER TABLE field.role_grant ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE field.role_grant FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON field.role_grant
        AS RESTRICTIVE
        FOR ALL
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
    """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS field.role_grant CASCADE;")
