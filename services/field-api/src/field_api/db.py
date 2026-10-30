"""Field API Database Connection Utility."""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg

from field_api.config import settings

DATABASE_URL = (
    os.getenv(
        "FIELD_DATABASE_URL",
        getattr(
            settings,
            "FIELD_DATABASE_URL",
            "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/field",
        ),
    )
    .replace("postgresql+psycopg://", "postgresql://")
    .replace("@localhost:", "@127.0.0.1:")
)


def get_conn(db_url: str | None = None) -> psycopg.Connection[Any]:
    """Return a psycopg3 database connection with autocommit disabled."""
    url = (
        (db_url or DATABASE_URL)
        .replace("postgresql+psycopg://", "postgresql://")
        .replace("@localhost:", "@127.0.0.1:")
    )
    return psycopg.connect(url, autocommit=False)


@contextmanager
def tenant_tx(tenant_id: str, site_ids: Sequence[str] = ("*",)) -> Iterator[psycopg.Cursor[Any]]:
    """One transaction with RLS context set transaction-locally (C4 foundation).

    Sets ``app.tenant_id`` and ``app.site_ids`` with ``set_config(..., true)`` so the scope
    cannot leak past this transaction. Commits on success, rolls back on any exception,
    always closes the connection. Connect as the application role (NOBYPASSRLS) so RLS
    really applies; never as a superuser.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT set_config('app.tenant_id', %s, true), set_config('app.site_ids', %s, true)",
                (str(tenant_id), ",".join(site_ids) if site_ids else ""),
            )
            yield cur
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def principal_tx(principal: Any) -> Any:
    """``tenant_tx`` scoped to an authenticated principal's tenant and sites."""
    return tenant_tx(principal.tenant_id, principal.site_ids)
