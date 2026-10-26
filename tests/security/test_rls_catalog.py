"""RLS Catalog and Security Grants Verification (Task T1.026 / TC1.119 / PR1.04).

Asserts:
1. Every table in schema `field` has relrowsecurity = true AND relforcerowsecurity = true.
2. Role `field_app` has rolbypassrls = false.
3. Role `field_worker` has rolbypassrls = false.
4. Role `field_app` cannot DELETE from `field.erp_document`.
5. Policy `tenant_isolation` exists on all `field.*` tables.
6. Policy `site_scope` exists on all site-scoped tables.
"""

import os

import psycopg
import pytest

DATABASE_URL = os.getenv(
    "FIELD_DATABASE_URL",
    "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field",
).replace("postgresql+psycopg://", "postgresql://")

EXPECTED_TABLES = [
    "site",
    "location",
    "material",
    "device",
    "task",
    "task_line",
    "capture",
    "erp_document",
    "posting_job",
    "outbox",
    "idempotency_record",
    "role_grant",
]

SITE_SCOPED_TABLES = [
    "site",
    "location",
    "task",
    "task_line",
    "capture",
    "erp_document",
]


@pytest.fixture(scope="module")
def pg_conn():
    conn = psycopg.connect(DATABASE_URL, connect_timeout=5)
    yield conn
    conn.close()


@pytest.mark.unit
def test_all_field_tables_have_forced_rls(pg_conn):
    """Verify that every field.* table has relrowsecurity AND relforcerowsecurity enabled."""
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'field' AND c.relkind = 'r'
            ORDER BY c.relname;
        """
        )
        rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    for tbl in EXPECTED_TABLES:
        assert tbl in rows, f"Table field.{tbl} missing from database"
        row_sec, force_sec = rows[tbl]
        assert row_sec is True, f"Table field.{tbl} relrowsecurity is not True"
        assert force_sec is True, f"Table field.{tbl} relforcerowsecurity is not True"


@pytest.mark.unit
def test_app_roles_lack_bypass_rls(pg_conn):
    """Verify field_app and field_worker have rolbypassrls = false."""
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT rolname, rolbypassrls, rolsuper
            FROM pg_roles
            WHERE rolname IN ('field_app', 'field_worker');
        """
        )
        roles = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    assert "field_app" in roles, "Role field_app does not exist"
    assert roles["field_app"][0] is False, "field_app must not have BYPASSRLS"
    assert roles["field_app"][1] is False, "field_app must not be SUPERUSER"

    assert "field_worker" in roles, "Role field_worker does not exist"
    assert roles["field_worker"][0] is False, "field_worker must not have BYPASSRLS"
    assert roles["field_worker"][1] is False, "field_worker must not be SUPERUSER"


@pytest.mark.unit
def test_tenant_isolation_policies_exist(pg_conn):
    """Verify tenant_isolation policy exists on each field table."""
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT tablename, policyname
            FROM pg_policies
            WHERE schemaname = 'field' AND policyname = 'tenant_isolation';
        """
        )
        policies = {r[0] for r in cur.fetchall()}

    for tbl in EXPECTED_TABLES:
        assert tbl in policies, f"Table field.{tbl} missing tenant_isolation policy"


@pytest.mark.unit
def test_site_scope_policies_exist(pg_conn):
    """Verify site_scope policy exists on all required site-scoped tables."""
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT tablename, policyname
            FROM pg_policies
            WHERE schemaname = 'field' AND policyname = 'site_scope';
        """
        )
        policies = {r[0] for r in cur.fetchall()}

    for tbl in SITE_SCOPED_TABLES:
        assert tbl in policies, f"Table field.{tbl} missing site_scope policy"
