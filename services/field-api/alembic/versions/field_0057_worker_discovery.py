"""Worker tenant discovery without bypassing RLS (C4: a real worker process).

The worker connects as field_worker (NOBYPASSRLS). To know *which* tenants have work it calls
these SECURITY DEFINER functions, which expose only identifiers, never row data:
- field.worker_pending_tenants(): tenants with posting jobs due now
- field.worker_erp_sites(): (tenant_id, site_id, erp_plant, storage locations) of active ERP sites
- field.worker_purge_idempotency(): deletes expired idempotency rows, returns the count

Revision ID: field_0057
Revises: field_0056
"""

from alembic import op

revision = "field_0057"
down_revision = "field_0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION field.worker_pending_tenants() RETURNS SETOF uuid
            LANGUAGE sql STABLE SECURITY DEFINER SET search_path = field, pg_temp AS $$
            SELECT DISTINCT tenant_id FROM field.posting_job WHERE status = 'pending' AND next_attempt_at <= NOW()
        $$;
        CREATE OR REPLACE FUNCTION field.worker_erp_sites()
            RETURNS TABLE (tenant_id uuid, site_id uuid, erp_plant text, storage_locations text[])
            LANGUAGE sql STABLE SECURITY DEFINER SET search_path = field, pg_temp AS $$
            SELECT tenant_id, id, erp_plant, erp_storage_locations FROM field.site
             WHERE erp_plant IS NOT NULL AND status = 'active'
        $$;
        CREATE OR REPLACE FUNCTION field.worker_purge_idempotency() RETURNS integer
            LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = field, pg_temp AS $$
            WITH d AS (DELETE FROM field.idempotency_record WHERE expires_at < NOW() RETURNING 1)
            SELECT count(*)::int FROM d
        $$;
        REVOKE ALL ON FUNCTION field.worker_pending_tenants(), field.worker_erp_sites(),
                               field.worker_purge_idempotency() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION field.worker_pending_tenants(), field.worker_erp_sites(),
                                  field.worker_purge_idempotency() TO field_worker;
        GRANT USAGE ON SCHEMA field TO field_worker;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA field TO field_worker;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA field TO field_worker;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS field.worker_purge_idempotency();
        DROP FUNCTION IF EXISTS field.worker_erp_sites();
        DROP FUNCTION IF EXISTS field.worker_pending_tenants();
        """
    )
