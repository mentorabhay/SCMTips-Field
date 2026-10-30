"""PI book values, count provenance, damage flags and approval valuation (C3/C4).

- field.pi_book: book quantity and unit price per PI line, held server-side only. The operator
  projection never reads this table (API3.01 / API3.11 "never contains book_qty").
- field.pi_document: site_id, task_id link, planned date, requested_by.
- field.count_record: counted_by, count_no, source (blind count and recount by a different operator).
- field.task_line: damaged_qty, damage_evidence_id.
- field.approval_request: pi_document_id, value_abs, currency, band, counters (SoD), and widened
  approval_type for receipt over-tolerance.

Revision ID: field_0053
Revises: field_0052
"""

from alembic import op

revision = "field_0053"
down_revision = "field_0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.pi_book (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            pi_document_id uuid NOT NULL REFERENCES field.pi_document(id) ON DELETE CASCADE,
            task_line_id uuid NOT NULL REFERENCES field.task_line(id) ON DELETE CASCADE,
            book_qty numeric(14,3) NOT NULL,
            unit_price numeric(14,4) NOT NULL,
            currency text NOT NULL DEFAULT 'INR',
            created_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_pi_book_line UNIQUE (tenant_id, task_line_id)
        );
        ALTER TABLE field.pi_book ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.pi_book FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON field.pi_book AS RESTRICTIVE FOR ALL
            USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
        GRANT SELECT, INSERT, UPDATE, DELETE ON field.pi_book TO field_app, field_worker;

        ALTER TABLE field.pi_document ADD COLUMN IF NOT EXISTS site_id uuid REFERENCES field.site(id);
        ALTER TABLE field.pi_document ADD COLUMN IF NOT EXISTS task_id uuid REFERENCES field.task(id);
        ALTER TABLE field.pi_document ADD COLUMN IF NOT EXISTS planned_count_date date;
        ALTER TABLE field.pi_document ADD COLUMN IF NOT EXISTS requested_by text;

        ALTER TABLE field.count_record ADD COLUMN IF NOT EXISTS counted_by text;
        ALTER TABLE field.count_record ADD COLUMN IF NOT EXISTS count_no integer NOT NULL DEFAULT 1;
        ALTER TABLE field.count_record ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'voice';

        ALTER TABLE field.task_line ADD COLUMN IF NOT EXISTS damaged_qty numeric(12,3) NOT NULL DEFAULT 0;
        ALTER TABLE field.task_line ADD COLUMN IF NOT EXISTS damage_evidence_id uuid;

        ALTER TABLE field.approval_request ADD COLUMN IF NOT EXISTS pi_document_id uuid REFERENCES field.pi_document(id);
        ALTER TABLE field.approval_request ADD COLUMN IF NOT EXISTS value_abs numeric(16,2);
        ALTER TABLE field.approval_request ADD COLUMN IF NOT EXISTS currency text;
        ALTER TABLE field.approval_request ADD COLUMN IF NOT EXISTS band text;
        ALTER TABLE field.approval_request ADD COLUMN IF NOT EXISTS excluded_principals text[] NOT NULL DEFAULT '{}';
        ALTER TABLE field.approval_request DROP CONSTRAINT IF EXISTS approval_request_approval_type_check;
        ALTER TABLE field.approval_request ADD CONSTRAINT approval_request_approval_type_check
            CHECK (approval_type IN ('pi_variance', 'short_pick', 'damage_writeoff', 'manual_reversal',
                                     'tower_mismatch', 'mismatch_decision', 'receipt_over_tolerance'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE field.approval_request DROP CONSTRAINT IF EXISTS approval_request_approval_type_check;
        DELETE FROM field.approval_request WHERE approval_type = 'receipt_over_tolerance';
        ALTER TABLE field.approval_request ADD CONSTRAINT approval_request_approval_type_check
            CHECK (approval_type IN ('pi_variance', 'short_pick', 'damage_writeoff', 'manual_reversal',
                                     'tower_mismatch', 'mismatch_decision'));
        ALTER TABLE field.approval_request DROP COLUMN IF EXISTS excluded_principals;
        ALTER TABLE field.approval_request DROP COLUMN IF EXISTS band;
        ALTER TABLE field.approval_request DROP COLUMN IF EXISTS currency;
        ALTER TABLE field.approval_request DROP COLUMN IF EXISTS value_abs;
        ALTER TABLE field.approval_request DROP COLUMN IF EXISTS pi_document_id;
        ALTER TABLE field.task_line DROP COLUMN IF EXISTS damage_evidence_id;
        ALTER TABLE field.task_line DROP COLUMN IF EXISTS damaged_qty;
        ALTER TABLE field.count_record DROP COLUMN IF EXISTS source;
        ALTER TABLE field.count_record DROP COLUMN IF EXISTS count_no;
        ALTER TABLE field.count_record DROP COLUMN IF EXISTS counted_by;
        ALTER TABLE field.pi_document DROP COLUMN IF EXISTS requested_by;
        ALTER TABLE field.pi_document DROP COLUMN IF EXISTS planned_count_date;
        ALTER TABLE field.pi_document DROP COLUMN IF EXISTS task_id;
        ALTER TABLE field.pi_document DROP COLUMN IF EXISTS site_id;
        DROP TABLE IF EXISTS field.pi_book CASCADE;
        """
    )
