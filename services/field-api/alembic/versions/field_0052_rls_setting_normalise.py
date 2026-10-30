"""Normalise RLS policies on one tenant setting: app.tenant_id (C4 foundation).

Phase 4 migrations 0041-0050 created policies on ``app.current_tenant_id`` while every other
table uses ``app.tenant_id``. Code that set only one of them saw zero rows (or had writes
refused) on the other group. This migration rewrites every ``field`` policy that references
``app.current_tenant_id`` to reference ``app.tenant_id``, preserving name, permissiveness,
command, roles, USING and WITH CHECK.

Revision ID: field_0052
Revises: field_0051
"""

from alembic import op

revision = "field_0052"
down_revision = "field_0051"
branch_labels = None
depends_on = None

_REWRITE = """
DO $$
DECLARE r record; roles_sql text;
BEGIN
  FOR r IN
    SELECT schemaname, tablename, policyname, permissive, cmd, roles, qual, with_check
      FROM pg_policies
     WHERE schemaname = 'field'
       AND (coalesce(qual, '') LIKE '%{src}%' OR coalesce(with_check, '') LIKE '%{src}%')
  LOOP
    SELECT string_agg(quote_ident(x), ', ') INTO roles_sql FROM unnest(r.roles) AS x;
    EXECUTE format('DROP POLICY %I ON %I.%I', r.policyname, r.schemaname, r.tablename);
    EXECUTE format(
      'CREATE POLICY %I ON %I.%I AS %s FOR %s TO %s %s %s',
      r.policyname, r.schemaname, r.tablename, r.permissive, r.cmd,
      CASE WHEN roles_sql = 'public' THEN 'PUBLIC' ELSE roles_sql END,
      CASE WHEN r.qual IS NULL THEN '' ELSE 'USING (' || replace(r.qual, '{src}', '{dst}') || ')' END,
      CASE WHEN r.with_check IS NULL THEN '' ELSE 'WITH CHECK (' || replace(r.with_check, '{src}', '{dst}') || ')' END
    );
  END LOOP;
END $$;
"""

# Tables whose policies 0041-0050 created on app.current_tenant_id (for an exact downgrade).
PHASE4_TABLES = (
    "asset_model", "asset_model_bom", "audit_finding", "audit_report", "balloon_registry",
    "climb_safety_event", "equipment", "exception_case", "fl_import_job", "queue_hold",
    "serial_event", "site_pack", "site_visit", "site_graph_node", "site_graph_edge",
)


def upgrade() -> None:
    op.execute(_REWRITE.format(src="app.current_tenant_id", dst="app.tenant_id"))


def downgrade() -> None:
    # Restore the original setting name only on the Phase 4 tables that used it.
    tables = ", ".join(f"'{t}'" for t in PHASE4_TABLES)
    op.execute(
        _REWRITE.format(src="app.tenant_id", dst="app.current_tenant_id").replace(
            "WHERE schemaname = 'field'", f"WHERE schemaname = 'field' AND tablename IN ({tables})"
        )
    )
