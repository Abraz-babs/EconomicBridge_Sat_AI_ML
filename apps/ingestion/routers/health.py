"""GET /api/v1/health — ingestion-service liveness probe."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from config import get_settings

router = APIRouter(prefix="/health", tags=["health"])


class IngestionHealth(BaseModel):
    status: str
    service: str
    version: str
    app_env: str
    nasa_firms_configured: bool


@router.get("", response_model=IngestionHealth)
async def health(request: Request) -> IngestionHealth:
    settings = get_settings()
    return IngestionHealth(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        app_env=settings.app_env,
        nasa_firms_configured=bool(settings.nasa_firms_map_key),
    )
