"""Phase 4 3D Site Graph Constraints and Kinds Migration (Task T4.050 / FR4.046 / TC4.142).

Revision ID: field_0048
Revises: field_0047
Create Date: 2026-10-28
"""

from alembic import op

revision = "field_0048"
down_revision = "field_0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE field.site_graph_node DROP CONSTRAINT IF EXISTS site_graph_node_node_type_check;
        ALTER TABLE field.site_graph_node ADD CONSTRAINT site_graph_node_node_type_check
            CHECK (node_type IN ('waypoint', 'bin', 'dock', 'door', 'intersection', 'way', 'place', 'asset'));

        ALTER TABLE field.site_graph_node DROP CONSTRAINT IF EXISTS site_graph_node_subkind_check;
        ALTER TABLE field.site_graph_node ADD CONSTRAINT site_graph_node_subkind_check
            CHECK (subkind IS NULL OR subkind IN (
                'ground', 'ladder_foot', 'rest_platform', 'sector_platform', 'antenna', 'shelter', 'rack'
            ));

        ALTER TABLE field.site_graph_edge DROP CONSTRAINT IF EXISTS site_graph_edge_length_check;
        ALTER TABLE field.site_graph_edge ADD CONSTRAINT site_graph_edge_length_check
            CHECK (distance_m >= 0.0 AND (climb_length_m IS NULL OR climb_length_m >= 0.0));

        DROP POLICY IF EXISTS tenant_isolation ON field.site_graph_node;
        CREATE POLICY tenant_isolation ON field.site_graph_node
        AS PERMISSIVE FOR ALL
        USING (tenant_id = (COALESCE(NULLIF(current_setting('app.tenant_id'::text, true), ''::text), NULLIF(current_setting('app.current_tenant_id'::text, true), ''::text)))::uuid)
        WITH CHECK (tenant_id = (COALESCE(NULLIF(current_setting('app.tenant_id'::text, true), ''::text), NULLIF(current_setting('app.current_tenant_id'::text, true), ''::text)))::uuid);

        DROP POLICY IF EXISTS tenant_isolation ON field.site_graph_edge;
        CREATE POLICY tenant_isolation ON field.site_graph_edge
        AS PERMISSIVE FOR ALL
        USING (tenant_id = (COALESCE(NULLIF(current_setting('app.tenant_id'::text, true), ''::text), NULLIF(current_setting('app.current_tenant_id'::text, true), ''::text)))::uuid)
        WITH CHECK (tenant_id = (COALESCE(NULLIF(current_setting('app.tenant_id'::text, true), ''::text), NULLIF(current_setting('app.current_tenant_id'::text, true), ''::text)))::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE field.site_graph_edge DROP CONSTRAINT IF EXISTS site_graph_edge_length_check;
        ALTER TABLE field.site_graph_node DROP CONSTRAINT IF EXISTS site_graph_node_subkind_check;
        ALTER TABLE field.site_graph_node DROP CONSTRAINT IF EXISTS site_graph_node_node_type_check;
        ALTER TABLE field.site_graph_node ADD CONSTRAINT site_graph_node_node_type_check
            CHECK (node_type IN ('waypoint', 'bin', 'dock', 'door', 'intersection'));
        """
    )
