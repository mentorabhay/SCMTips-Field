"""Capture Extensions and Evidence Storage Migration (Task T2.046 / FR2.046, FR2.051).

Revision ID: field_0022
Revises: field_0021
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0022"
down_revision = "field_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add Phase 2 columns to field.capture
    op.execute(
        """
        ALTER TABLE field.capture
            ADD COLUMN IF NOT EXISTS shutter_timestamp bigint NULL,
            ADD COLUMN IF NOT EXISTS blur_applied boolean NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS bystander_count integer NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS code_type text NULL,
            ADD COLUMN IF NOT EXISTS code_value text NULL,
            ADD COLUMN IF NOT EXISTS readability numeric(4,3) NULL,
            ADD COLUMN IF NOT EXISTS rank_score numeric(4,3) NULL,
            ADD COLUMN IF NOT EXISTS task_line_id uuid NULL REFERENCES field.task_line(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS on_task boolean NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS superseded_by uuid NULL REFERENCES field.capture(id),
            ADD COLUMN IF NOT EXISTS verify_status text NOT NULL DEFAULT 'unverified' CHECK (verify_status IN ('unverified', 'verified', 'mismatch', 'failed')),
            ADD COLUMN IF NOT EXISTS verify_reason text NULL;

        CREATE INDEX IF NOT EXISTS idx_capture_dedupe
            ON field.capture (tenant_id, task_id, code_type, code_value)
            WHERE superseded_by IS NULL;
        """
    )

    # 2. Create field.capture_evidence table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.capture_evidence (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            capture_id uuid NOT NULL REFERENCES field.capture(id) ON DELETE CASCADE,
            crop_s3_uri text NOT NULL,
            file_size_bytes bigint NOT NULL,
            sha256_hash text NOT NULL,
            sse_kms_key_id text NULL,
            retention_until timestamptz NOT NULL,
            is_legal_hold boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_evidence_retention
            ON field.capture_evidence (retention_until, is_legal_hold);
        """
    )

    # 3. Forced RLS on capture_evidence
    op.execute("ALTER TABLE field.capture_evidence ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE field.capture_evidence FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON field.capture_evidence
        AS RESTRICTIVE
        FOR ALL
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS field.capture_evidence CASCADE;")
    op.execute(
        """
        DROP INDEX IF EXISTS field.idx_capture_dedupe;
        ALTER TABLE field.capture
            DROP COLUMN IF EXISTS shutter_timestamp,
            DROP COLUMN IF EXISTS blur_applied,
            DROP COLUMN IF EXISTS bystander_count,
            DROP COLUMN IF EXISTS code_type,
            DROP COLUMN IF EXISTS code_value,
            DROP COLUMN IF EXISTS readability,
            DROP COLUMN IF EXISTS rank_score,
            DROP COLUMN IF EXISTS task_line_id,
            DROP COLUMN IF EXISTS on_task,
            DROP COLUMN IF EXISTS superseded_by,
            DROP COLUMN IF EXISTS verify_status,
            DROP COLUMN IF EXISTS verify_reason;
        """
    )
