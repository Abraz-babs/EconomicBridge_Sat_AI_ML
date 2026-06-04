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
import contextlib
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import get_settings
from dependencies import DPAGateError, dpa_gate_exception_handler
from errors import http_exception_handler, validation_exception_handler
from middleware.audit import AuditLogMiddleware
from middleware.module_access import ModuleAccessMiddleware
from middleware.security import SecurityHeadersMiddleware
from middleware.tenant import TenantContextMiddleware
from middleware.trace import TraceIdMiddleware
from routers import (
    admin_tenants,
    auth,
    aid_coordination,
    aid_coordination_bulk,
    cropguard,
    cropguard_ndvi,
    cropguard_prices,
    cropguard_prices_bulk,
    dpa,
    economic_mobility,
    economic_visibility,
    farmland,
    health,
    health_db,
    intelligence,
    overview,
    reports,
    shockguard,
    skills,
    tenants,
)

settings = get_settings()

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    # Load runtime-registered tenants (Phase 2) so super-admin-provisioned
    # tenants are accepted by is_valid_tenant_id without a redeploy.
    try:
        from sqlalchemy import text as _text

        from db.engine import get_session_factory
        from services.tenants import set_runtime_tenants

        factory = get_session_factory()
        async with factory() as session:
            rows = await session.execute(_text("SELECT id FROM public.tenant_registry"))
            set_runtime_tenants({r[0] for r in rows})
    except Exception as exc:  # noqa: BLE001 — never block startup on this
        logging.getLogger(__name__).warning(
            "startup: could not load tenant registry (%s)", exc,
        )
    yield


app = FastAPI(
    title="EconomicBridge API",
    version=settings.app_version,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# Error envelope (CLAUDE.md §7). Order of specificity matters — Starlette
# dispatches to the most-specific registered handler:
#   DPAGateError (subclass)  → dpa_gate_exception_handler  (Slice 14/19)
#   HTTPException (general)   → http_exception_handler      (Slice 23)
#   RequestValidationError    → validation_exception_handler (Slice 23)
app.add_exception_handler(DPAGateError, dpa_gate_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)

# Inner-first add order (Starlette wraps in reverse):
app.add_middleware(AuditLogMiddleware)
app.add_middleware(ModuleAccessMiddleware)
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
app.include_router(auth.router, prefix="/api/v1")
app.include_router(tenants.router, prefix="/api/v1")
app.include_router(farmland.router, prefix="/api/v1")
app.include_router(cropguard.router, prefix="/api/v1")
app.include_router(cropguard_prices.router, prefix="/api/v1")
app.include_router(cropguard_prices_bulk.router, prefix="/api/v1")
app.include_router(cropguard_ndvi.router, prefix="/api/v1")
app.include_router(economic_visibility.router, prefix="/api/v1")
app.include_router(economic_mobility.router, prefix="/api/v1")
app.include_router(aid_coordination.router, prefix="/api/v1")
app.include_router(aid_coordination_bulk.router, prefix="/api/v1")
app.include_router(shockguard.router, prefix="/api/v1")
app.include_router(skills.router, prefix="/api/v1")
app.include_router(intelligence.router, prefix="/api/v1")
app.include_router(overview.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(admin_tenants.router, prefix="/api/v1")
app.include_router(dpa.router, prefix="/api/v1")
