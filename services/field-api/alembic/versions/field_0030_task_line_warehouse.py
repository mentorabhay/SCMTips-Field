"""Task Line Warehouse Columns Migration with Forced RLS (Task T3.002 / FR3.065).

Revision ID: field_0030
Revises: field_0028
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0030"
down_revision = "field_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE field.task_line
            ADD COLUMN IF NOT EXISTS storage_bin text NULL,
            ADD COLUMN IF NOT EXISTS target_bin text NULL,
            ADD COLUMN IF NOT EXISTS batch text NULL,
            ADD COLUMN IF NOT EXISTS sscc text NULL,
            ADD COLUMN IF NOT EXISTS picked_qty numeric(12,3) NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS received_qty numeric(12,3) NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS movement_type text NULL;

        CREATE INDEX IF NOT EXISTS idx_task_line_bin
            ON field.task_line (tenant_id, storage_bin);
        CREATE INDEX IF NOT EXISTS idx_task_line_target_bin
            ON field.task_line (tenant_id, target_bin);
        CREATE INDEX IF NOT EXISTS idx_task_line_sscc
            ON field.task_line (tenant_id, sscc);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS field.idx_task_line_sscc;
        DROP INDEX IF EXISTS field.idx_task_line_target_bin;
        DROP INDEX IF EXISTS field.idx_task_line_bin;

        ALTER TABLE field.task_line
            DROP COLUMN IF EXISTS movement_type,
            DROP COLUMN IF EXISTS received_qty,
            DROP COLUMN IF EXISTS picked_qty,
            DROP COLUMN IF EXISTS sscc,
            DROP COLUMN IF EXISTS batch,
            DROP COLUMN IF EXISTS target_bin,
            DROP COLUMN IF EXISTS storage_bin;
        """
    )
