"""M5 stream X: supplier claims (docs/design/M5_CONTRACT.md section 3).

- field.supplier_claim(id, tenant_id, site_id, look_id, task_id, capture_id, status, lines, text, source, reasons,
  model_calls, created_by, created_at, decision, decision_reason, decided_by, decided_at, confirm_by, confirmed_by,
  confirmed_at, confirm_words, sent_outbox_id, version, updated_at): one claim per look
  (UNIQUE (tenant_id, look_id)), so a second "make a claim" on the same look returns the first claim.
  status draft | pending_confirm | approved | rejected. ``lines`` are computed from the look (never by a model);
  ``text`` is Muse's draft or the template (``source``), ``reasons`` say why the template was used.

Independent of stream V's tables: ``look_id`` and ``capture_id`` are plain uuids (no foreign key to
field.vision_look), so this migration applies with or without V's field_0064 before it. The evidence page reads
everything else from tables that exist since M1-M4 (erp_document, posting_job, outbox, capture_evidence,
voice_event, assistant_turn) and adds no copies of them.

Forced RLS: RESTRICTIVE tenant_isolation plus a PERMISSIVE site_scope, as every M3/M4 table.

Revision ID: field_0065
Revises: field_0062 (until stream V's field_0064 lands; the integrator re-points this to field_0064, M5 contract
section 5)
"""

from alembic import op

revision = "field_0065"
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
        CREATE TABLE field.supplier_claim (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE RESTRICT,
            look_id uuid NOT NULL,
            task_id uuid NULL,
            capture_id uuid NULL,
            status text NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'pending_confirm', 'approved', 'rejected')),
            lines jsonb NOT NULL CHECK (jsonb_typeof(lines) = 'array' AND jsonb_array_length(lines) >= 1),
            text text NOT NULL CHECK (length(text) BETWEEN 1 AND 4000),
            source text NOT NULL CHECK (source IN ('model', 'template')),
            reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
            model_calls jsonb NOT NULL DEFAULT '[]'::jsonb,
            created_by text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            decision text NULL CHECK (decision IS NULL OR decision IN ('approve', 'reject')),
            decision_reason text NULL CHECK (decision_reason IS NULL OR length(decision_reason) <= 500),
            decided_by text NULL,
            decided_at timestamptz NULL,
            confirm_by timestamptz NULL,
            confirmed_by text NULL,
            confirmed_at timestamptz NULL,
            confirm_words text NULL CHECK (confirm_words IS NULL OR length(confirm_words) <= 500),
            sent_outbox_id uuid NULL,
            version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
            updated_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_supplier_claim_look UNIQUE (tenant_id, look_id),
            CHECK (status <> 'pending_confirm' OR (decision IS NOT NULL AND confirm_by IS NOT NULL)),
            CHECK (status NOT IN ('approved', 'rejected') OR confirmed_at IS NOT NULL)
        );
        CREATE INDEX idx_supplier_claim_status ON field.supplier_claim (tenant_id, status, created_at);
        CREATE INDEX idx_supplier_claim_task ON field.supplier_claim (tenant_id, task_id) WHERE task_id IS NOT NULL;
        """
        + _RLS.format(t="supplier_claim")
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS field.supplier_claim;")
