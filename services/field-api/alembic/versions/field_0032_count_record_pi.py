"""Count Record PI Extensions Migration with Forced RLS (Task T3.002 / FR3.065).

Revision ID: field_0032
Revises: field_0031
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0032"
down_revision = "field_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE field.count_record
            ADD COLUMN IF NOT EXISTS pi_doc_id text NULL,
            ADD COLUMN IF NOT EXISTS recount_round integer NOT NULL DEFAULT 1,
            ADD COLUMN IF NOT EXISTS operator_id text NULL,
            ADD COLUMN IF NOT EXISTS verified_by text NULL;

        CREATE INDEX IF NOT EXISTS idx_count_record_pi
            ON field.count_record (tenant_id, pi_doc_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS field.idx_count_record_pi;

        ALTER TABLE field.count_record
            DROP COLUMN IF EXISTS verified_by,
            DROP COLUMN IF EXISTS operator_id,
            DROP COLUMN IF EXISTS recount_round,
            DROP COLUMN IF EXISTS pi_doc_id;
        """
    )
