"""GET /api/v1/health — notifications-service liveness probe."""
from fastapi import APIRouter
from pydantic import BaseModel

from config import get_settings

router = APIRouter(prefix="/health", tags=["health"])


class NotificationsHealth(BaseModel):
    status: str
    service: str
    version: str
    app_env: str
    termii_configured: bool
    twilio_configured: bool


@router.get("", response_model=NotificationsHealth)
async def health() -> NotificationsHealth:
    s = get_settings()
    return NotificationsHealth(
        status="ok",
        service=s.app_name,
        version=s.app_version,
        app_env=s.app_env,
        termii_configured=s.termii_configured,
        twilio_configured=s.twilio_configured,
    )
