"""Property Test PR1.04: Fail-closed RLS Tenant Isolation and Site Scoping.

Invariants:
1. When app.tenant_id is unset or empty, SELECT on any field table returns 0 rows (fail closed).
2. When app.tenant_id = T1, rows for T2 are never visible.
3. INSERT with tenant_id != current_setting('app.tenant_id') fails WITH CHECK violation.
4. When app.site_ids is specific (e.g. S1), rows for S2 are not visible.
"""

import os
import uuid

import psycopg
import pytest

DATABASE_URL = os.getenv(
    "FIELD_DATABASE_URL",
    "postgresql://field_app:devpassword@127.0.0.1:5450/field",
).replace("postgresql+psycopg://", "postgresql://")

ADMIN_DATABASE_URL = os.getenv(
    "FIELD_ADMIN_DATABASE_URL",
    "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field",
).replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture(scope="module")
def seeded_tenants():
    """Seed data across two separate tenants T1 and T2 using admin connection."""
    admin_conn = psycopg.connect(ADMIN_DATABASE_URL, autocommit=True)
    t1_id = str(uuid.uuid4())
    t2_id = str(uuid.uuid4())

    with admin_conn.cursor() as cur:
        # Seed Site 1 for T1
        cur.execute(
            """
            INSERT INTO field.site (id, tenant_id, code, name, kind)
            VALUES (field.uuid_generate_v7(), %s, 'SITE-T1-A', 'Site T1 Alpha', 'warehouse')
            RETURNING id;
        """,
            (t1_id,),
        )
        s1_id = str(cur.fetchone()[0])

        # Seed Site 2 for T1
        cur.execute(
            """
            INSERT INTO field.site (id, tenant_id, code, name, kind)
            VALUES (field.uuid_generate_v7(), %s, 'SITE-T1-B', 'Site T1 Beta', 'warehouse')
            RETURNING id;
        """,
            (t1_id,),
        )
        s2_id = str(cur.fetchone()[0])

        # Seed Site 3 for T2
        cur.execute(
            """
            INSERT INTO field.site (id, tenant_id, code, name, kind)
            VALUES (field.uuid_generate_v7(), %s, 'SITE-T2-A', 'Site T2 Alpha', 'warehouse')
            RETURNING id;
        """,
            (t2_id,),
        )
        s3_id = str(cur.fetchone()[0])

    admin_conn.close()

    yield {
        "t1_id": t1_id,
        "t2_id": t2_id,
        "t1_s1": s1_id,
        "t1_s2": s2_id,
        "t2_s1": s3_id,
    }

    # Teardown
    admin_conn = psycopg.connect(ADMIN_DATABASE_URL, autocommit=True)
    with admin_conn.cursor() as cur:
        cur.execute("DELETE FROM field.site WHERE tenant_id IN (%s, %s);", (t1_id, t2_id))
    admin_conn.close()


@pytest.mark.property
def test_rls_fail_closed_when_tenant_unset(seeded_tenants):
    """PR1.04 Invariant 1: Unset or empty tenant context returns 0 rows (fail closed)."""
    conn = psycopg.connect(DATABASE_URL, autocommit=True)
    with conn.cursor() as cur:
        # Without setting app.tenant_id
        cur.execute("SELECT count(*) FROM field.site;")
        count = cur.fetchone()[0]
        assert count == 0, f"Expected 0 rows when app.tenant_id is unset, got {count}"

        # With empty string
        cur.execute("SET app.tenant_id = '';")
        cur.execute("SELECT count(*) FROM field.site;")
        count = cur.fetchone()[0]
        assert count == 0, f"Expected 0 rows when app.tenant_id is empty, got {count}"
    conn.close()


@pytest.mark.property
def test_rls_strict_tenant_isolation(seeded_tenants):
    """PR1.04 Invariant 2: Context for T1 only sees T1 rows and never T2 rows."""
    t1_id = seeded_tenants["t1_id"]
    t2_id = seeded_tenants["t2_id"]

    conn = psycopg.connect(DATABASE_URL, autocommit=True)
    with conn.cursor() as cur:
        cur.execute(f"SET app.tenant_id = '{t1_id}';")
        cur.execute("SET app.site_ids = '*';")
        cur.execute("SELECT tenant_id::text, code FROM field.site;")
        rows = cur.fetchall()

        assert len(rows) == 2, f"Expected 2 rows for T1, got {len(rows)}"
        for row_tenant, code in rows:
            assert row_tenant == t1_id
            assert "SITE-T1" in code

        # Switch to T2
        cur.execute(f"SET app.tenant_id = '{t2_id}';")
        cur.execute("SELECT tenant_id::text, code FROM field.site;")
        rows2 = cur.fetchall()

        assert len(rows2) == 1, f"Expected 1 row for T2, got {len(rows2)}"
        assert rows2[0][0] == t2_id
        assert rows2[0][1] == "SITE-T2-A"
    conn.close()


@pytest.mark.property
def test_rls_cross_tenant_insert_prevented(seeded_tenants):
    """PR1.04 Invariant 3: Inserting row for T2 while in T1 context violates WITH CHECK."""
    t1_id = seeded_tenants["t1_id"]
    t2_id = seeded_tenants["t2_id"]

    conn = psycopg.connect(DATABASE_URL, autocommit=True)
    with conn.cursor() as cur:
        cur.execute(f"SET app.tenant_id = '{t1_id}';")
        cur.execute("SET app.site_ids = '*';")

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(
                """
                INSERT INTO field.site (id, tenant_id, code, name, kind)
                VALUES (field.uuid_generate_v7(), %s, 'SITE-ROGUE', 'Rogue Site', 'warehouse');
            """,
                (t2_id,),
            )
    conn.close()


@pytest.mark.property
def test_rls_site_scoping(seeded_tenants):
    """PR1.04 Invariant 4: Scoping to specific site restricts visible rows."""
    t1_id = seeded_tenants["t1_id"]
    s1_id = seeded_tenants["t1_s1"]

    conn = psycopg.connect(DATABASE_URL, autocommit=True)
    with conn.cursor() as cur:
        cur.execute(f"SET app.tenant_id = '{t1_id}';")
        # Restrict to site 1 only
        cur.execute(f"SET app.site_ids = '{s1_id}';")
        cur.execute("SELECT id::text, code FROM field.site;")
        rows = cur.fetchall()

        assert len(rows) == 1
        assert rows[0][0] == s1_id
        assert rows[0][1] == "SITE-T1-A"
    conn.close()
