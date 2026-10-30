"""One ERP document per voice confirm turn (API2.14 / FR2.055) (C4).

Revision ID: field_0056
Revises: field_0055
"""

from alembic import op

revision = "field_0056"
down_revision = "field_0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_erp_document_post_voice_event"
        " ON field.erp_document (tenant_id, (payload->>'post_voice_event_id'))"
        " WHERE payload ? 'post_voice_event_id'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS field.uq_erp_document_post_voice_event")
