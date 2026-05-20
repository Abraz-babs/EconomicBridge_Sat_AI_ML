"""Settings for the ML service.

Reads the project-root .env (same as api + ingestion). Production secrets via
AWS Secrets Manager per CLAUDE.md §4.1.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/ml/config.py → apps/ml/ → apps/ → project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ROOT_ENV = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "economicbridge-ml"
    app_version: str = "0.1.0"
    log_level: str = "INFO"

    cors_origins: list[str] = ["http://localhost:3000"]

    # DB — same instance as api + ingestion. Used to persist predictions.
    database_url: str = (
        "postgresql+asyncpg://postgres:devpassword@localhost:5432/economicbridge"
    )
    db_echo: bool = False
    db_pool_size: int = 3
    db_pool_max_overflow: int = 5

    # Model paths — joblib / .pth snapshots live next to the source code.
    model_dir: Path = PROJECT_ROOT / "apps" / "ml" / "artifacts"

    # CropGuard ResNet-50 — how many top classes the response ships back.
    # 3 hits the sweet spot: top-1 + two runners-up gives the dashboard
    # enough context for "are we confident?" without exploding payload size.
    crop_top_k_classes: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
