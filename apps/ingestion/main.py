"""EconomicBridge — Satellite Ingestion Service.

Run from `apps/ingestion/` with the shared dev venv:
    python -m uvicorn main:app --host 127.0.0.1 --port 8001

Swagger UI:  http://localhost:8001/api/docs
OpenAPI:     http://localhost:8001/api/openapi.json

What this service does today:
  - POST /api/v1/ingest/firms  — manual NASA FIRMS pull + alert promotion
  - GET  /api/v1/passes/upcoming — live N2YO satellite-pass schedule
  - GET  /api/v1/scheduler/jobs — introspect the in-process scheduler
  - Scheduled: daily 06:00 UTC FIRMS pull for every pilot tenant

When Celery + Redis land the in-process APScheduler moves to Celery beat
and the manual trigger becomes a delay()-fronted 202 Accepted.
"""
from __future__ import annotations

import logging
import sys
import uuid
from contextlib import asynccontextmanager
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
from routers import health, jobs, passes, triggers  # noqa: E402
from scheduler import setup_scheduler  # noqa: E402

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the scheduler on app boot, stop it on shutdown.

    The scheduler instance is attached to `app.state` so the introspection
    endpoint can read its jobs without holding a module-level singleton.
    """
    scheduler = setup_scheduler()
    scheduler.start()
    app.state.scheduler = scheduler
    log = logging.getLogger(__name__)
    log.info(
        "scheduler started — jobs: %s",
        [j.id for j in scheduler.get_jobs()],
    )
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        log.info("scheduler stopped")


app = FastAPI(
    title="EconomicBridge — Satellite Ingestion",
    version=settings.app_version,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
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
app.include_router(passes.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
