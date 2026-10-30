"""ops schema: AI spend ledger (budget guard, A-02) and service heartbeats (API1.13 real status).

ops.* is system-level (not tenant data), so it is not under tenant RLS; access is by grant:
- field_app may read heartbeats and read/insert/update ai_usage (the budget guard runs in field-api)
- field_worker may upsert its heartbeat

Revision ID: field_0058
Revises: field_0057
"""

from alembic import op

revision = "field_0058"
down_revision = "field_0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE SCHEMA IF NOT EXISTS ops;
        CREATE TABLE ops.ai_usage (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            provider text NOT NULL CHECK (provider IN ('llama', 'baseten')),
            model text NOT NULL,
            purpose text NOT NULL,
            status text NOT NULL CHECK (status IN ('reserved', 'settled', 'failed')),
            reserved_usd numeric(12, 6) NOT NULL CHECK (reserved_usd >= 0),
            cost_usd numeric(12, 6) CHECK (cost_usd >= 0),
            input_tokens integer,
            output_tokens integer,
            tenant_id uuid,
            request_id text,
            created_at timestamptz NOT NULL DEFAULT NOW(),
            settled_at timestamptz,
            CHECK (status = 'reserved' OR cost_usd IS NOT NULL)
        );
        CREATE INDEX ai_usage_provider_created ON ops.ai_usage (provider, created_at);
        CREATE TABLE ops.service_heartbeat (
            service text PRIMARY KEY,
            instance text NOT NULL,
            beat_at timestamptz NOT NULL DEFAULT NOW(),
            details jsonb NOT NULL DEFAULT '{}'::jsonb
        );
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'field_app') THEN
                GRANT USAGE ON SCHEMA ops TO field_app;
                GRANT SELECT, INSERT, UPDATE ON ops.ai_usage TO field_app;
                GRANT SELECT ON ops.service_heartbeat TO field_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'field_worker') THEN
                GRANT USAGE ON SCHEMA ops TO field_worker;
                GRANT SELECT, INSERT, UPDATE ON ops.service_heartbeat TO field_worker;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE ops.service_heartbeat; DROP TABLE ops.ai_usage; DROP SCHEMA ops;")
