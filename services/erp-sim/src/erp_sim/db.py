"""Database connection pool / factory for erp-sim."""

import os

import psycopg

DATABASE_URL = (
    os.getenv(
        "ERPSIM_DATABASE_URL",
        "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/erpsim",
    )
    .replace("postgresql+psycopg://", "postgresql://")
    .replace("@localhost:", "@127.0.0.1:")
)


def get_conn() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, autocommit=False)
