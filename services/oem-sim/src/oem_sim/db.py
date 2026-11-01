"""Database connection of the OEM simulator: schema ``oemsim`` in the simulator database.

OEMSIM_DATABASE_URL, else ERPSIM_DATABASE_URL (the OEM simulator is mounted by erp-sim and shares its database).
"""

import os

import psycopg


def database_url() -> str:
    url = os.getenv("OEMSIM_DATABASE_URL") or os.getenv("ERPSIM_DATABASE_URL") or (
        "postgresql://postgres:dev-postgres-password@127.0.0.1:5450/erpsim")
    return url.replace("postgresql+psycopg://", "postgresql://").replace("@localhost:", "@127.0.0.1:")


def get_conn() -> psycopg.Connection:
    return psycopg.connect(database_url(), autocommit=False)
