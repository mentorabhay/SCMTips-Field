"""M4 F4: goods receipts to the core's feeds (docs/design/M4_CONTRACT.md section 4; handover 01a).

- field.core_feed_delivery(id, tenant_id, site_id, event_id, feed, doc_number, fiscal_year, body, row_count, status,
  attempts, max_attempts, next_attempt_at, last_status, last_error, skip_reason, delivered_at, created_at,
  updated_at): one row per (erp.posted goods-receipt outbox event, feed). ``body`` is the exact JSON array that is
  signed and sent, so every retry sends the same bytes. status pending | delivered | dead | skipped.
  UNIQUE (tenant_id, event_id, feed) makes delivery idempotent on the event id.
- field.worker_core_feed_tenants(lookback): SECURITY DEFINER for the worker (NOBYPASSRLS): tenants with goods
  receipts posted within ``lookback`` that have no delivery rows yet, or with deliveries due now.
- idx_outbox_erp_posted: the worker's scan of erp.posted events.

Forced RLS on the new table: RESTRICTIVE tenant_isolation plus a PERMISSIVE site_scope.

Revision ID: field_0062
Revises: field_0061 (stream M's field_0063 also revises field_0061; the integrator chains them, M4 contract §1)
"""

from alembic import op

revision = "field_0062"
down_revision = "field_0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE field.core_feed_delivery (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            site_id uuid NULL,
            event_id uuid NOT NULL,
            feed text NOT NULL CHECK (feed IN ('inventory', 'open_supply')),
            doc_number text NOT NULL,
            fiscal_year text NOT NULL,
            body text NOT NULL,
            row_count integer NOT NULL DEFAULT 0 CHECK (row_count >= 0),
            status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'delivered', 'dead', 'skipped')),
            attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            max_attempts integer NOT NULL CHECK (max_attempts >= 1),
            next_attempt_at timestamptz NOT NULL DEFAULT NOW(),
            last_status integer NULL,
            last_error text NULL CHECK (last_error IS NULL OR length(last_error) <= 500),
            skip_reason text NULL,
            delivered_at timestamptz NULL,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            updated_at timestamptz NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_core_feed_event UNIQUE (tenant_id, event_id, feed)
        );
        CREATE INDEX idx_core_feed_due ON field.core_feed_delivery (next_attempt_at) WHERE status = 'pending';
        CREATE INDEX idx_outbox_erp_posted ON field.outbox (tenant_id, created_at) WHERE event_type = 'erp.posted';

        ALTER TABLE field.core_feed_delivery ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.core_feed_delivery FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON field.core_feed_delivery AS RESTRICTIVE FOR ALL
            USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
        CREATE POLICY site_scope ON field.core_feed_delivery AS PERMISSIVE FOR ALL
            USING (nullif(current_setting('app.site_ids', true), '') = '*'
                   OR site_id::text = ANY (string_to_array(nullif(current_setting('app.site_ids', true), ''), ',')));
        GRANT SELECT, INSERT, UPDATE, DELETE ON field.core_feed_delivery TO field_app, field_worker;

        CREATE OR REPLACE FUNCTION field.worker_core_feed_tenants(lookback interval) RETURNS SETOF uuid
            LANGUAGE sql STABLE SECURITY DEFINER SET search_path = field, pg_temp AS $$
            SELECT o.tenant_id FROM field.outbox o
             WHERE o.event_type = 'erp.posted' AND o.payload->'data'->>'doc_type' = 'GoodsReceipt'
               AND o.created_at > NOW() - lookback
               AND NOT EXISTS (SELECT 1 FROM field.core_feed_delivery d
                                WHERE d.tenant_id = o.tenant_id AND d.event_id = o.id)
            UNION
            SELECT tenant_id FROM field.core_feed_delivery WHERE status = 'pending' AND next_attempt_at <= NOW()
        $$;
        REVOKE ALL ON FUNCTION field.worker_core_feed_tenants(interval) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION field.worker_core_feed_tenants(interval) TO field_worker;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS field.worker_core_feed_tenants(interval);
        DROP INDEX IF EXISTS field.idx_outbox_erp_posted;
        DROP TABLE IF EXISTS field.core_feed_delivery;
        """
    )
