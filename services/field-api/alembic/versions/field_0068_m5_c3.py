"""M5 case C3: authenticity checks and claims from them (docs/design/M5_C3_CONTRACT.md sections 3, 4).

- field.authenticity_check(id, tenant_id, site_id, idempotency_key, principal_id, device_id, capture_id, code, oem,
  serial, sku, verdict, rule, tamper, reasons, signals, say, say_next, final, visual_due_at, models, cost_usd,
  latency_ms, created_at, updated_at): one "check this box" (POST /v1/authenticity/checks). ``verdict`` and ``rule``
  come from the deterministic rule table (authenticity.rules) and never change after the insert; the visual seal check
  (two steps, like M5-S01) later sets ``tamper``, its reasons, ``say`` / ``say_next`` and ``final`` while ``final`` is
  false. ``visual_due_at``: past it, the next read ends an unfinished visual check (``visual:not_finished``). The
  first-check claim itself lives at the maker (oemsim.first_check), never here. Unique (tenant_id, idempotency_key).
  Forced RLS: RESTRICTIVE tenant_isolation plus a PERMISSIVE site_scope, as every M3-M5 table.
- field.supplier_claim gains ``kind`` (supplier | authenticity, default supplier: every M5 claim is unchanged) and
  ``check_id``; ``look_id`` is nullable now, and exactly one of them is set by kind. One claim per check
  (UNIQUE (tenant_id, check_id)) as one per look.

Revision ID: field_0068_m5_c3
Revises: field_0067_m5_try (built beside the try page's 0067 on field_0066; re-pointed after it at the M5 merge,
the two touch different tables)
"""

from alembic import op

revision = "field_0068_m5_c3"
down_revision = "field_0067_m5_try"
branch_labels = None
depends_on = None

_RLS = """
ALTER TABLE field.{t} ENABLE ROW LEVEL SECURITY;
ALTER TABLE field.{t} FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON field.{t} AS RESTRICTIVE FOR ALL
    USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY site_scope ON field.{t} AS PERMISSIVE FOR ALL
    USING (nullif(current_setting('app.site_ids', true), '') = '*'
           OR site_id::text = ANY (string_to_array(nullif(current_setting('app.site_ids', true), ''), ',')));
GRANT SELECT, INSERT, UPDATE, DELETE ON field.{t} TO field_app, field_worker;
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE field.authenticity_check (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE RESTRICT,
            idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 255),
            principal_id text NOT NULL,
            device_id uuid NULL,
            capture_id uuid NULL,
            code text NOT NULL CHECK (length(code) BETWEEN 1 AND 1024),
            oem text NULL,
            serial text NULL,
            sku text NULL,
            verdict text NOT NULL CHECK (verdict IN ('GENUINE_NEW', 'GENUINE_PREVIOUSLY_ACTIVATED',
                                                     'RETURNED_REFURBISHED', 'CANNOT_VERIFY', 'LIKELY_COUNTERFEIT')),
            rule text NOT NULL CHECK (rule ~ '^R[0-9]{1,2}$'),
            tamper boolean NULL,
            reasons jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(reasons) = 'array'),
            signals jsonb NOT NULL CHECK (jsonb_typeof(signals) = 'object'),
            say text NOT NULL CHECK (length(say) BETWEEN 1 AND 1000),
            say_next text NULL CHECK (say_next IS NULL OR length(say_next) <= 500),
            final boolean NOT NULL DEFAULT true,
            visual_due_at timestamptz NULL,
            models jsonb NOT NULL DEFAULT '[]'::jsonb,
            cost_usd numeric(12, 6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
            latency_ms integer NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),
            created_at timestamptz NOT NULL DEFAULT NOW(),
            updated_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_authenticity_check_idempotency UNIQUE (tenant_id, idempotency_key),
            CHECK (final OR visual_due_at IS NOT NULL)
        );
        CREATE INDEX idx_authenticity_check_serial ON field.authenticity_check (tenant_id, serial, created_at)
            WHERE serial IS NOT NULL;
        CREATE INDEX idx_authenticity_check_pending ON field.authenticity_check (visual_due_at) WHERE NOT final;
        """
        + _RLS.format(t="authenticity_check")
        + """
        ALTER TABLE field.supplier_claim ADD COLUMN kind text NOT NULL DEFAULT 'supplier'
            CHECK (kind IN ('supplier', 'authenticity'));
        ALTER TABLE field.supplier_claim ADD COLUMN check_id uuid NULL;
        ALTER TABLE field.supplier_claim ALTER COLUMN look_id DROP NOT NULL;
        ALTER TABLE field.supplier_claim ADD CONSTRAINT uq_supplier_claim_check UNIQUE (tenant_id, check_id);
        ALTER TABLE field.supplier_claim ADD CONSTRAINT ck_supplier_claim_kind_subject CHECK (
            (kind = 'supplier' AND look_id IS NOT NULL AND check_id IS NULL)
            OR (kind = 'authenticity' AND check_id IS NOT NULL AND look_id IS NULL));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM field.supplier_claim WHERE kind = 'authenticity';
        ALTER TABLE field.supplier_claim DROP CONSTRAINT IF EXISTS ck_supplier_claim_kind_subject;
        ALTER TABLE field.supplier_claim DROP CONSTRAINT IF EXISTS uq_supplier_claim_check;
        ALTER TABLE field.supplier_claim ALTER COLUMN look_id SET NOT NULL;
        ALTER TABLE field.supplier_claim DROP COLUMN IF EXISTS check_id;
        ALTER TABLE field.supplier_claim DROP COLUMN IF EXISTS kind;
        DROP TABLE IF EXISTS field.authenticity_check;
        """
    )
