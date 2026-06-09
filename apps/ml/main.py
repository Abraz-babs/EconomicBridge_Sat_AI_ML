"""EconomicBridge — ML Service.

Run from apps/ml/ with the shared dev venv (plus ML libs installed):
    python -m uvicorn main:app --host 127.0.0.1 --port 8002

Swagger UI:  http://localhost:8002/api/docs
OpenAPI:     http://localhost:8002/api/openapi.json

Today this service:
  - exposes POST /api/v1/predict/conflict (Random Forest + SHAP)
  - writes inferences to tenant_<id>.conflict_predictions

Next iterations:
  - U-Net flood detector (Step 10)
  - ResNet-50 crop disease classifier (Step 11)
  - Conflict-predictor v2 trained on Citadel's real labelled set
"""
from __future__ import annotations

import logging
import sys
import uuid
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.responses import Response  # noqa: E402

from fastapi.exceptions import RequestValidationError  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402

from config import get_settings  # noqa: E402
from errors import http_exception_handler, validation_exception_handler  # noqa: E402
from routers import (  # noqa: E402
    health,
    predict,
    predict_crop,
    predict_crop_tiled,
    predict_yield,
)

settings = get_settings()

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = uuid.uuid4()
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-Id"] = str(trace_id)
        return response


class UrlPrefixStripMiddleware:
    """Strip the ALB deployment path prefix before routing (pure ASGI).

    ALB listener rules forward paths UNCHANGED, so behind ``/ml/*`` a request
    for ``/ml/api/v1/health`` arrives here while the app serves
    ``/api/v1/health``. Strips the configured prefix when present; passes
    everything else through (dev + target-group health checks unaffected).
    Enabled only when ``URL_PREFIX`` is set (the ECS task definition sets it).
    """

    def __init__(self, app, prefix: str) -> None:
        self.app = app
        self.prefix = "/" + prefix.strip("/")

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            if path == self.prefix or path.startswith(self.prefix + "/"):
                scope = dict(scope)
                scope["path"] = path[len(self.prefix):] or "/"
        await self.app(scope, receive, send)


import contextlib  # noqa: E402


@contextlib.asynccontextmanager
async def _lifespan(_app: "FastAPI"):
    # Accept super-admin-provisioned tenants (Phase 2) without a redeploy.
    try:
        from db import load_runtime_tenants
        await load_runtime_tenants()
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("startup: tenant load failed (%s)", exc)
    yield


app = FastAPI(
    title="EconomicBridge — ML Service",
    version=settings.app_version,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=_lifespan,
)

# Error envelope (CLAUDE.md §7) — Slice 24.
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)

app.add_middleware(TraceIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["X-Trace-Id"],
)
# Added LAST → runs OUTERMOST, so the prefix is gone before anything routes.
if settings.url_prefix:
    app.add_middleware(UrlPrefixStripMiddleware, prefix=settings.url_prefix)

app.include_router(health.router, prefix="/api/v1")
app.include_router(predict.router, prefix="/api/v1")
app.include_router(predict_crop.router, prefix="/api/v1")
app.include_router(predict_crop_tiled.router, prefix="/api/v1")
app.include_router(predict_yield.router, prefix="/api/v1")
