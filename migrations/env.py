"""
Alembic Environment Configuration — EconomicBridge
=====================================================
Configures Alembic for async migrations with per-tenant schema support.

The TENANT_SCHEMA environment variable controls which schema the migration
targets. The run_migrations.py script sets this for each tenant.
"""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# Import Base so Alembic can detect models
# from apps.api.core.database import Base  # noqa: E402
# target_metadata = Base.metadata

# For now, use None — models will be added as they're created
target_metadata = None

# Alembic Config object
config = context.config

# Setup logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url from environment if available
database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# Get tenant schema from environment
tenant_schema = os.environ.get("TENANT_SCHEMA", "public")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts without connecting to the database.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=tenant_schema,
        include_schemas=True,
    )

    with context.begin_transaction():
        # Set search_path for the tenant schema
        context.execute(f"SET search_path TO {tenant_schema}, public")
        context.run_migrations()


def do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    """Run migrations within a connection context.

    Args:
        connection: SQLAlchemy connection object.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=tenant_schema,
        include_schemas=True,
    )

    with context.begin_transaction():
        # Set search_path for the tenant schema
        context.execute(f"SET search_path TO {tenant_schema}, public")
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
