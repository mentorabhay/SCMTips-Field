"""Phase 4 Climb Safety Events and Lone Worker Migration with Forced RLS (Task T4.044, T4.045 / FR4.038 - FR4.045 / API4.15).

Revision ID: field_0047
Revises: field_0046
Create Date: 2026-10-28
"""

from alembic import op

revision = "field_0047"
down_revision = "field_0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add lone-worker altitude and acknowledgment columns to field.site_visit
    op.execute(
        """
        ALTER TABLE field.site_visit
            ADD COLUMN IF NOT EXISTS last_altitude_m numeric(6, 2) NULL,
            ADD COLUMN IF NOT EXISTS last_tower_fl text NULL,
            ADD COLUMN IF NOT EXISTS acked_at timestamptz NULL,
            ADD COLUMN IF NOT EXISTS acked_by uuid NULL,
            ADD COLUMN IF NOT EXISTS ack_notes text NULL;

        CREATE INDEX IF NOT EXISTS idx_site_visit_active_status
            ON field.site_visit (tenant_id, status)
            WHERE status IN ('checked_in', 'on_structure', 'overdue', 'escalated');
        """
    )

    # 2. Create field.climb_safety_event table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.climb_safety_event (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            visit_id uuid NOT NULL REFERENCES field.site_visit(id) ON DELETE CASCADE,
            device_seq integer NOT NULL,
            type text NOT NULL CHECK (type IN (
                'state_changed', 'harness_confirmed', 'checkpoint_reached',
                'check_in', 'climb_safe_activated', 'warning_deferred', 'warning_emitted'
            )),
            altitude_m numeric(6, 2) NULL,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            occurred_at timestamptz NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_climb_event_visit_seq UNIQUE (tenant_id, visit_id, device_seq)
        );

        CREATE INDEX IF NOT EXISTS idx_climb_safety_visit_seq
            ON field.climb_safety_event (tenant_id, visit_id, device_seq);
        CREATE INDEX IF NOT EXISTS idx_climb_safety_type
            ON field.climb_safety_event (tenant_id, type, occurred_at DESC);

        ALTER TABLE field.climb_safety_event ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.climb_safety_event FORCE ROW LEVEL SECURITY;

        CREATE POLICY tenant_isolation ON field.climb_safety_event
            AS RESTRICTIVE
            USING (tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), NULLIF(current_setting('app.current_tenant_id', true), ''))::uuid)
            WITH CHECK (tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), NULLIF(current_setting('app.current_tenant_id', true), ''))::uuid);

        CREATE POLICY allow_all ON field.climb_safety_event
            FOR ALL
            USING (true)
            WITH CHECK (true);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS field.climb_safety_event CASCADE;

        ALTER TABLE field.site_visit
            DROP COLUMN IF EXISTS ack_notes,
            DROP COLUMN IF EXISTS acked_by,
            DROP COLUMN IF EXISTS acked_at,
            DROP COLUMN IF EXISTS last_tower_fl,
            DROP COLUMN IF EXISTS last_altitude_m;
        """
    )
