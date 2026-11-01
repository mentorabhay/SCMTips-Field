"""M5-W01 "Try a look" for judges: a vision look on an uploaded photo with no task, no capture, no posting, no claim.

field.vision_look gains:
- ``kind`` ('task' default: every earlier look; 'try': a look from the console's /try page, POST /v1/try/looks);
- ``site_id``, ``task_id`` and ``capture_id`` become nullable, for try looks only (ck_vision_look_kind keeps them
  required on task looks; a try look has no task, line, capture or ERP document);
- ``photo_uri`` / ``photo_sha256``: the try photo as stored (faces pixelated server-side before storing and before any
  model call), in the try photo store (FIELD_TRY_PHOTO_DIR), not the capture crop store;
- ``photo_expires_at`` (created + 24 h) and ``photo_purged_at``: try photos and their label text are kept 24 hours,
  then field.worker_purge_try_looks() (SECURITY DEFINER, worker role) clears photo_uri and raw_labels and returns the
  photo files no look refers to any more, which the worker deletes. The rest of the row (counts, model calls, cost)
  stays.
- policy try_scope (PERMISSIVE): a try look has no site, so the site_scope policy cannot match it; try looks are
  visible within the tenant (RESTRICTIVE tenant_isolation unchanged) and the API reads only the caller's own.

field.try_look_slot: one row per accepted try look (tenant, principal, time), the rolling-hour rate limit (10 per
principal, FIELD-TRY-429-RATE); rows older than a day are deleted by the same purge. Forced RLS: RESTRICTIVE
tenant_isolation plus a PERMISSIVE tenant-wide policy (no site).

Revision ID: field_0067_m5_try
Revises: field_0066_m5_look_stage
"""

from alembic import op

revision = "field_0067_m5_try"
down_revision = "field_0066_m5_look_stage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE field.vision_look
            ALTER COLUMN site_id DROP NOT NULL,
            ALTER COLUMN task_id DROP NOT NULL,
            ALTER COLUMN capture_id DROP NOT NULL,
            ADD COLUMN kind text NOT NULL DEFAULT 'task' CHECK (kind IN ('task', 'try')),
            ADD COLUMN photo_uri text,
            ADD COLUMN photo_sha256 text CHECK (photo_sha256 IS NULL OR photo_sha256 ~ '^[0-9a-f]{64}$'),
            ADD COLUMN photo_expires_at timestamptz,
            ADD COLUMN photo_purged_at timestamptz,
            ADD CONSTRAINT ck_vision_look_kind CHECK (
                (kind = 'task' AND site_id IS NOT NULL AND task_id IS NOT NULL AND capture_id IS NOT NULL
                     AND photo_uri IS NULL AND photo_expires_at IS NULL)
                OR (kind = 'try' AND site_id IS NULL AND task_id IS NULL AND line_id IS NULL AND capture_id IS NULL
                     AND erp_document_id IS NULL AND photo_expires_at IS NOT NULL));
        CREATE INDEX idx_vision_look_try_principal ON field.vision_look (tenant_id, principal_id, created_at DESC)
            WHERE kind = 'try';
        CREATE INDEX idx_vision_look_try_expiry ON field.vision_look (photo_expires_at)
            WHERE kind = 'try' AND photo_purged_at IS NULL;
        CREATE POLICY try_scope ON field.vision_look AS PERMISSIVE FOR ALL
            USING (kind = 'try' AND site_id IS NULL)
            WITH CHECK (kind = 'try' AND site_id IS NULL);

        CREATE TABLE field.try_look_slot (
            id uuid PRIMARY KEY DEFAULT field.uuid_generate_v7(),
            tenant_id uuid NOT NULL,
            principal_id text NOT NULL CHECK (length(principal_id) BETWEEN 1 AND 255),
            created_at timestamptz NOT NULL DEFAULT NOW()
        );
        CREATE INDEX idx_try_look_slot_principal ON field.try_look_slot (tenant_id, principal_id, created_at DESC);
        ALTER TABLE field.try_look_slot ENABLE ROW LEVEL SECURITY;
        ALTER TABLE field.try_look_slot FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON field.try_look_slot AS RESTRICTIVE FOR ALL
            USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
        CREATE POLICY tenant_rows ON field.try_look_slot AS PERMISSIVE FOR ALL USING (true) WITH CHECK (true);
        GRANT SELECT, INSERT, DELETE ON field.try_look_slot TO field_app, field_worker;

        CREATE OR REPLACE FUNCTION field.worker_purge_try_looks() RETURNS TABLE (photo_uri text)
            LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = field, pg_temp AS $$
        DECLARE
            uris text[];
        BEGIN
            SELECT array_agg(DISTINCT l.photo_uri) INTO uris FROM field.vision_look l
             WHERE l.kind = 'try' AND l.photo_purged_at IS NULL AND l.photo_expires_at < NOW()
               AND l.photo_uri IS NOT NULL;
            UPDATE field.vision_look l
               SET photo_uri = NULL, photo_purged_at = NOW(), raw_labels = NULL,
                   raw_purged_at = COALESCE(l.raw_purged_at, NOW())
             WHERE l.kind = 'try' AND l.photo_purged_at IS NULL AND l.photo_expires_at < NOW();
            DELETE FROM field.try_look_slot s WHERE s.created_at < NOW() - interval '1 day';
            RETURN QUERY SELECT u FROM unnest(COALESCE(uris, ARRAY[]::text[])) AS u
                          WHERE NOT EXISTS (SELECT 1 FROM field.vision_look l2 WHERE l2.photo_uri = u);
        END $$;
        REVOKE ALL ON FUNCTION field.worker_purge_try_looks() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION field.worker_purge_try_looks() TO field_worker;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS field.worker_purge_try_looks();
        DROP TABLE IF EXISTS field.try_look_slot;
        DELETE FROM field.vision_look WHERE kind = 'try';
        DROP POLICY IF EXISTS try_scope ON field.vision_look;
        DROP INDEX IF EXISTS field.idx_vision_look_try_expiry;
        DROP INDEX IF EXISTS field.idx_vision_look_try_principal;
        ALTER TABLE field.vision_look
            DROP CONSTRAINT IF EXISTS ck_vision_look_kind,
            DROP COLUMN IF EXISTS photo_purged_at,
            DROP COLUMN IF EXISTS photo_expires_at,
            DROP COLUMN IF EXISTS photo_sha256,
            DROP COLUMN IF EXISTS photo_uri,
            DROP COLUMN IF EXISTS kind,
            ALTER COLUMN capture_id SET NOT NULL,
            ALTER COLUMN task_id SET NOT NULL,
            ALTER COLUMN site_id SET NOT NULL;
        """
    )
