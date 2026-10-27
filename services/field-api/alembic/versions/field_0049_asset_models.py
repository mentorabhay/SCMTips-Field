"""Phase 4 Asset Model Store, BOM & Balloon Registry Migration (WS4.7 / Tasks T4.055, T4.056, T4.059 / FR4.051-FR4.054).

Revision ID: field_0049
Revises: field_0048
Create Date: 2026-10-28
"""

from alembic import op

revision = "field_0049"
down_revision = "field_0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- 1. Asset Model table (glTF 2.0 binary metadata & lifecycle)
        CREATE TABLE IF NOT EXISTS field.asset_model (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            equipment_class text NOT NULL,
            version text NOT NULL,
            status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'validated', 'invalid', 'published', 'deprecated', 'rejected')),
            sha256_hash text NOT NULL,
            file_size_bytes bigint NOT NULL,
            triangle_count integer NOT NULL DEFAULT 0,
            glb_storage_path text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            published_at timestamptz NULL,
            published_by uuid NULL,
            updated_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_asset_model_class_version UNIQUE (tenant_id, equipment_class, version)
        );

        -- 2. Asset Model BOM table (part hierarchy, balloons, nodes, explode vectors)
        CREATE TABLE IF NOT EXISTS field.asset_model_bom (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            model_id uuid NOT NULL REFERENCES field.asset_model(id) ON DELETE CASCADE,
            part_no text NOT NULL,
            description text NOT NULL,
            qty integer NOT NULL CHECK (qty > 0),
            is_serialised boolean NOT NULL DEFAULT false,
            parent_part_no text NULL,
            node_path text NOT NULL DEFAULT '',
            node_names text[] NOT NULL DEFAULT '{}',
            balloon_no integer NULL,
            explode_vector_x real NOT NULL DEFAULT 0.0,
            explode_vector_y real NOT NULL DEFAULT 0.0,
            explode_vector_z real NOT NULL DEFAULT 0.0,
            created_at timestamptz NOT NULL DEFAULT NOW()
        );

        -- 3. Balloon Registry (per equipment class, stable across versions, retired numbers never reused)
        CREATE TABLE IF NOT EXISTS field.balloon_registry (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            equipment_class text NOT NULL,
            part_no text NOT NULL,
            node_path text NOT NULL DEFAULT '',
            balloon_no integer NOT NULL,
            is_retired boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_balloon_registry_class_part_node UNIQUE (tenant_id, equipment_class, part_no, node_path),
            CONSTRAINT uq_balloon_registry_class_balloon UNIQUE (tenant_id, equipment_class, balloon_no)
        );

        -- 4. Equipment model version pinning (FR4.054)
        ALTER TABLE field.equipment
            ADD COLUMN IF NOT EXISTS pinned_model_version_id uuid NULL REFERENCES field.asset_model(id),
            ADD COLUMN IF NOT EXISTS pinned_model_version text NULL;

        -- 5. Indexes
        CREATE INDEX IF NOT EXISTS idx_asset_model_class_status ON field.asset_model(tenant_id, equipment_class, status);
        CREATE INDEX IF NOT EXISTS idx_asset_model_bom_model ON field.asset_model_bom(tenant_id, model_id);
        CREATE INDEX IF NOT EXISTS idx_balloon_registry_lookup ON field.balloon_registry(tenant_id, equipment_class, part_no);

        -- 6. Forced RLS Isolation with PERMISSIVE policies
        ALTER TABLE field.asset_model ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.asset_model FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON field.asset_model;
        CREATE POLICY tenant_isolation ON field.asset_model
        AS PERMISSIVE FOR ALL
        USING (tenant_id = (COALESCE(NULLIF(current_setting('app.tenant_id'::text, true), ''::text), NULLIF(current_setting('app.current_tenant_id'::text, true), ''::text)))::uuid)
        WITH CHECK (tenant_id = (COALESCE(NULLIF(current_setting('app.tenant_id'::text, true), ''::text), NULLIF(current_setting('app.current_tenant_id'::text, true), ''::text)))::uuid);

        ALTER TABLE field.asset_model_bom ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.asset_model_bom FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON field.asset_model_bom;
        CREATE POLICY tenant_isolation ON field.asset_model_bom
        AS PERMISSIVE FOR ALL
        USING (tenant_id = (COALESCE(NULLIF(current_setting('app.tenant_id'::text, true), ''::text), NULLIF(current_setting('app.current_tenant_id'::text, true), ''::text)))::uuid)
        WITH CHECK (tenant_id = (COALESCE(NULLIF(current_setting('app.tenant_id'::text, true), ''::text), NULLIF(current_setting('app.current_tenant_id'::text, true), ''::text)))::uuid);

        ALTER TABLE field.balloon_registry ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.balloon_registry FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON field.balloon_registry;
        CREATE POLICY tenant_isolation ON field.balloon_registry
        AS PERMISSIVE FOR ALL
        USING (tenant_id = (COALESCE(NULLIF(current_setting('app.tenant_id'::text, true), ''::text), NULLIF(current_setting('app.current_tenant_id'::text, true), ''::text)))::uuid)
        WITH CHECK (tenant_id = (COALESCE(NULLIF(current_setting('app.tenant_id'::text, true), ''::text), NULLIF(current_setting('app.current_tenant_id'::text, true), ''::text)))::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE field.equipment DROP COLUMN IF EXISTS pinned_model_version;
        ALTER TABLE field.equipment DROP COLUMN IF EXISTS pinned_model_version_id;
        DROP TABLE IF EXISTS field.balloon_registry CASCADE;
        DROP TABLE IF EXISTS field.asset_model_bom CASCADE;
        DROP TABLE IF EXISTS field.asset_model CASCADE;
        """
    )
