"""erp_document.doc_number / fiscal_year are assigned by the ERP on posting (C4).

A staged document has no ERP number yet. The old code stored the *delivery* number in doc_number
to satisfy NOT NULL, which conflated two identifiers and collided on a second partial receipt
(unique tenant_id, doc_number, fiscal_year). Both columns are nullable until posted; the unique
constraint keeps applying to posted numbers (NULLs never collide).

Revision ID: field_0055
Revises: field_0054
"""

from alembic import op

revision = "field_0055"
down_revision = "field_0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE field.erp_document ALTER COLUMN doc_number DROP NOT NULL;
        ALTER TABLE field.erp_document ALTER COLUMN fiscal_year DROP NOT NULL;
        ALTER TABLE field.erp_document ADD CONSTRAINT erp_document_posted_has_number
            CHECK (status <> 'posted' OR (doc_number IS NOT NULL AND fiscal_year IS NOT NULL));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE field.erp_document DROP CONSTRAINT IF EXISTS erp_document_posted_has_number;
        UPDATE field.erp_document SET doc_number = 'UNPOSTED-' || id::text WHERE doc_number IS NULL;
        UPDATE field.erp_document SET fiscal_year = '0000' WHERE fiscal_year IS NULL;
        ALTER TABLE field.erp_document ALTER COLUMN doc_number SET NOT NULL;
        ALTER TABLE field.erp_document ALTER COLUMN fiscal_year SET NOT NULL;
        """
    )
