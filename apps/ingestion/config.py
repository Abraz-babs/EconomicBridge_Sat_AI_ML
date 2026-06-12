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

    # ALB deployment path prefix (e.g. "/ingestion") — stripped before routing
    # by UrlPrefixStripMiddleware. Empty (dev) = disabled.
    url_prefix: str = ""

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
    # CDSE OData endpoint for raw SAFE downloads. Search is via the Sentinel
    # Hub Catalog API (above); download is via OData on dataspace.
    copernicus_odata_url: str = "https://catalogue.dataspace.copernicus.eu/odata/v1"
    # Statistical API: server-side raster aggregation that returns JSON
    # time series (mean/min/max/percentiles per requested time-bucket) over
    # a polygon or bbox. Lets ShockGuard + NDVI anomaly detectors run on
    # real Sentinel-1 SAR + Sentinel-2 NDVI without us touching raster
    # bytes. See docs/memory reference_copernicus_endpoints.md.
    copernicus_statistical_url: str = (
        "https://sh.dataspace.copernicus.eu/api/v1/statistics"
    )
    # Hard timeout for one SAFE download. Sentinel-2 L2A scenes run
    # ~600 MB — over a 10 Mbps link that's ~8 minutes. 15 min headroom
    # for slower networks and the SAR (Sentinel-1 GRD) which is larger.
    copernicus_download_timeout_seconds: int = 15 * 60

    # ML service (conflict predictor + future ShockGuard, CropGuard). The
    # ingestion service calls ML over HTTP per the production architecture
    # (CLAUDE.md §5 — never call satellite/ML in-process).
    ml_base_url: str = "http://127.0.0.1:8002/api/v1"
    # Confidence floor for promoting a prediction into alert_events.
    # CLAUDE.md §9: >= 0.90 HIGH, >= 0.75 MEDIUM, < 0.75 LOW (audit-only).
    conflict_alert_min_confidence: float = 0.75
    # Cap conflict alerts inserted per tenant per scheduled run. Same logic
    # as DEFAULT_MAX_ALERTS_PER_RUN for FIRMS — keeps the feed legible.
    conflict_max_alerts_per_run: int = 3

    # NASA Earthdata (LAADS DAAC) — VIIRS Black Marble nightlight catalog.
    # Bearer token from urs.earthdata.nasa.gov → "Generate Token". Empty
    # token means "catalog client returns no scenes" — the processor
    # downgrades to seed_v1 rows in that case. NEVER hardcode the token.
    earthdata_token: str = ""
    # LAADS DAAC catalog base. The full search URL is built by the client
    # — this is the host + version prefix only so we can override per env.
    earthdata_laads_base_url: str = "https://ladsweb.modaps.eosdis.nasa.gov"
    # VNP46A2 = daily moonlight-adjusted black marble (per-pixel radiance).
    # VNP46A4 = annual composite (smoothed). A2 for change-detection; A4
    # for stable poverty mapping baselines.
    viirs_black_marble_product: str = "VNP46A2"
    # LAADS collection number. 5200 is the current VNP46A2 v002 collection
    # (5000 was deprecated in 2023). When NASA bumps to a new collection
    # — typically every 2-3 years — flip this without redeploying code.
    earthdata_laads_collection: str = "5200"

    # WorldPop — population grid catalog. Anonymous REST API at
    # hub.worldpop.org/rest/data (the www. host 301s here as of 2026-04).
    # Open S3 bucket (s3://worldpop-data) for raster reads in Phase B.
    worldpop_rest_base_url: str = "https://hub.worldpop.org/rest/data"

    # Base for the PPP population GeoTIFF rasters (COG sampling). Default is
    # WorldPop's server; in AWS we point this at our S3 mirror
    # (s3://<artifacts-bucket>/worldpop) because data.worldpop.org currently
    # answers HTTP range requests with 200 + the full file instead of 206,
    # which breaks GDAL/vsicurl COG reads everywhere. Same path layout under
    # either base: {year}/{ISO3}/{iso3}_ppp_{year}.tif
    worldpop_raster_base_url: str = (
        "https://data.worldpop.org/GIS/Population/Global_2000_2020"
    )
    # Family path within the catalog. "pop/pic" = "Individual country
    # populations" (one row per ISO3). The bare /pop list is a directory
    # of 17 subdatasets — too coarse. /pop/{id} detail endpoints return
    # 500 inconsistently, so we list /pop/pic and filter client-side.
    worldpop_default_dataset: str = "pop/pic"
    # Default year used when the caller doesn't pin one. WorldPop publishes
    # ~2 years behind; 2024 layers are stable as of 2026-Q1.
    worldpop_default_year: int = 2024

    # NBS — Nigeria National Bureau of Statistics (cost-of-living / CPI +
    # household income). Drives Module 06 (Economic Mobility Compass)
    # live data. Empty key = mock mode: the client returns deterministic
    # synthetic indicators tagged source='nbs_col_v1' so the swap-in
    # path (seed_v1 → nbs_col_v1) is exercisable without credentials.
    # NBS publishes Selected Food + All-Items CPI at the state level;
    # the real client maps those to our per-LGA cost_of_living_index.
    nbs_api_key: str = ""
    nbs_base_url: str = "https://nigerianstat.gov.ng/api"
    # ECOWAS STAT covers the non-Nigerian pilots (Ghana, Senegal). Same
    # mock-fallback contract; separate key because it's a different body.
    ecowas_stat_api_key: str = ""
    ecowas_stat_base_url: str = "https://ecowas.int/statistics/api"

    # World Bank Indicators API (v2) — keyless, open (CC BY 4.0). Supplies
    # the national economic ANCHOR for Module 06: GNI per capita in local
    # currency (NY.GNP.PCAP.CN — Naira for Nigerian pilots, so no FX) is
    # disaggregated to per-LGA estimates tagged source='worldbank_v1'.
    # No API key required; this runs automatically on the scheduler.
    worldbank_api_base_url: str = "https://api.worldbank.org/v2"

    # UNICEF GIGA (school connectivity mapping) + ITU (telecom coverage)
    # feed Module 07 (SkillsBridge). Both are global so they apply to all
    # pilots — a single giga_v1 source tag carries the combined per-LGA
    # row (school density from GIGA, internet/mobile coverage from ITU).
    # Empty keys => mock mode, same contract as NBS. NEVER hardcode keys.
    # GIGA: register at https://maps.giga.global (Azure AD B2C sign-in) and
    # request an API key via their API-keys admin dashboard; full API docs at
    # https://maps.giga.global/docs/explore-api. Key auth model confirmed
    # 2026-05; exact schools/measurements endpoint paths + JSON field names
    # must be verified against a live key before the real fetch ships.
    giga_api_key: str = ""
    giga_base_url: str = "https://maps.giga.global/api"
    itu_api_key: str = ""
    itu_base_url: str = "https://api.datahub.itu.int"

    # HDX HAPI (Humanitarian API) — keyless, open. Module 02 (Aid
    # Coordination): operational-presence ("who does what where") becomes
    # per-LGA agency coverage tagged source='hapi_v1'. The "app identifier"
    # HAPI wants is a public attribution token = base64("<app>:<email>"),
    # NOT a credential — the client derives it from the two fields below
    # (override via .env for your own attribution).
    hdx_hapi_base_url: str = "https://hapi.humdata.org/api/v2"
    hdx_app_name: str = "economicbridge"
    hdx_app_email: str = "data@bizrafarms.org"

    # S3 imagery archive — Phase A.6. Empty bucket name = mock mode; the
    # downloader records what *would* have happened but doesn't call AWS.
    # Production Terraform (infrastructure/terraform/) provisions the
    # bucket per tenant naming convention.
    s3_imagery_bucket: str = ""
    s3_imagery_region: str = "eu-west-1"
    # Multipart-upload part size in bytes. 8 MB matches boto3's default
    # transfer config; smaller parts mean more requests but lower retry
    # cost on flaky links — sane staging default.
    s3_imagery_part_size_bytes: int = 8 * 1024 * 1024
    # Cap on per-attempt download size to protect dev disks. Sentinel SAFE
    # bundles run ~600 MB-1 GB; this is set at 2 GB to give headroom for
    # future Sentinel-3 OLCI tiles (which can hit 1.5 GB).
    s3_imagery_max_bytes: int = 2 * 1024 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
