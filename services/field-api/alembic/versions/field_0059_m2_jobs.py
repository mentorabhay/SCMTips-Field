"""M2 jobs contract (docs/design/M2_JOBS_CONTRACT.md): putaway / pick / count / audit / swap on one runner.

- field.task: subtitle (list line under the title), reason (why a recount exists), recount_of,
  completed_at (set by trigger when the status becomes completed, cleared if it leaves it).
- field.posting_job: last_error (the SAP / adapter message of the last failed attempt; for the console).
- field.task_line: position (tower slot, "Sector A · slot 2"), confirmed_bin (putaway / pick bin scan),
  confirmed_product (pick product scan), captured_serial (audit / swap old unit), new_serial (swap new unit),
  equipment_no (ERP equipment of the expected unit).
- field.pi_document: count_round (1 = first count, 2/3 = recounts, FR3.033) and recount_of.
- field.task_line_confirmation: every scan the phone confirms on a line (append-only audit trail).
- field.bin_stock: field-side stock by storage bin. SAP IM has no bins (FR3.014): putaway, pick and PI
  postings keep this table in step, and the putaway proposal and pick stops read it.

- field.site_visit: user_id, override_by, acked_by become text. Principals are text ids everywhere
  else (tokens carry e.g. "op-1"); as uuid, a check-in by any non-UUID principal failed (cast error).

- field.climb_safety_event: type also allows climb_safe_released (contract §6; the phone sends it on the
  way down and the insert failed with a check violation, HTTP 500).

Every new table has forced RLS: RESTRICTIVE tenant_isolation plus a PERMISSIVE site_scope.

Revision ID: field_0059
Revises: field_0058
"""

from alembic import op

revision = "field_0059"
down_revision = "field_0058"
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
        ALTER TABLE field.task ADD COLUMN IF NOT EXISTS subtitle text;
        ALTER TABLE field.task ADD COLUMN IF NOT EXISTS reason text;
        ALTER TABLE field.task ADD COLUMN IF NOT EXISTS recount_of uuid REFERENCES field.task(id) ON DELETE SET NULL;
        ALTER TABLE field.task ADD COLUMN IF NOT EXISTS completed_at timestamptz;
        CREATE OR REPLACE FUNCTION field.task_completed_at() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.status = 'completed' AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM 'completed') THEN
                NEW.completed_at := NOW();
            ELSIF NEW.status <> 'completed' THEN
                NEW.completed_at := NULL;
            END IF;
            RETURN NEW;
        END $$;
        DROP TRIGGER IF EXISTS trg_task_completed_at ON field.task;
        CREATE TRIGGER trg_task_completed_at BEFORE INSERT OR UPDATE OF status ON field.task
            FOR EACH ROW EXECUTE FUNCTION field.task_completed_at();
        ALTER TABLE field.posting_job ADD COLUMN IF NOT EXISTS last_error text;
        ALTER TABLE field.climb_safety_event DROP CONSTRAINT IF EXISTS climb_safety_event_type_check;
        ALTER TABLE field.climb_safety_event ADD CONSTRAINT climb_safety_event_type_check CHECK (type IN (
            'state_changed', 'harness_confirmed', 'checkpoint_reached', 'check_in', 'climb_safe_activated',
            'climb_safe_released', 'warning_deferred', 'warning_emitted'));
        ALTER TABLE field.site_visit ALTER COLUMN user_id TYPE text USING user_id::text;
        ALTER TABLE field.site_visit ALTER COLUMN override_by TYPE text USING override_by::text;
        ALTER TABLE field.site_visit ALTER COLUMN acked_by TYPE text USING acked_by::text;

        ALTER TABLE field.task_line ADD COLUMN IF NOT EXISTS position text;
        ALTER TABLE field.task_line ADD COLUMN IF NOT EXISTS confirmed_bin text;
        ALTER TABLE field.task_line ADD COLUMN IF NOT EXISTS confirmed_product text;
        ALTER TABLE field.task_line ADD COLUMN IF NOT EXISTS captured_serial text;
        ALTER TABLE field.task_line ADD COLUMN IF NOT EXISTS new_serial text;
        ALTER TABLE field.task_line ADD COLUMN IF NOT EXISTS equipment_no text;

        ALTER TABLE field.pi_document ADD COLUMN IF NOT EXISTS count_round integer NOT NULL DEFAULT 1;
        ALTER TABLE field.pi_document ADD COLUMN IF NOT EXISTS recount_of uuid REFERENCES field.pi_document(id);

        CREATE TABLE field.task_line_confirmation (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE RESTRICT,
            task_id uuid NOT NULL REFERENCES field.task(id) ON DELETE CASCADE,
            task_line_id uuid NOT NULL REFERENCES field.task_line(id) ON DELETE CASCADE,
            kind text NOT NULL CHECK (kind IN ('bin', 'product', 'hu', 'serial')),
            role text CHECK (role IS NULL OR role IN ('old', 'new')),
            code text NOT NULL CHECK (length(code) BETWEEN 1 AND 128),
            source text NOT NULL CHECK (source IN ('scan', 'voice', 'manual')),
            accepted boolean NOT NULL,
            match boolean,
            confirmed_by text NOT NULL,
            device_id uuid,
            created_at timestamptz NOT NULL DEFAULT NOW()
        );
        CREATE INDEX idx_task_line_confirmation_line ON field.task_line_confirmation (tenant_id, task_line_id, created_at);

        CREATE TABLE field.bin_stock (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE RESTRICT,
            storage_bin text NOT NULL,
            material_no text NOT NULL,
            material_id uuid REFERENCES field.material(id) ON DELETE SET NULL,
            quantity numeric(14,3) NOT NULL DEFAULT 0 CHECK (quantity >= 0),
            uom text NOT NULL DEFAULT 'EA',
            updated_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_bin_stock UNIQUE (tenant_id, site_id, storage_bin, material_no)
        );
        CREATE INDEX idx_bin_stock_material ON field.bin_stock (tenant_id, site_id, material_no);
        """
        + _RLS.format(t="task_line_confirmation")
        + _RLS.format(t="bin_stock")
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS field.bin_stock;
        DROP TABLE IF EXISTS field.task_line_confirmation;
        ALTER TABLE field.pi_document DROP COLUMN IF EXISTS recount_of;
        ALTER TABLE field.pi_document DROP COLUMN IF EXISTS count_round;
        ALTER TABLE field.task_line DROP COLUMN IF EXISTS equipment_no;
        ALTER TABLE field.task_line DROP COLUMN IF EXISTS new_serial;
        ALTER TABLE field.task_line DROP COLUMN IF EXISTS captured_serial;
        ALTER TABLE field.task_line DROP COLUMN IF EXISTS confirmed_product;
        ALTER TABLE field.task_line DROP COLUMN IF EXISTS confirmed_bin;
        ALTER TABLE field.task_line DROP COLUMN IF EXISTS position;
        ALTER TABLE field.posting_job DROP COLUMN IF EXISTS last_error;
        DELETE FROM field.climb_safety_event WHERE type = 'climb_safe_released';
        ALTER TABLE field.climb_safety_event DROP CONSTRAINT IF EXISTS climb_safety_event_type_check;
        ALTER TABLE field.climb_safety_event ADD CONSTRAINT climb_safety_event_type_check CHECK (type IN (
            'state_changed', 'harness_confirmed', 'checkpoint_reached', 'check_in', 'climb_safe_activated',
            'warning_deferred', 'warning_emitted'));
        DELETE FROM field.site_visit WHERE user_id !~ '^[0-9a-f-]{36}$'
            OR coalesce(override_by, '00000000-0000-0000-0000-000000000000') !~ '^[0-9a-f-]{36}$'
            OR coalesce(acked_by, '00000000-0000-0000-0000-000000000000') !~ '^[0-9a-f-]{36}$';
        ALTER TABLE field.site_visit ALTER COLUMN acked_by TYPE uuid USING acked_by::uuid;
        ALTER TABLE field.site_visit ALTER COLUMN override_by TYPE uuid USING override_by::uuid;
        ALTER TABLE field.site_visit ALTER COLUMN user_id TYPE uuid USING user_id::uuid;
        DROP TRIGGER IF EXISTS trg_task_completed_at ON field.task;
        DROP FUNCTION IF EXISTS field.task_completed_at();
        ALTER TABLE field.task DROP COLUMN IF EXISTS completed_at;
        ALTER TABLE field.task DROP COLUMN IF EXISTS recount_of;
        ALTER TABLE field.task DROP COLUMN IF EXISTS reason;
        ALTER TABLE field.task DROP COLUMN IF EXISTS subtitle;
        """
    )
