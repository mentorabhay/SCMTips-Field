"""Verification Attempt Table Migration with Forced RLS (Task T2.046 / FR2.053, FR2.058).

Revision ID: field_0028
Revises: field_0027
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0028"
down_revision = "field_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.verification_attempt (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            capture_id uuid NOT NULL REFERENCES field.capture(id) ON DELETE CASCADE,
            model_name text NOT NULL,
            prompt_id text NOT NULL,
            prompt_version text NOT NULL,
            verdict text NOT NULL CHECK (verdict IN ('verified', 'mismatch', 'failed')),
            confidence numeric(4,3) NULL,
            latency_ms integer NOT NULL,
            tokens_used integer NOT NULL DEFAULT 0,
            cost_usd numeric(8,6) NOT NULL DEFAULT 0.000000,
            created_at timestamptz NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_verify_capture
            ON field.verification_attempt (tenant_id, capture_id);
        """
    )

    op.execute("ALTER TABLE field.verification_attempt ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE field.verification_attempt FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON field.verification_attempt
        AS RESTRICTIVE
        FOR ALL
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS field.verification_attempt CASCADE;")
