"""Physical Inventory Document Table Migration with Forced RLS (Task T3.002 / FR3.065).

Revision ID: field_0033
Revises: field_0032
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0033"
down_revision = "field_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.pi_document (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            doc_number text NOT NULL,
            fiscal_year text NOT NULL,
            plant text NOT NULL,
            storage_location text NOT NULL,
            posting_blocked boolean NOT NULL DEFAULT true,
            freeze_book boolean NOT NULL DEFAULT true,
            status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'counted', 'recount', 'posted', 'cancelled')),
            difference_doc_no text NULL,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            closed_at timestamptz NULL,
            CONSTRAINT uq_pi_doc_tenant_num_year UNIQUE (tenant_id, doc_number, fiscal_year)
        );

        CREATE INDEX IF NOT EXISTS idx_pi_doc_status
            ON field.pi_document (tenant_id, status);

        ALTER TABLE field.pi_document ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.pi_document FORCE ROW LEVEL SECURITY;

        CREATE POLICY tenant_isolation ON field.pi_document
        AS RESTRICTIVE
        FOR ALL
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS field.pi_document CASCADE;
        """
    )
