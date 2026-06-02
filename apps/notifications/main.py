"""EconomicBridge — Notifications Service.

Run from apps/notifications/ with the shared dev venv:
    python -m uvicorn main:app --host 127.0.0.1 --port 8003

Swagger UI:  http://localhost:8003/api/docs

Today this service:
  - exposes POST /api/v1/notify/conflict (synchronous dispatch)
  - exposes GET/POST /api/v1/subscribers (per-tenant CRUD)
  - dispatches via Termii (Nigeria) or Twilio (ECOWAS) per
    tenants.yaml's sms_gateway field
  - falls back to a MockGateway when no provider keys are configured

When Celery + Redis land:
  - ML service posts to /notify/conflict on every HIGH-band prediction
    (or queues directly via the outbox worker pattern)
  - A retry worker scans public.sms_outbox for status='failed' rows
"""
from __future__ import annotations

import logging
import sys
import uuid
from pathlib import Path

NOTIF_ROOT = Path(__file__).resolve().parent
if str(NOTIF_ROOT) not in sys.path:
    sys.path.insert(0, str(NOTIF_ROOT))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.responses import Response  # noqa: E402

from fastapi.exceptions import RequestValidationError  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402

from config import get_settings  # noqa: E402
from dependencies import DPAGateError, dpa_gate_exception_handler  # noqa: E402
from errors import http_exception_handler, validation_exception_handler  # noqa: E402
from routers import health, notify, subscribers, subscribers_bulk  # noqa: E402

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


app = FastAPI(
    title="EconomicBridge — Notifications",
    version=settings.app_version,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Error envelope (CLAUDE.md §7). DPAGateError (subclass) keeps its own
# handler; the general HTTPException + validation handlers (Slice 24)
# cover everything else.
app.add_exception_handler(DPAGateError, dpa_gate_exception_handler)
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

app.include_router(health.router, prefix="/api/v1")
app.include_router(subscribers.router, prefix="/api/v1")
app.include_router(subscribers_bulk.router, prefix="/api/v1")
app.include_router(notify.router, prefix="/api/v1")
