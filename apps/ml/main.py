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

from config import get_settings  # noqa: E402
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


app = FastAPI(
    title="EconomicBridge — ML Service",
    version=settings.app_version,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

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
app.include_router(predict.router, prefix="/api/v1")
app.include_router(predict_crop.router, prefix="/api/v1")
app.include_router(predict_crop_tiled.router, prefix="/api/v1")
app.include_router(predict_yield.router, prefix="/api/v1")
