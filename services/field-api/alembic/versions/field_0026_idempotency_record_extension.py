"""Idempotency Record Extension Migration (Task T2.046 / FR2.047).

Revision ID: field_0026
Revises: field_0025
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0026"
down_revision = "field_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE field.idempotency_record
            ADD COLUMN IF NOT EXISTS route text NULL,
            ADD COLUMN IF NOT EXISTS body_sha256 text NULL,
            ADD COLUMN IF NOT EXISTS expires_at timestamptz NOT NULL DEFAULT (NOW() + interval '24 hours');

        CREATE INDEX IF NOT EXISTS idx_idempotency_expires
            ON field.idempotency_record (expires_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS field.idx_idempotency_expires;
        ALTER TABLE field.idempotency_record
            DROP COLUMN IF EXISTS route,
            DROP COLUMN IF EXISTS body_sha256,
            DROP COLUMN IF EXISTS expires_at;
        """
    )
