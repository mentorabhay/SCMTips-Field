"""M5 vision look, flagged receipt quantities and the two test cases (docs/design/M5_CONTRACT.md §1, §2; A-06).

- field.vision_look: one look at a capture (POST /v1/vision/looks): the instances the models found, the
  deterministic counts / pack / expiry check, the proposal and the spoken ``say``, the model calls, and the ERP
  document a receipt with this look was posted in (``erp_document_id``, set when the post is staged). The label text
  the model read (``raw_labels``, {n: text}) is kept 30 days like assistant turns, then cleared by
  field.worker_purge_vision_raw(days) (``raw_purged_at``). Unique (tenant_id, idempotency_key).
- field.vision_case_line: what a test-case delivery line expects beyond its quantity (C1 grocery: pieces per unit;
  C2 pharmacy: the expiry window), and the noun the look counts ("pack", "box").
- field.task_line.flag_qty: units of a received line posted to the quality storage location (101 to 101Q) instead
  of unrestricted stock; 0 for every line not posted with a look (the M4 receipt is unchanged).

Both new tables have forced RLS: RESTRICTIVE tenant_isolation plus a PERMISSIVE site_scope (as field_0061).

Revision ID: field_0064_m5_vision
Revises: field_0062
"""

from alembic import op

revision = "field_0064_m5_vision"
down_revision = "field_0062"
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
        CREATE TABLE field.vision_look (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE RESTRICT,
            task_id uuid NOT NULL REFERENCES field.task(id) ON DELETE CASCADE,
            line_id uuid REFERENCES field.task_line(id) ON DELETE SET NULL,
            capture_id uuid NOT NULL,
            "case" text NOT NULL CHECK ("case" IN ('grocery', 'pharmacy', 'generic')),
            object text NOT NULL CHECK (length(object) BETWEEN 1 AND 40),
            source text NOT NULL CHECK (source IN ('model', 'partial', 'rules')),
            idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 255),
            principal_id text NOT NULL,
            device_id uuid,
            image jsonb NOT NULL,
            instances jsonb NOT NULL DEFAULT '[]'::jsonb,
            raw_labels jsonb,
            counts jsonb NOT NULL,
            pack jsonb,
            expiry jsonb,
            proposal jsonb NOT NULL,
            say text NOT NULL,
            models jsonb NOT NULL DEFAULT '[]'::jsonb,
            reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
            cost_usd numeric(12, 6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
            latency_ms integer NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),
            erp_document_id uuid REFERENCES field.erp_document(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            raw_purged_at timestamptz,
            CONSTRAINT uq_vision_look_idempotency UNIQUE (tenant_id, idempotency_key)
        );
        CREATE INDEX idx_vision_look_task ON field.vision_look (tenant_id, task_id, created_at DESC);
        CREATE INDEX idx_vision_look_document ON field.vision_look (erp_document_id) WHERE erp_document_id IS NOT NULL;
        CREATE INDEX idx_vision_look_retention ON field.vision_look (created_at) WHERE raw_purged_at IS NULL;

        CREATE TABLE field.vision_case_line (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE RESTRICT,
            task_id uuid NOT NULL REFERENCES field.task(id) ON DELETE CASCADE,
            task_line_id uuid NOT NULL REFERENCES field.task_line(id) ON DELETE CASCADE,
            "case" text NOT NULL CHECK ("case" IN ('grocery', 'pharmacy')),
            object text NOT NULL CHECK (length(object) BETWEEN 1 AND 40),
            expected_pieces_per_unit integer CHECK (expected_pieces_per_unit IS NULL OR expected_pieces_per_unit > 0),
            expiry_window_days integer CHECK (expiry_window_days IS NULL OR expiry_window_days BETWEEN 0 AND 3650),
            created_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_vision_case_line UNIQUE (tenant_id, task_line_id)
        );
        CREATE INDEX idx_vision_case_task ON field.vision_case_line (tenant_id, task_id);

        ALTER TABLE field.task_line ADD COLUMN IF NOT EXISTS flag_qty numeric(12, 3) NOT NULL DEFAULT 0
            CHECK (flag_qty >= 0);

        CREATE OR REPLACE FUNCTION field.worker_purge_vision_raw(p_days integer) RETURNS integer
            LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = field, pg_temp AS $$
        DECLARE
            n integer;
        BEGIN
            IF p_days IS NULL OR p_days < 1 THEN
                RAISE EXCEPTION 'retention days must be >= 1';
            END IF;
            UPDATE field.vision_look SET raw_labels = NULL, raw_purged_at = NOW()
             WHERE raw_purged_at IS NULL AND created_at < NOW() - make_interval(days => p_days);
            GET DIAGNOSTICS n = ROW_COUNT;
            RETURN n;
        END $$;
        REVOKE ALL ON FUNCTION field.worker_purge_vision_raw(integer) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION field.worker_purge_vision_raw(integer) TO field_worker;
        """
        + _RLS.format(t="vision_look")
        + _RLS.format(t="vision_case_line")
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS field.worker_purge_vision_raw(integer);
        ALTER TABLE field.task_line DROP COLUMN IF EXISTS flag_qty;
        DROP TABLE IF EXISTS field.vision_case_line;
        DROP TABLE IF EXISTS field.vision_look;
        """
    )
