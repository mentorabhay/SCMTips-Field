"""M3 sandbox: barcodes of materials (SAP MEAN) and what the sandbox needs in the simulator.

- erpsim.material_barcode(client, material_no, barcode, uom, is_main), PK (client, barcode): modelled on
  SAP table MEAN (international article numbers per material and unit). Every SAMPLE material gets
  barcode = material_no, so the printed labels that carry the material number keep working.
- erpsim.material.sandbox_plant: a material created by a sandbox site (HOME-nnnn) exists for that plant
  only (S/4 extends a material to plants in MARC; the sim lists every other material for every plant).
- erpsim.physical_inventory_doc.header_data: the document header, so a PI document created for a sandbox
  site can carry ``sandbox`` into the material document its differences post.
- number range SANDBOX_MATERIAL (HOME-0001 .. HOME-9999).

Revision ID: erpsim_0003
Revises: erpsim_0002
"""

from alembic import op

revision = "erpsim_0003"
down_revision = "erpsim_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE erpsim.material_barcode (
            client text NOT NULL DEFAULT '100',
            material_no text NOT NULL,
            barcode text NOT NULL CHECK (length(barcode) BETWEEN 1 AND 128),
            uom text NOT NULL DEFAULT 'EA',
            is_main boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            PRIMARY KEY (client, barcode),
            CONSTRAINT fk_material_barcode_material FOREIGN KEY (client, material_no)
                REFERENCES erpsim.material (client, material_no) ON DELETE CASCADE
        );
        CREATE INDEX idx_material_barcode_material ON erpsim.material_barcode (client, material_no);
        INSERT INTO erpsim.material_barcode (client, material_no, barcode, uom, is_main)
        SELECT client, material_no, material_no, base_uom, true FROM erpsim.material
         WHERE material_no LIKE 'SAMPLE-%'
        ON CONFLICT DO NOTHING;

        ALTER TABLE erpsim.material ADD COLUMN IF NOT EXISTS sandbox_plant text;
        ALTER TABLE erpsim.physical_inventory_doc ADD COLUMN IF NOT EXISTS header_data jsonb NOT NULL
            DEFAULT '{}'::jsonb;
        INSERT INTO erpsim.number_range (client, object, current, lower, upper)
        VALUES ('100', 'SANDBOX_MATERIAL', 0, 0, 9999) ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM erpsim.number_range WHERE object = 'SANDBOX_MATERIAL';
        ALTER TABLE erpsim.physical_inventory_doc DROP COLUMN IF EXISTS header_data;
        ALTER TABLE erpsim.material DROP COLUMN IF EXISTS sandbox_plant;
        DROP TABLE IF EXISTS erpsim.material_barcode;
        """
    )
