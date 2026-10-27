"""Phase 3 Warehouse Optimization Indexes Migration (Task T3.002 / FR3.065).

Revision ID: field_0039
Revises: field_0038
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0039"
down_revision = "field_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_line_status_bin
            ON field.task_line (tenant_id, status, storage_bin);

        CREATE INDEX IF NOT EXISTS idx_posting_job_status_attempts
            ON field.posting_job (tenant_id, status, attempts);

        CREATE INDEX IF NOT EXISTS idx_site_graph_type
            ON field.site_graph_node (tenant_id, site_id, node_type);

        CREATE INDEX IF NOT EXISTS idx_trail_point_speed_forklift
            ON field.trail_point (tenant_id, in_forklift_zone, speed_mps);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS field.idx_trail_point_speed_forklift;
        DROP INDEX IF EXISTS field.idx_site_graph_type;
        DROP INDEX IF EXISTS field.idx_posting_job_status_attempts;
        DROP INDEX IF EXISTS field.idx_task_line_status_bin;
        """
    )
