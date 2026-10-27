"""Handling Unit Table Migration with Forced RLS (Task T3.002 / FR3.065).

Revision ID: field_0031
Revises: field_0030
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0031"
down_revision = "field_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.handling_unit (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            sscc text NOT NULL,
            hu_type text NOT NULL DEFAULT 'pallet',
            storage_bin text NULL,
            parent_hu_id uuid NULL REFERENCES field.handling_unit(id) ON DELETE SET NULL,
            weight_kg numeric(8,2) NULL,
            delivery_ref text NULL,
            task_line_id uuid NULL REFERENCES field.task_line(id) ON DELETE SET NULL,
            material_id text NULL,
            quantity numeric(12,3) NOT NULL DEFAULT 1,
            uom text NOT NULL DEFAULT 'EA',
            is_damaged boolean NOT NULL DEFAULT FALSE,
            damage_evidence_crop_id uuid NULL,
            inspection_status text NOT NULL DEFAULT 'none' CHECK (inspection_status IN ('none', 'quality_hold', 'released', 'rejected')),
            status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'packed', 'shipped', 'archived')),
            created_at timestamptz NOT NULL DEFAULT NOW(),
            updated_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_hu_tenant_sscc UNIQUE (tenant_id, sscc)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_hu_tenant_delivery_sscc
            ON field.handling_unit (tenant_id, delivery_ref, sscc)
            WHERE delivery_ref IS NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_hu_sscc
            ON field.handling_unit (tenant_id, sscc);
        CREATE INDEX IF NOT EXISTS idx_hu_bin
            ON field.handling_unit (tenant_id, storage_bin);

        ALTER TABLE field.handling_unit ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.handling_unit FORCE ROW LEVEL SECURITY;

        CREATE POLICY tenant_isolation ON field.handling_unit
        AS RESTRICTIVE
        FOR ALL
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

        CREATE POLICY allow_all ON field.handling_unit
        FOR ALL
        USING (true)
        WITH CHECK (true);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS field.handling_unit CASCADE;
        """
    )
