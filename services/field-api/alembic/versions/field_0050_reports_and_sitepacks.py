"""Phase 4 Site Pack, Audit Reports & Queue Hold Migration (WS4.8 / Tasks T4.060, T4.061, T4.064).

Revision ID: field_0050
Revises: field_0049
Create Date: 2026-10-28
"""

from alembic import op

revision = "field_0050"
down_revision = "field_0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- 1. Audit Report table (PDF/CSV exports with authenticated evidence links and 14-day retention)
        CREATE TABLE IF NOT EXISTS field.audit_report (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            task_id uuid NOT NULL,
            format text NOT NULL CHECK (format IN ('pdf', 'csv', 'json')),
            status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'ready', 'failed')),
            storage_path text NULL,
            file_size_bytes bigint NULL,
            sha256_hash text NULL,
            download_url text NULL,
            error_message text NULL,
            expires_at timestamptz NOT NULL DEFAULT (NOW() + interval '14 days'),
            created_by text NULL,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            completed_at timestamptz NULL
        );

        CREATE INDEX IF NOT EXISTS idx_audit_report_tenant_task
            ON field.audit_report (tenant_id, task_id, status);

        ALTER TABLE field.audit_report ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.audit_report FORCE ROW LEVEL SECURITY;

        CREATE POLICY audit_report_tenant_isolation ON field.audit_report
            AS PERMISSIVE FOR ALL
            USING (tenant_id = (COALESCE(NULLIF(current_setting('app.tenant_id'::text, true), ''::text), NULLIF(current_setting('app.current_tenant_id'::text, true), ''::text)))::uuid)
            WITH CHECK (tenant_id = (COALESCE(NULLIF(current_setting('app.tenant_id'::text, true), ''::text), NULLIF(current_setting('app.current_tenant_id'::text, true), ''::text)))::uuid);


        -- 2. Site Pack table (offline manifests, snapshot versions, chunks metadata, <= 60 MB)
        CREATE TABLE IF NOT EXISTS field.site_pack (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE CASCADE,
            snapshot_version text NOT NULL,
            etag text NOT NULL,
            size_bytes bigint NOT NULL DEFAULT 0,
            manifest_data jsonb NOT NULL,
            expires_at timestamptz NOT NULL DEFAULT (NOW() + interval '14 days'),
            created_at timestamptz NOT NULL DEFAULT NOW()
        );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_site_pack_tenant_site_snap
            ON field.site_pack (tenant_id, site_id, snapshot_version);

        ALTER TABLE field.site_pack ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.site_pack FORCE ROW LEVEL SECURITY;

        CREATE POLICY site_pack_tenant_isolation ON field.site_pack
            AS PERMISSIVE FOR ALL
            USING (tenant_id = (COALESCE(NULLIF(current_setting('app.tenant_id'::text, true), ''::text), NULLIF(current_setting('app.current_tenant_id'::text, true), ''::text)))::uuid)
            WITH CHECK (tenant_id = (COALESCE(NULLIF(current_setting('app.tenant_id'::text, true), ''::text), NULLIF(current_setting('app.current_tenant_id'::text, true), ''::text)))::uuid);


        -- 3. Queue Hold table (holds individual tower posting queues on replay conflict - TC4.152)
        CREATE TABLE IF NOT EXISTS field.queue_hold (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            queue_key text NOT NULL,
            tower_fl text NOT NULL,
            is_held boolean NOT NULL DEFAULT true,
            conflict_reason text NOT NULL,
            exception_case_id uuid NULL,
            held_at timestamptz NOT NULL DEFAULT NOW(),
            released_at timestamptz NULL,
            released_by text NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_queue_hold_active
            ON field.queue_hold (tenant_id, queue_key)
            WHERE is_held = true;

        ALTER TABLE field.queue_hold ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.queue_hold FORCE ROW LEVEL SECURITY;

        CREATE POLICY queue_hold_tenant_isolation ON field.queue_hold
            AS PERMISSIVE FOR ALL
            USING (tenant_id = (COALESCE(NULLIF(current_setting('app.tenant_id'::text, true), ''::text), NULLIF(current_setting('app.current_tenant_id'::text, true), ''::text)))::uuid)
            WITH CHECK (tenant_id = (COALESCE(NULLIF(current_setting('app.tenant_id'::text, true), ''::text), NULLIF(current_setting('app.current_tenant_id'::text, true), ''::text)))::uuid);

        -- Allow app roles access to newly created tables
        GRANT ALL ON field.audit_report TO field_app;
        GRANT ALL ON field.site_pack TO field_app;
        GRANT ALL ON field.queue_hold TO field_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS field.queue_hold CASCADE;
        DROP TABLE IF EXISTS field.site_pack CASCADE;
        DROP TABLE IF EXISTS field.audit_report CASCADE;
        """
    )
