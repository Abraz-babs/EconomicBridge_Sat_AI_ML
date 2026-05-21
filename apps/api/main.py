"""EconomicBridge API entrypoint.

Local dev:
    cd apps/api
    python -m uvicorn main:app --reload --port 8000

Swagger UI:  http://localhost:8000/api/docs
OpenAPI:     http://localhost:8000/api/openapi.json

Middleware stack (outer-first as the request flows in):
    CORS -> TraceId -> SecurityHeaders -> TenantContext -> AuditLog -> handler

Starlette runs middleware in REVERSE addition order, so `add_middleware` calls
below are written in the opposite (inner-first) order.
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from middleware.audit import AuditLogMiddleware
from middleware.security import SecurityHeadersMiddleware
from middleware.tenant import TenantContextMiddleware
from middleware.trace import TraceIdMiddleware
from routers import (
    cropguard,
    cropguard_prices,
    dpa,
    farmland,
    health,
    health_db,
    tenants,
)

settings = get_settings()

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="EconomicBridge API",
    version=settings.app_version,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Inner-first add order (Starlette wraps in reverse):
app.add_middleware(AuditLogMiddleware)
app.add_middleware(TenantContextMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(TraceIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Trace-Id"],
)

app.include_router(health.router, prefix="/api/v1")
app.include_router(health_db.router, prefix="/api/v1")
app.include_router(tenants.router, prefix="/api/v1")
app.include_router(farmland.router, prefix="/api/v1")
app.include_router(cropguard.router, prefix="/api/v1")
app.include_router(cropguard_prices.router, prefix="/api/v1")
app.include_router(dpa.router, prefix="/api/v1")
