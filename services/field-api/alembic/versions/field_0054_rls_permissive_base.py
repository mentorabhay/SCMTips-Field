"""Give every forced-RLS table a permissive base policy (C4 foundation; root cause of §3.10).

PostgreSQL grants a non-owner access to a row only if at least one PERMISSIVE policy passes and
every RESTRICTIVE policy passes. Thirteen tables (material, device, device_pairing, consent_record,
capture_upload, voice_event, count_record, idempotency_record, pi_document, role_grant,
trail_point, anchor, device_notification) had only a RESTRICTIVE tenant policy, so the app role
(NOBYPASSRLS) could neither read nor write them. Every DB path to them failed, which is why the
routes had fallen back to in-process stores.

This migration adds ``rls_permissive_base`` (USING true / WITH CHECK true) to each such table.
Isolation is unchanged: the RESTRICTIVE tenant and site policies still have to pass.

Revision ID: field_0054
Revises: field_0053
"""

from alembic import op

revision = "field_0054"
down_revision = "field_0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE t record;
        BEGIN
          FOR t IN
            SELECT c.relname
              FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'field' AND c.relkind = 'r' AND c.relforcerowsecurity
               AND NOT EXISTS (
                 SELECT 1 FROM pg_policies p
                  WHERE p.schemaname = 'field' AND p.tablename = c.relname AND p.permissive = 'PERMISSIVE')
          LOOP
            EXECUTE format(
              'CREATE POLICY rls_permissive_base ON field.%I AS PERMISSIVE FOR ALL USING (true) WITH CHECK (true)',
              t.relname);
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE t record;
        BEGIN
          FOR t IN SELECT tablename FROM pg_policies
                    WHERE schemaname = 'field' AND policyname = 'rls_permissive_base'
          LOOP
            EXECUTE format('DROP POLICY rls_permissive_base ON field.%I', t.tablename);
          END LOOP;
        END $$;
        """
    )
