"""Posting Job Ordering and Locking Migration with Forced RLS (Task T3.002 / FR3.065).

Revision ID: field_0034
Revises: field_0033
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0034"
down_revision = "field_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE field.posting_job
            ADD COLUMN IF NOT EXISTS ref_doc_no text NULL,
            ADD COLUMN IF NOT EXISTS seq integer NOT NULL DEFAULT 1,
            ADD COLUMN IF NOT EXISTS locked_by text NULL,
            ADD COLUMN IF NOT EXISTS locked_until timestamptz NULL,
            ADD COLUMN IF NOT EXISTS max_attempts integer NOT NULL DEFAULT 8;

        CREATE INDEX IF NOT EXISTS idx_posting_job_queue_seq
            ON field.posting_job (tenant_id, queue_key, seq);
        CREATE INDEX IF NOT EXISTS idx_posting_job_ref_doc
            ON field.posting_job (tenant_id, ref_doc_no);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS field.idx_posting_job_ref_doc;
        DROP INDEX IF EXISTS field.idx_posting_job_queue_seq;

        ALTER TABLE field.posting_job
            DROP COLUMN IF EXISTS max_attempts,
            DROP COLUMN IF EXISTS locked_until,
            DROP COLUMN IF EXISTS locked_by,
            DROP COLUMN IF EXISTS seq,
            DROP COLUMN IF EXISTS ref_doc_no;
        """
    )
