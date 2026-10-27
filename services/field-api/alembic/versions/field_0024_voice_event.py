"""Voice Event Table Migration with Forced RLS (Task T2.046 / FR2.038).

Revision ID: field_0024
Revises: field_0023
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0024"
down_revision = "field_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.voice_event (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            device_id uuid NOT NULL REFERENCES field.device(id) ON DELETE CASCADE,
            task_id uuid NULL REFERENCES field.task(id) ON DELETE SET NULL,
            capture_id uuid NULL REFERENCES field.capture(id) ON DELETE SET NULL,
            transcript text NOT NULL,
            confidence numeric(4,3) NOT NULL,
            intent text NOT NULL,
            is_accepted boolean NOT NULL DEFAULT true,
            locale text NOT NULL DEFAULT 'en-US',
            client_timestamp timestamptz NOT NULL DEFAULT NOW(),
            created_at timestamptz NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_voice_task_intent
            ON field.voice_event (tenant_id, task_id, intent, created_at);
        """
    )

    op.execute("ALTER TABLE field.voice_event ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE field.voice_event FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON field.voice_event
        AS RESTRICTIVE
        FOR ALL
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS field.voice_event CASCADE;")
