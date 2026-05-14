"""Application settings.

Sources values from environment variables and an optional `.env` file. In production
secrets (DB password, JWT key, third-party API keys) must come from AWS Secrets
Manager, not env vars — see CLAUDE.md §4.1. This module only handles non-secret
configuration that's safe to live in env vars.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, populated from env and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "economicbridge-api"
    app_version: str = "0.1.0"

    log_level: str = "INFO"

    cors_origins: list[str] = ["http://localhost:3000"]

    # Database — async URL for SQLAlchemy / asyncpg.
    # In prod this must come from AWS Secrets Manager, not env vars (CLAUDE.md §4.1).
    database_url: str = (
        "postgresql+asyncpg://postgres:devpassword@localhost:5432/economicbridge"
    )
    # Sync URL — used only by Alembic (which does not run async).
    database_url_sync: str = (
        "postgresql+psycopg2://postgres:devpassword@localhost:5432/economicbridge"
    )
    db_echo: bool = False
    db_pool_size: int = 5
    db_pool_max_overflow: int = 10


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Tests may call `get_settings.cache_clear()` to force a reload after monkey-
    patching the environment.
    """
    return Settings()
