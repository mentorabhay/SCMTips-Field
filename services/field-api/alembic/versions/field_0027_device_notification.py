"""Device Notification Table Migration with Forced RLS (Task T2.046 / FR2.052).

Revision ID: field_0027
Revises: field_0026
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0027"
down_revision = "field_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.device_notification (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            device_id uuid NOT NULL REFERENCES field.device(id) ON DELETE CASCADE,
            event_id text NOT NULL,
            tick_type text NOT NULL,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            is_delivered boolean NOT NULL DEFAULT false,
            expires_at timestamptz NOT NULL DEFAULT (NOW() + interval '24 hours'),
            created_at timestamptz NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_device_notification_lookup
            ON field.device_notification (tenant_id, device_id, event_id);
        """
    )

    op.execute("ALTER TABLE field.device_notification ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE field.device_notification FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON field.device_notification
        AS RESTRICTIVE
        FOR ALL
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS field.device_notification CASCADE;")
