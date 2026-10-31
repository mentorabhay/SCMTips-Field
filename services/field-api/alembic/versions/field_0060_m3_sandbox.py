"""M3 sandbox and barcodes (docs/design/M3_CONTRACT.md sections 2 and 3).

- field.material_barcode(tenant_id, material_id, barcode, uom): the barcodes of a material as the ERP
  read gives them (S/4 to_ProductUnitsOfMeasureEAN / MEAN), synced by the worker's material sync and,
  for a sandbox item, written at once by field-api. Forced RLS: RESTRICTIVE tenant_isolation plus the
  permissive base policy, like field.material (materials and their barcodes are tenant-wide).
- field.site.mode: production (default) or sandbox. Changed only by field.admin (PATCH /v1/sites).
- field.task_line.source_key: the Idempotency-Key of the sandbox "add item" that created the line
  (unique per task), so a retried add returns the first line.
- field.pi_document.storage_bin: the bin of a sandbox count that starts empty and gains lines as boxes
  are scanned; field.pi_document.simulated: the count was set up by ``stack home --simulate-differences``
  (its ERP documents are marked simulated).

Revision ID: field_0060
Revises: field_0059
"""

from alembic import op

revision = "field_0060"
down_revision = "field_0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE field.material_barcode (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            material_id uuid NOT NULL REFERENCES field.material(id) ON DELETE CASCADE,
            barcode text NOT NULL CHECK (length(barcode) BETWEEN 1 AND 128),
            uom text NOT NULL DEFAULT 'EA',
            created_at timestamptz NOT NULL DEFAULT NOW(),
            updated_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_material_barcode UNIQUE (tenant_id, material_id, barcode)
        );
        CREATE INDEX idx_material_barcode_code ON field.material_barcode (tenant_id, upper(barcode));
        ALTER TABLE field.material_barcode ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.material_barcode FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON field.material_barcode AS RESTRICTIVE FOR ALL
            USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
        CREATE POLICY rls_permissive_base ON field.material_barcode AS PERMISSIVE FOR ALL
            USING (true) WITH CHECK (true);
        GRANT SELECT, INSERT, UPDATE, DELETE ON field.material_barcode TO field_app, field_worker;

        ALTER TABLE field.site ADD COLUMN IF NOT EXISTS mode text NOT NULL DEFAULT 'production';
        ALTER TABLE field.site ADD CONSTRAINT site_mode_check CHECK (mode IN ('production', 'sandbox'));

        ALTER TABLE field.task_line ADD COLUMN IF NOT EXISTS source_key text;
        CREATE UNIQUE INDEX uq_task_line_source_key ON field.task_line (task_id, source_key)
            WHERE source_key IS NOT NULL;

        ALTER TABLE field.pi_document ADD COLUMN IF NOT EXISTS storage_bin text;
        ALTER TABLE field.pi_document ADD COLUMN IF NOT EXISTS simulated boolean NOT NULL DEFAULT false;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE field.pi_document DROP COLUMN IF EXISTS simulated;
        ALTER TABLE field.pi_document DROP COLUMN IF EXISTS storage_bin;
        DROP INDEX IF EXISTS field.uq_task_line_source_key;
        ALTER TABLE field.task_line DROP COLUMN IF EXISTS source_key;
        ALTER TABLE field.site DROP CONSTRAINT IF EXISTS site_mode_check;
        ALTER TABLE field.site DROP COLUMN IF EXISTS mode;
        DROP TABLE IF EXISTS field.material_barcode;
        """
    )
