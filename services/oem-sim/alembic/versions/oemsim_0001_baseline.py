"""OEM simulator baseline (docs/design/M5_C3_CONTRACT.md section 5): units, their history and first-check claims.

- oemsim.unit(serial, oem, sku, sealed_at, nonce, scenario, title, copies, created_at, updated_at): one sealed unit
  of the SAMPLE maker. ``nonce`` is derived from the signing seed and the serial (oem_sim.keys), so a printed label
  stays valid when the scenarios are seeded again. ``scenario`` / ``title`` / ``copies`` only drive the label sheet.
- oemsim.unit_event(id, serial, type, at, area): the unit's history (manufactured, shipped_to_seller, delivered,
  activated, returned, refurbished); ``area`` is coarse (city level) or null.
- oemsim.first_check(serial, checker, at, area): the first verification of a serial. The primary key on ``serial``
  makes the claim atomic: of two concurrent first checks one insert wins (ON CONFLICT DO NOTHING), the other reads
  the winner. ``checker`` is the pseudonymous id field-api sends (32 hex), never a name.
- oemsim.forged_label(serial, sku, sealed_at, scenario, title): a code for the label sheet only, signed with a
  forger's key and never in the registry (scenario L3, counterfeit).

Revision ID: oemsim_0001
Revises: (none)
"""

from alembic import op

revision = "oemsim_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE SCHEMA IF NOT EXISTS oemsim;
        CREATE TABLE oemsim.unit (
            serial text PRIMARY KEY CHECK (serial ~ '^[A-Z0-9-]{4,40}$'),
            oem text NOT NULL CHECK (oem ~ '^[a-z0-9-]{3,40}$'),
            sku text NOT NULL CHECK (sku ~ '^[A-Z0-9-]{2,40}$'),
            sealed_at date NOT NULL,
            nonce text NOT NULL CHECK (nonce ~ '^[0-9a-f]{16}$'),
            scenario text NULL CHECK (scenario IS NULL OR length(scenario) <= 8),
            title text NULL CHECK (title IS NULL OR length(title) <= 120),
            copies integer NOT NULL DEFAULT 1 CHECK (copies BETWEEN 1 AND 4),
            created_at timestamptz NOT NULL DEFAULT NOW(),
            updated_at timestamptz NOT NULL DEFAULT NOW()
        );
        CREATE TABLE oemsim.unit_event (
            id bigserial PRIMARY KEY,
            serial text NOT NULL REFERENCES oemsim.unit(serial) ON DELETE CASCADE,
            type text NOT NULL CHECK (type IN ('manufactured', 'shipped_to_seller', 'delivered', 'activated',
                                               'returned', 'refurbished')),
            at date NOT NULL,
            area text NULL CHECK (area IS NULL OR length(area) <= 60),
            created_at timestamptz NOT NULL DEFAULT NOW()
        );
        CREATE INDEX idx_oemsim_unit_event_serial ON oemsim.unit_event (serial, at, id);
        CREATE TABLE oemsim.first_check (
            serial text PRIMARY KEY REFERENCES oemsim.unit(serial) ON DELETE CASCADE,
            checker text NOT NULL CHECK (checker ~ '^[0-9a-f]{32}$'),
            at timestamptz NOT NULL DEFAULT NOW(),
            area text NULL CHECK (area IS NULL OR length(area) <= 60)
        );
        CREATE TABLE oemsim.forged_label (
            serial text PRIMARY KEY CHECK (serial ~ '^[A-Z0-9-]{4,40}$'),
            sku text NOT NULL CHECK (sku ~ '^[A-Z0-9-]{2,40}$'),
            sealed_at date NOT NULL,
            scenario text NULL CHECK (scenario IS NULL OR length(scenario) <= 8),
            title text NULL CHECK (title IS NULL OR length(title) <= 120),
            created_at timestamptz NOT NULL DEFAULT NOW()
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS oemsim.forged_label;
        DROP TABLE IF EXISTS oemsim.first_check;
        DROP TABLE IF EXISTS oemsim.unit_event;
        DROP TABLE IF EXISTS oemsim.unit;
        """
    )
