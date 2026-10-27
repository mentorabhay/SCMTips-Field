"""Count Record Table Migration with Forced RLS (Task T2.046 / FR2.050).

Revision ID: field_0025
Revises: field_0024
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0025"
down_revision = "field_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.count_record (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            task_id uuid NOT NULL REFERENCES field.task(id) ON DELETE CASCADE,
            task_line_id uuid NULL REFERENCES field.task_line(id) ON DELETE SET NULL,
            capture_id uuid NULL REFERENCES field.capture(id) ON DELETE SET NULL,
            voice_event_id uuid NULL REFERENCES field.voice_event(id) ON DELETE SET NULL,
            quantity numeric(12,3) NOT NULL,
            unit text NOT NULL DEFAULT 'EA',
            is_reversal boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_count_task_line
            ON field.count_record (tenant_id, task_id, task_line_id);
        """
    )

    op.execute("ALTER TABLE field.count_record ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE field.count_record FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON field.count_record
        AS RESTRICTIVE
        FOR ALL
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS field.count_record CASCADE;")
