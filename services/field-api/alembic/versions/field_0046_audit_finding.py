"""Audit Finding and Exception Case Migration with Forced RLS (Task T4.015, T4.016 / FR4.019, FR4.022, FR4.023).

Revision ID: field_0046
Revises: field_0045
Create Date: 2026-10-28
"""

from alembic import op

revision = "field_0046"
down_revision = "field_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create field.exception_case table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.exception_case (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE RESTRICT,
            type text NOT NULL,
            dedupe_key text NOT NULL,
            status text NOT NULL DEFAULT 'open',
            severity text NOT NULL DEFAULT 'S3' CHECK (severity IN ('S1', 'S2', 'S3', 'S4')),
            severity_override jsonb NULL,
            subject jsonb NOT NULL DEFAULT '{}'::jsonb,
            facts jsonb NOT NULL DEFAULT '{}'::jsonb,
            value_at_risk numeric(18,2) NULL,
            currency char(3) NOT NULL DEFAULT 'USD',
            rule_id text NOT NULL,
            rule_version int NOT NULL DEFAULT 1,
            assignee text NULL,
            occurrence_count int NOT NULL DEFAULT 1,
            ack_due_at timestamptz NOT NULL DEFAULT (NOW() + interval '4 hours'),
            resolve_due_at timestamptz NOT NULL DEFAULT (NOW() + interval '24 hours'),
            acked_at timestamptz NULL,
            resolved_at timestamptz NULL,
            closed_at timestamptz NULL,
            close_reason text NULL,
            reopen_count int NOT NULL DEFAULT 0,
            previous_case_id uuid NULL REFERENCES field.exception_case(id),
            exposure_match_ids uuid[] NOT NULL DEFAULT '{}',
            bundle_version int NOT NULL DEFAULT 0,
            version int NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT NOW()
        );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_exception_case_dedupe
            ON field.exception_case (tenant_id, dedupe_key)
            WHERE status <> 'closed';

        CREATE INDEX IF NOT EXISTS idx_exception_case_sla
            ON field.exception_case (tenant_id, site_id, status, resolve_due_at);

        ALTER TABLE field.exception_case ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.exception_case FORCE ROW LEVEL SECURITY;

        CREATE POLICY tenant_isolation ON field.exception_case
            FOR ALL
            USING (tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), NULLIF(current_setting('app.current_tenant_id', true), ''))::uuid)
            WITH CHECK (tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), NULLIF(current_setting('app.current_tenant_id', true), ''))::uuid);
        """
    )

    # 2. Create field.audit_finding table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS field.audit_finding (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            task_id uuid NOT NULL REFERENCES field.task(id) ON DELETE CASCADE,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE RESTRICT,
            tower_location_id uuid NULL REFERENCES field.location(id) ON DELETE SET NULL,
            location_id uuid NULL REFERENCES field.location(id) ON DELETE SET NULL,
            task_line_id uuid NULL REFERENCES field.task_line(id) ON DELETE SET NULL,
            capture_id uuid NULL REFERENCES field.capture(id) ON DELETE SET NULL,
            class text NOT NULL CHECK (class IN ('matched', 'serial_mismatch', 'tower_only', 'erp_only', 'misplaced')),
            expected_serial text NULL,
            found_serial text NULL,
            reason text NULL CHECK (reason IS NULL OR reason IN ('not_found', 'removed_by_other', 'inaccessible')),
            exception_case_id uuid NULL REFERENCES field.exception_case(id) ON DELETE SET NULL,
            decision text NULL CHECK (decision IS NULL OR decision IN ('re_capture', 'accept_erp', 'update_erp', 'record_move', 'waived')),
            decided_by text NULL,
            approval_ref text NULL,
            status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'awaiting_approval', 'resolved')),
            dedupe_key text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            updated_at timestamptz NOT NULL DEFAULT NOW()
        );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_audit_finding_dedupe
            ON field.audit_finding (tenant_id, dedupe_key)
            WHERE status <> 'resolved';

        CREATE INDEX IF NOT EXISTS idx_audit_finding_query
            ON field.audit_finding (tenant_id, site_id, status, class);

        CREATE INDEX IF NOT EXISTS idx_audit_finding_task
            ON field.audit_finding (tenant_id, task_id);

        ALTER TABLE field.audit_finding ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.audit_finding FORCE ROW LEVEL SECURITY;

        CREATE POLICY tenant_isolation ON field.audit_finding
            FOR ALL
            USING (tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), NULLIF(current_setting('app.current_tenant_id', true), ''))::uuid)
            WITH CHECK (tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), NULLIF(current_setting('app.current_tenant_id', true), ''))::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS field.audit_finding CASCADE;")
    op.execute("DROP TABLE IF EXISTS field.exception_case CASCADE;")
