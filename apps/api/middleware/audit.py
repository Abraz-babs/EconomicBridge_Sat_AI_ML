"""AuditLogMiddleware (STUB).

Once the DB is wired, this middleware must INSERT a row into `audit_log` for every
mutating request (POST / PUT / PATCH / DELETE), capturing tenant_id, user_id, action,
resource, trace_id, ip_address, and timestamp (CLAUDE.md §4.6, §6).

Until then it just logs to stdout — enough to verify the middleware order is right.
GET and HEAD requests are exempt because they don't change state.
"""
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = logging.getLogger(__name__)

MUTATING_METHODS: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Placeholder audit logger — emits a structured log line for every mutating call."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        if request.method in MUTATING_METHODS and response.status_code < 500:
            log.info(
                "audit method=%s path=%s status=%d tenant=%s trace=%s",
                request.method,
                request.url.path,
                response.status_code,
                getattr(request.state, "tenant_id", None),
                getattr(request.state, "trace_id", None),
            )
        return response
