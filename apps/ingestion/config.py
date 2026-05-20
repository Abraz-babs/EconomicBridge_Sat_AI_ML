"""Settings for the satellite ingestion microservice.

Sourced from env + the **project-root** `.env`. Path is computed from `__file__`
so it works regardless of cwd. Production secrets come from AWS Secrets
Manager per CLAUDE.md §4.1 — env vars are dev-only.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/ingestion/config.py → apps/ingestion/ → apps/ → project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ROOT_ENV = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "economicbridge-ingestion"
    app_version: str = "0.1.0"

    log_level: str = "INFO"

    cors_origins: list[str] = ["http://localhost:3000"]

    # DB — same instance as apps/api. Each service has its own pool.
    database_url: str = (
        "postgresql+asyncpg://postgres:devpassword@localhost:5432/economicbridge"
    )
    db_echo: bool = False
    db_pool_size: int = 3
    db_pool_max_overflow: int = 5

    # NASA FIRMS — empty string means "no key configured, use mock-mode".
    nasa_firms_map_key: str = ""
    nasa_firms_base_url: str = "https://firms.modaps.eosdis.nasa.gov/api"
    # Default source: MODIS Near-Real-Time. Other valid values include
    # VIIRS_SNPP_NRT, VIIRS_NOAA20_NRT, MODIS_SP (standard product, 24h delay).
    nasa_firms_default_source: str = "MODIS_NRT"

    # N2YO — live satellite-pass predictions. Empty key => 503 from the
    # passes endpoint, which is the right answer: no fake pass schedules.
    n2yo_api_key: str = ""
    n2yo_base_url: str = "https://api.n2yo.com/rest/v1/satellite"
    # Minimum elevation (degrees) we consider a "useful" overhead pass.
    # Below ~25° the satellite is too oblique for good imagery of the
    # target ROI. 30° matches Copernicus' own pass-planning heuristics.
    n2yo_default_min_elevation: int = 30

    # Copernicus Data Space Ecosystem (CDSE) — Sentinel Hub on CDSE, NOT
    # commercial Sentinel Hub. OAuth client_credentials at the identity
    # endpoint; STAC catalog at the sh.dataspace endpoint. See
    # docs/memory ref_copernicus_endpoints.md for the why.
    copernicus_client_id: str = ""
    copernicus_client_secret: str = ""
    copernicus_oauth_url: str = (
        "https://identity.dataspace.copernicus.eu"
        "/auth/realms/CDSE/protocol/openid-connect/token"
    )
    copernicus_catalog_url: str = (
        "https://sh.dataspace.copernicus.eu/api/v1/catalog/1.0.0/search"
    )
    # Default collection: Sentinel-2 L2A (atmospherically corrected optical).
    # Other valid: sentinel-1-grd (SAR), sentinel-3-olci-l1b (ocean colour).
    copernicus_default_collection: str = "sentinel-2-l2a"
    # Refresh the token this many seconds before stated expiry — protects
    # against clock skew + in-flight requests landing post-expiry.
    copernicus_token_refresh_skew_seconds: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
