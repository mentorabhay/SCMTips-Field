"""3D Columns on Site Graph Nodes and Edges Migration (Task T4.050 / FR4.046).

Revision ID: field_0044
Revises: field_0043
Create Date: 2026-10-28
"""

from alembic import op

revision = "field_0044"
down_revision = "field_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE field.site_graph_node
            ADD COLUMN IF NOT EXISTS z real NOT NULL DEFAULT 0.0,
            ADD COLUMN IF NOT EXISTS subkind text NULL,
            ADD COLUMN IF NOT EXISTS platform_height_m real NULL,
            ADD COLUMN IF NOT EXISTS sector_code text NULL;

        ALTER TABLE field.site_graph_edge
            ADD COLUMN IF NOT EXISTS climb_length_m real NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE field.site_graph_edge
            DROP COLUMN IF EXISTS climb_length_m;

        ALTER TABLE field.site_graph_node
            DROP COLUMN IF EXISTS sector_code,
            DROP COLUMN IF EXISTS platform_height_m,
            DROP COLUMN IF EXISTS subkind,
            DROP COLUMN IF EXISTS z;
        """
    )
