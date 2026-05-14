"""TraceIdMiddleware — attaches a UUID trace_id to every request.

The trace_id is exposed on `request.state.trace_id` so handlers and other middleware
can include it in audit logs, error responses, and the response envelope's `meta`.
The same id is also echoed in the `X-Trace-Id` response header for downstream tooling.
"""
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Generate a request-scoped trace_id and stamp it on the response."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = uuid4()
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-Id"] = str(trace_id)
        return response
