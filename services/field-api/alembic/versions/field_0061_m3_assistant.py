"""M3 Field Assistant records (docs/design/M3_CONTRACT.md §4) and the Meta Model API in the budget guard.

- field.assistant_session(id, tenant_id, site_id, principal_id, device_id, mode, started_at, ended_at) plus
  ``dialog`` (the open rules-mode dialog, e.g. the sandbox "What is it?" / "How many?" questions) and
  ``last_turn_at``.
- field.assistant_turn(id, session_id, at, event, heard, said, actions, tool_calls, code, photo_ref, ai, cost_usd,
  latency_ms) plus tenant_id / site_id (RLS), ``task_id`` (the job the turn was about; links the session to the
  SAP documents of its jobs) and ``purged_at`` (set when the 30-day retention cleared heard / said / photo).
- field.worker_purge_assistant_content(days): SECURITY DEFINER for the worker (NOBYPASSRLS): clears heard,
  said, photo_ref and tool-call arguments of turns older than ``days``; returns the photo refs that no turn uses
  any more, so the worker can delete the files.
- ops.ai_usage: provider ``meta`` allowed; cached_input_tokens recorded.

Both new tables have forced RLS: RESTRICTIVE tenant_isolation plus a PERMISSIVE site_scope.

Revision ID: field_0061
Revises: field_0059 (the integrator re-points this to field_0060 at merge, M3 contract §1)
"""

from alembic import op

revision = "field_0061"
down_revision = "field_0060"
branch_labels = None
depends_on = None

_RLS = """
ALTER TABLE field.{t} ENABLE ROW LEVEL SECURITY;
ALTER TABLE field.{t} FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON field.{t} AS RESTRICTIVE FOR ALL
    USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY site_scope ON field.{t} AS PERMISSIVE FOR ALL
    USING (nullif(current_setting('app.site_ids', true), '') = '*'
           OR site_id::text = ANY (string_to_array(nullif(current_setting('app.site_ids', true), ''), ',')));
GRANT SELECT, INSERT, UPDATE, DELETE ON field.{t} TO field_app, field_worker;
"""

EVENTS = ("session_start", "utterance", "scan", "unknown_code", "photo", "step_done", "pause", "resume", "session_end")


def upgrade() -> None:
    events = ", ".join(f"'{e}'" for e in EVENTS)
    op.execute(
        f"""
        CREATE TABLE field.assistant_session (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE RESTRICT,
            principal_id text NOT NULL,
            device_id uuid,
            mode text NOT NULL DEFAULT 'production' CHECK (mode IN ('production', 'sandbox')),
            started_at timestamptz NOT NULL DEFAULT NOW(),
            ended_at timestamptz,
            last_turn_at timestamptz NOT NULL DEFAULT NOW(),
            dialog jsonb,
            CHECK (ended_at IS NULL OR ended_at >= started_at)
        );
        CREATE INDEX idx_assistant_session_site ON field.assistant_session (tenant_id, site_id, started_at DESC);

        CREATE TABLE field.assistant_turn (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            site_id uuid NOT NULL REFERENCES field.site(id) ON DELETE RESTRICT,
            session_id uuid NOT NULL REFERENCES field.assistant_session(id) ON DELETE CASCADE,
            at timestamptz NOT NULL DEFAULT NOW(),
            event text NOT NULL CHECK (event IN ({events})),
            heard text CHECK (heard IS NULL OR length(heard) <= 2000),
            said text,
            actions jsonb NOT NULL DEFAULT '[]'::jsonb,
            tool_calls jsonb NOT NULL DEFAULT '[]'::jsonb,
            code text CHECK (code IS NULL OR length(code) <= 128),
            photo_ref text,
            ai text NOT NULL CHECK (ai IN ('model', 'rules')),
            cost_usd numeric(12, 6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
            latency_ms integer NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),
            task_id uuid,
            purged_at timestamptz
        );
        CREATE INDEX idx_assistant_turn_session ON field.assistant_turn (tenant_id, session_id, at);
        CREATE INDEX idx_assistant_turn_retention ON field.assistant_turn (at) WHERE purged_at IS NULL;

        CREATE OR REPLACE FUNCTION field.worker_purge_assistant_content(p_days integer) RETURNS SETOF text
            LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = field, pg_temp AS $$
        DECLARE
            refs text[];
        BEGIN
            IF p_days IS NULL OR p_days < 1 THEN
                RAISE EXCEPTION 'retention days must be >= 1';
            END IF;
            WITH old AS (
                SELECT id, photo_ref FROM field.assistant_turn
                 WHERE purged_at IS NULL AND at < NOW() - make_interval(days => p_days)
                 FOR UPDATE
            ), upd AS (
                UPDATE field.assistant_turn t
                   SET heard = NULL, said = NULL, photo_ref = NULL, purged_at = NOW(),
                       tool_calls = COALESCE((SELECT jsonb_agg(jsonb_build_object('name', e->>'name'))
                                                FROM jsonb_array_elements(t.tool_calls) e), '[]'::jsonb)
                  FROM old WHERE t.id = old.id
                RETURNING old.photo_ref
            )
            SELECT array_agg(DISTINCT photo_ref) INTO refs FROM upd WHERE photo_ref IS NOT NULL;
            RETURN QUERY
                SELECT r FROM unnest(COALESCE(refs, '{{}}'::text[])) r
                 WHERE NOT EXISTS (SELECT 1 FROM field.assistant_turn t2 WHERE t2.photo_ref = r);
        END $$;
        REVOKE ALL ON FUNCTION field.worker_purge_assistant_content(integer) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION field.worker_purge_assistant_content(integer) TO field_worker;

        ALTER TABLE ops.ai_usage DROP CONSTRAINT IF EXISTS ai_usage_provider_check;
        ALTER TABLE ops.ai_usage ADD CONSTRAINT ai_usage_provider_check
            CHECK (provider IN ('llama', 'baseten', 'meta'));
        ALTER TABLE ops.ai_usage ADD COLUMN IF NOT EXISTS cached_input_tokens integer
            CHECK (cached_input_tokens IS NULL OR cached_input_tokens >= 0);
        """
        + _RLS.format(t="assistant_session")
        + _RLS.format(t="assistant_turn")
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE ops.ai_usage DROP COLUMN IF EXISTS cached_input_tokens;
        DELETE FROM ops.ai_usage WHERE provider = 'meta';
        ALTER TABLE ops.ai_usage DROP CONSTRAINT IF EXISTS ai_usage_provider_check;
        ALTER TABLE ops.ai_usage ADD CONSTRAINT ai_usage_provider_check CHECK (provider IN ('llama', 'baseten'));
        DROP FUNCTION IF EXISTS field.worker_purge_assistant_content(integer);
        DROP TABLE IF EXISTS field.assistant_turn;
        DROP TABLE IF EXISTS field.assistant_session;
        """
    )
