"""Alembic environment of the OEM simulator: schema ``oemsim``, its own version table ``oemsim.alembic_version``."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def get_url() -> str:
    url = os.getenv("OEMSIM_DATABASE_URL") or os.getenv(
        "ERPSIM_DATABASE_URL",
        "postgresql+psycopg://postgres:dev-postgres-password@127.0.0.1:5450/erpsim",
    )
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if "@localhost:" in url:
        url = url.replace("@localhost:", "@127.0.0.1:")
    return url


def run_migrations_offline() -> None:
    context.configure(url=get_url(), target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"}, version_table_schema="oemsim")
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        # The version table lives in the schema, so the schema must exist before Alembic looks for it.
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS oemsim"))
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata, version_table_schema="oemsim")
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
