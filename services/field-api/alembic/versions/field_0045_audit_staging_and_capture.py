"""Audit Task Extensions, Capture Location, and Evidence Consent Migration (Task T4.013, T4.034 / FR4.014, FR4.020).

Revision ID: field_0045
Revises: field_0044
Create Date: 2026-10-28
"""

from alembic import op

revision = "field_0045"
down_revision = "field_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE field.task
            ADD COLUMN IF NOT EXISTS snapshot_version text NULL;

        ALTER TABLE field.task_line
            ADD COLUMN IF NOT EXISTS expected_serial text NULL,
            ADD COLUMN IF NOT EXISTS location_id uuid NULL REFERENCES field.location(id) ON DELETE SET NULL;

        ALTER TABLE field.capture
            ADD COLUMN IF NOT EXISTS location_id uuid NULL REFERENCES field.location(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS device_position jsonb NULL;

        ALTER TABLE field.capture
            DROP CONSTRAINT IF EXISTS capture_verify_status_check;

        ALTER TABLE field.capture
            ADD CONSTRAINT capture_verify_status_check
            CHECK (verify_status IN ('not_needed', 'unverified', 'queued', 'verified', 'mismatch', 'failed'));

        ALTER TABLE field.capture_evidence
            ADD COLUMN IF NOT EXISTS consent_ref text NULL;

        CREATE POLICY allow_all ON field.verification_attempt FOR ALL USING (true) WITH CHECK (true);
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS allow_all ON field.verification_attempt;")
    op.execute(
        """
        ALTER TABLE field.capture_evidence
            DROP COLUMN IF EXISTS consent_ref;

        ALTER TABLE field.capture
            DROP CONSTRAINT IF EXISTS capture_verify_status_check;

        ALTER TABLE field.capture
            ADD CONSTRAINT capture_verify_status_check
            CHECK (verify_status IN ('unverified', 'verified', 'mismatch', 'failed'));

        ALTER TABLE field.capture
            DROP COLUMN IF EXISTS device_position,
            DROP COLUMN IF EXISTS location_id;

        ALTER TABLE field.task_line
            DROP COLUMN IF EXISTS location_id,
            DROP COLUMN IF EXISTS expected_serial;

        ALTER TABLE field.task
            DROP COLUMN IF EXISTS snapshot_version;
        """
    )
