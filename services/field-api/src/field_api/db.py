"""Field API Database Connection Utility."""

from __future__ import annotations

import os
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
