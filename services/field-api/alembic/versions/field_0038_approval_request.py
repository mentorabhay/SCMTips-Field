"""Approval Request Table Migration with Forced RLS (Task T3.002 / FR3.065).

Revision ID: field_0038
Revises: field_0037
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0038"
down_revision = "field_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.approval_request (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            task_id uuid NOT NULL REFERENCES field.task(id) ON DELETE CASCADE,
            approval_type text NOT NULL CHECK (approval_type IN ('pi_variance', 'short_pick', 'damage_writeoff', 'manual_reversal')),
            threshold_val numeric(12,2) NOT NULL DEFAULT 0.00,
            status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
            requested_by text NOT NULL,
            approved_by text NULL,
            reason text NULL,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            decided_at timestamptz NULL
        );

        CREATE INDEX IF NOT EXISTS idx_approval_status
            ON field.approval_request (tenant_id, status);
        CREATE INDEX IF NOT EXISTS idx_approval_task
            ON field.approval_request (tenant_id, task_id);

        ALTER TABLE field.approval_request ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.approval_request FORCE ROW LEVEL SECURITY;

        CREATE POLICY tenant_isolation ON field.approval_request
        AS RESTRICTIVE FOR ALL
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS field.approval_request CASCADE;
        """
    )
