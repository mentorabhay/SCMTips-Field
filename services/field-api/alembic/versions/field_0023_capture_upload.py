"""Presigned Capture Upload Migration with Forced RLS (Task T2.046 / FR2.046).

Revision ID: field_0023
Revises: field_0022
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0023"
down_revision = "field_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.capture_upload (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            device_id uuid NOT NULL REFERENCES field.device(id) ON DELETE CASCADE,
            s3_key text NOT NULL,
            expires_at timestamptz NOT NULL,
            status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'expired')),
            uploaded_at timestamptz NULL,
            created_at timestamptz NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_upload_expires ON field.capture_upload (expires_at, status);
        """
    )

    op.execute("ALTER TABLE field.capture_upload ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE field.capture_upload FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON field.capture_upload
        AS RESTRICTIVE
        FOR ALL
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS field.capture_upload CASCADE;")
