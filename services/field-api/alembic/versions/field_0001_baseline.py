"""Baseline Extensions and Field Schema (Task T1.024).

Revision ID: field_0001
Revises:
Create Date: 2026-10-27
"""

from alembic import op

revision = "field_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extensions
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # Schema
    op.execute("CREATE SCHEMA IF NOT EXISTS field")

    # Monotonic updated_at trigger function
    op.execute(
        """
        CREATE OR REPLACE FUNCTION field.touch_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """
    )

    # UUIDv7 Generator in Postgres PL/pgSQL
    op.execute(
        """
        CREATE OR REPLACE FUNCTION field.uuid_generate_v7()
        RETURNS uuid AS $$
        DECLARE
            v_time timestamp with time zone := clock_timestamp();
            v_secs bigint := EXTRACT(EPOCH FROM v_time);
            v_msec bigint := (v_secs * 1000) + EXTRACT(MILLISECONDS FROM v_time)::bigint % 1000;
            v_rand bytea := gen_random_bytes(10);
            v_hex text;
        BEGIN
            v_hex := lpad(to_hex(v_msec), 12, '0') ||
                     '7' || substr(encode(v_rand, 'hex'), 1, 3) ||
                     '8' || substr(encode(v_rand, 'hex'), 4, 3) ||
                     substr(encode(v_rand, 'hex'), 7, 12);
            RETURN v_hex::uuid;
        END;
        $$ LANGUAGE plpgsql VOLATILE;
    """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS field.uuid_generate_v7()")
    op.execute("DROP FUNCTION IF EXISTS field.touch_updated_at()")
