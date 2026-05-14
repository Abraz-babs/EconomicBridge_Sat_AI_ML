"""EconomicBridge — Satellite Ingestion Service.

Run from `apps/ingestion/` with the shared dev venv:
    python -m uvicorn main:app --host 127.0.0.1 --port 8001

Swagger UI:  http://localhost:8001/api/docs
OpenAPI:     http://localhost:8001/api/openapi.json

Today this service:
  - exposes `/api/v1/ingest/firms` for manual trigger (synchronous)
  - polls NASA FIRMS via apps/ingestion/sources/nasa_firms.py
  - writes detections into `tenant_<id>.heat_signatures`
  - records every run in `public.ingestion_runs`

When Celery + Redis land it will additionally:
  - run `tasks.firms_ingest` on a 24h beat schedule per active tenant
  - expose `/api/v1/ingest/runs` for status queries
  - back the manual trigger with `delay()` -> 202 Accepted with job_id
"""
from __future__ import annotations

import logging
import sys
import uuid
from pathlib import Path

# Make sibling modules importable when launched directly.
INGESTION_ROOT = Path(__file__).resolve().parent
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.responses import Response  # noqa: E402

from config import get_settings  # noqa: E402
from routers import health, triggers  # noqa: E402

settings = get_settings()

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Per-request trace_id on request.state + X-Trace-Id response header."""

    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = uuid.uuid4()
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-Id"] = str(trace_id)
        return response


app = FastAPI(
    title="EconomicBridge — Satellite Ingestion",
    version=settings.app_version,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(TraceIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,  # server-to-server only
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["X-Trace-Id"],
)

app.include_router(health.router, prefix="/api/v1")
app.include_router(triggers.router, prefix="/api/v1")
