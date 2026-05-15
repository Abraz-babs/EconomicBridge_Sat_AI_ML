"""Application settings.

Sources values from environment variables and the **project-root** `.env` file.
Path is computed from `__file__` so it works regardless of where uvicorn is
started. In production, secrets come from AWS Secrets Manager — see CLAUDE.md
§4.1.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api/config.py → apps/api/ → apps/ → project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ROOT_ENV = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Runtime settings, populated from env and the root `.env`."""

    model_config = SettingsConfigDict(
        env_file=str(ROOT_ENV),
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
