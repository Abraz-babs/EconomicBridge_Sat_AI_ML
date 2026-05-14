"""Alembic environment.

Uses the sync DB URL (`database_url_sync`) from config.Settings because Alembic
itself is sync. The async URL is used at request-time by the API. `target_metadata`
must reference the same Base that all models inherit from so `--autogenerate`
detects new tables.

This file lives at apps/api/migrations/env.py — when alembic is invoked from
apps/api/ the api package root is on sys.path and `from db.base import Base`
resolves cleanly.
"""
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make `apps/api/` importable so `db`, `models`, `config` resolve.
API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from config import get_settings  # noqa: E402
from db.base import Base  # noqa: E402
import models  # noqa: F401,E402  — registers all ORM tables with Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the sync DB URL from app settings (never read from alembic.ini).
config.set_main_option("sqlalchemy.url", get_settings().database_url_sync)

target_metadata = Base.metadata


def _include_object(obj, name, type_, reflected, compare_to):  # noqa: ANN001 — alembic signature
    """Exclude tenant-scoped tables from autogenerate.

    Per-tenant tables (alert_events, satellite_observations, etc.) live in
    tenant_<id> schemas and their DDL is hand-applied across every pilot schema
    inside migration files. Autogenerate would incorrectly suggest creating
    them in public — filter them out here.
    """
    if type_ == "table":
        info = getattr(obj, "info", {}) or {}
        if info.get("is_tenant_scoped"):
            return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no DB connection — emits SQL to stdout)."""

    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_object=_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
