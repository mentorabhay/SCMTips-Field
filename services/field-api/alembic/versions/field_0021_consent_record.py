"""Consent Record Migration with Forced RLS (Task T2.046 / FR2.064).

Revision ID: field_0021
Revises: field_0020
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0021"
down_revision = "field_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.consent_record (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE RESTRICT,
            user_id text NOT NULL,
            device_id uuid NOT NULL REFERENCES field.device(id) ON DELETE CASCADE,
            consent_version text NOT NULL DEFAULT 'v1',
            consent_type text NOT NULL DEFAULT 'site_and_bystander_privacy',
            granted boolean NOT NULL DEFAULT true,
            granted_at timestamptz NOT NULL DEFAULT NOW(),
            withdrawn_at timestamptz NULL,
            created_at timestamptz NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_consent_lookup
            ON field.consent_record (tenant_id, site_id, user_id, device_id);
        """
    )

    op.execute("ALTER TABLE field.consent_record ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE field.consent_record FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON field.consent_record
        AS RESTRICTIVE
        FOR ALL
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS field.consent_record CASCADE;")
