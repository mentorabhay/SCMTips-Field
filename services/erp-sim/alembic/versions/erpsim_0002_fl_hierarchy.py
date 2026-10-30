"""Functional location hierarchy in the simulator database (M2 tower data).

API_FUNCTIONALLOCATION used to serve only the JSON fixtures; locations created in the database had
no parent, kind, sector or height, so a tower built for a test could not be read back as a tree.

Also adds the CHANGE_DOC number range: Install / Dismantle allocate a change document from it and
failed with KeyError (HTTP 500) on every call because the baseline never configured it; and
erpsim.equipment_install.change_doc, which both routes write (UndefinedColumn, HTTP 500, before).

Revision ID: erpsim_0002
Revises: erpsim_0001
"""

from alembic import op

revision = "erpsim_0002"
down_revision = "erpsim_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE erpsim.functional_location ADD COLUMN IF NOT EXISTS superior_func_loc text;
        ALTER TABLE erpsim.functional_location ADD COLUMN IF NOT EXISTS kind text;
        ALTER TABLE erpsim.functional_location ADD COLUMN IF NOT EXISTS sector_code text;
        ALTER TABLE erpsim.functional_location ADD COLUMN IF NOT EXISTS height_m numeric(6,2);
        ALTER TABLE erpsim.functional_location ADD COLUMN IF NOT EXISTS plant text;
        ALTER TABLE erpsim.functional_location ADD COLUMN IF NOT EXISTS last_change_date_time timestamptz
            NOT NULL DEFAULT NOW();
        ALTER TABLE erpsim.equipment_install ADD COLUMN IF NOT EXISTS change_doc text;
        INSERT INTO erpsim.number_range (client, object, current, lower, upper)
        VALUES ('100', 'CHANGE_DOC', 7000000000, 7000000000, 7999999999) ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM erpsim.number_range WHERE object = 'CHANGE_DOC';
        ALTER TABLE erpsim.equipment_install DROP COLUMN IF EXISTS change_doc;
        ALTER TABLE erpsim.functional_location DROP COLUMN IF EXISTS last_change_date_time;
        ALTER TABLE erpsim.functional_location DROP COLUMN IF EXISTS plant;
        ALTER TABLE erpsim.functional_location DROP COLUMN IF EXISTS height_m;
        ALTER TABLE erpsim.functional_location DROP COLUMN IF EXISTS sector_code;
        ALTER TABLE erpsim.functional_location DROP COLUMN IF EXISTS kind;
        ALTER TABLE erpsim.functional_location DROP COLUMN IF EXISTS superior_func_loc;
        """
    )
