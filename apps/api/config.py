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

    # Auto-notify: when a ShockGuard/Farmland alert is persisted, fire an SMS
    # dispatch to the notifications service. OFF by default — sending PII SMS
    # automatically must be opted into. The system org must hold a signed DPA
    # for the tenants it notifies (in dev, the demo org from seed_demo_dpa.py).
    auto_notify_enabled: bool = False
    notify_base_url: str = "http://localhost:8003/api/v1"
    notify_system_org_id: str = ""

    # ─── Auth / JWT (CLAUDE.md §4.1) ─────────────────────────────────────
    # In production `jwt_secret_key` MUST come from AWS Secrets Manager, never
    # this default. The default exists only so local dev boots without config.
    jwt_secret_key: str = "dev-insecure-change-me-via-secrets-manager"
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_min: int = 15          # access token lifetime (CLAUDE.md §4.1)
    jwt_refresh_ttl_days: int = 7         # refresh token lifetime
    invite_ttl_hours: int = 48            # tenant activation-link validity

    # Public base URL of the dashboard — used to build activation links in
    # invite emails. In prod this is the deployed frontend origin.
    public_app_url: str = "http://localhost:3001"

    # Email delivery for invites. 'console' just logs the message + link (dev,
    # no spend) ; 'ses' sends via AWS SES (prod). When not 'console' we also
    # stop echoing the raw activation link back in the API response.
    email_backend: str = "console"
    email_from: str = "no-reply@economicbridge.app"
    aws_region: str = "eu-west-1"

    # Where the public Bizra Farms contact form delivers inquiries.
    contact_recipient_email: str = "bizrafarms@gmail.com"

    # Super-admin bootstrap — read ONLY by scripts/seed_super_admin.py to create
    # the platform operator account. Never referenced at request time.
    super_admin_email: str = "admin@economicbridge.app"
    super_admin_password: str = ""


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Tests may call `get_settings.cache_clear()` to force a reload after monkey-
    patching the environment.
    """
    return Settings()
