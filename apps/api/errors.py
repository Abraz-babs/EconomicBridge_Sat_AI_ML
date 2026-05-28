"""Global exception handlers that render errors in the CLAUDE.md §7 envelope.

Before this, only the tenant middleware and the DPA gate (Slice 19)
returned the standard `{success, data, error, meta}` shape — every
other endpoint's HTTPException came back as FastAPI's default
`{"detail": ...}`, and Pydantic 422s as `{"detail": [ ... ]}`. That
inconsistency means an API consumer (or the frontend's apiFetch) has
to special-case error parsing per endpoint.

These handlers normalise both:
  * `HTTPException`        — router-raised 400/404/409/503 etc.
  * `RequestValidationError` — Pydantic body/query validation 422s.

into the error envelope, stamping the request's trace_id. The DPA gate
keeps its own handler (registered separately) because DPAGateError is
a more-specific subclass — Starlette dispatches to the most specific
registered handler, so this general one never shadows it.

Registered in main.py via `app.add_exception_handler(...)`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


# Map HTTP status → a stable, descriptive error code (CLAUDE.md §7 uses
# SCREAMING_SNAKE codes like PERMISSION_DENIED). Routers that need a
# specific code raise HTTPException(detail={"code": ..., "message": ...});
# the rest get a sensible status-derived default here.
_STATUS_CODE_LABELS: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    410: "GONE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


def _trace_str(request: Request) -> str:
    trace = getattr(request.state, "trace_id", None)
    return str(trace) if trace else str(uuid4())


def _envelope(status_code: int, code: str, message: str, trace: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "data": None,
            "error": {"code": code, "message": message, "trace_id": trace},
            "meta": {
                "tenant_id": None,
                "trace_id": trace,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pagination": None,
            },
        },
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException,
) -> JSONResponse:
    """Render any HTTPException in the envelope.

    `detail` may be a plain string (most router raises) or a dict
    already carrying {code, message} (callers that want a specific
    code without a custom exception class). Both are handled.
    """
    trace = _trace_str(request)
    detail = exc.detail
    if isinstance(detail, dict) and "message" in detail:
        code = str(detail.get("code") or _STATUS_CODE_LABELS.get(
            exc.status_code, "ERROR"))
        message = str(detail["message"])
    else:
        code = _STATUS_CODE_LABELS.get(exc.status_code, "ERROR")
        message = detail if isinstance(detail, str) else str(detail)
    return _envelope(exc.status_code, code, message, trace)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError,
) -> JSONResponse:
    """Render Pydantic 422s in the envelope.

    The raw errors() list is summarised into a single human-readable
    message ("field 'x': reason; field 'y': reason"). The first
    offending field names are preserved in the message so existing
    tests asserting a field name appears in the response body still
    pass, and so clients get an actionable hint without us leaking the
    full pydantic error structure.
    """
    trace = _trace_str(request)
    parts: list[str] = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
        msg = err.get("msg", "invalid")
        parts.append(f"{loc}: {msg}" if loc else msg)
    message = "Request validation failed — " + "; ".join(parts) if parts else \
        "Request validation failed."
    return _envelope(422, "VALIDATION_ERROR", message, trace)
