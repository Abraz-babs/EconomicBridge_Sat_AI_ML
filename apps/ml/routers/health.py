"""GET /api/v1/health — ML-service liveness probe."""
from fastapi import APIRouter
from pydantic import BaseModel

from config import get_settings

router = APIRouter(prefix="/health", tags=["health"])


class MlHealth(BaseModel):
    status: str
    service: str
    version: str
    app_env: str


@router.get("", response_model=MlHealth)
async def health() -> MlHealth:
    s = get_settings()
    return MlHealth(
        status="ok",
        service=s.app_name,
        version=s.app_version,
        app_env=s.app_env,
    )
