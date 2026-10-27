"""Site Graph Nodes and Edges Migration with Forced RLS (Task T3.002 / FR3.065).

Revision ID: field_0035
Revises: field_0034
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0035"
down_revision = "field_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.site_graph_node (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE CASCADE,
            name text NOT NULL,
            x_m numeric(8,3) NOT NULL DEFAULT 0.000,
            y_m numeric(8,3) NOT NULL DEFAULT 0.000,
            z_m numeric(8,3) NOT NULL DEFAULT 0.000,
            node_type text NOT NULL DEFAULT 'waypoint' CHECK (node_type IN ('waypoint', 'bin', 'dock', 'door', 'intersection')),
            is_bin boolean NOT NULL DEFAULT false,
            bin_id text NULL,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_site_node_name UNIQUE (tenant_id, site_id, name)
        );

        CREATE TABLE IF NOT EXISTS field.site_graph_edge (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE CASCADE,
            from_node_id uuid NOT NULL REFERENCES field.site_graph_node(id) ON DELETE CASCADE,
            to_node_id uuid NOT NULL REFERENCES field.site_graph_node(id) ON DELETE CASCADE,
            distance_m numeric(8,3) NOT NULL,
            is_forklift_zone boolean NOT NULL DEFAULT false,
            is_one_way boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_site_node_site
            ON field.site_graph_node (tenant_id, site_id);
        CREATE INDEX IF NOT EXISTS idx_site_edge_site
            ON field.site_graph_edge (tenant_id, site_id);

        ALTER TABLE field.site_graph_node ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.site_graph_node FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON field.site_graph_node
        AS RESTRICTIVE FOR ALL
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

        ALTER TABLE field.site_graph_edge ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.site_graph_edge FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON field.site_graph_edge
        AS RESTRICTIVE FOR ALL
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS field.site_graph_edge CASCADE;
        DROP TABLE IF EXISTS field.site_graph_node CASCADE;
        """
    )
