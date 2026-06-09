"""Settings for the notifications microservice.

Reads the project-root `.env` (same as api / ingestion / ml). Production
secrets via AWS Secrets Manager per CLAUDE.md §4.1.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ROOT_ENV = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "economicbridge-notifications"
    app_version: str = "0.1.0"
    log_level: str = "INFO"

    cors_origins: list[str] = ["http://localhost:3000"]

    # ALB deployment path prefix (e.g. "/notifications") — stripped before
    # routing by UrlPrefixStripMiddleware. Empty (dev) = disabled.
    url_prefix: str = ""

    database_url: str = (
        "postgresql+asyncpg://postgres:devpassword@localhost:5432/economicbridge"
    )
    db_echo: bool = False
    db_pool_size: int = 3
    db_pool_max_overflow: int = 5

    # ── Termii (Nigerian SMS gateway) ───────────────────────────────────
    termii_api_key: str = ""
    termii_base_url: str = "https://api.ng.termii.com/api"
    termii_sender_id: str = "EconoBridge"

    # ── Twilio (ECOWAS / international SMS fallback) ────────────────────
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    # ── AWS SNS (primary Nigerian SMS, replaces Termii) ────────────────
    # Credentials come from the standard AWS chain (the ECS task role in
    # production, ~/.aws or env vars in dev) — never a hardcoded key, so
    # there's no api_key field. `sns_enabled` is the operator opt-in;
    # leaving it False keeps dev on the mock gateway. The sender ID is the
    # alphanumeric origination ID shown on the handset (must be registered
    # with Nigerian carriers, same as any provider).
    sns_enabled: bool = False
    sns_region: str = "eu-west-1"
    sns_sender_id: str = "EconBridge"

    @property
    def termii_configured(self) -> bool:
        return bool(self.termii_api_key)

    @property
    def twilio_configured(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_from_number)

    @property
    def sns_configured(self) -> bool:
        return bool(self.sns_enabled)


@lru_cache
def get_settings() -> Settings:
    return Settings()
