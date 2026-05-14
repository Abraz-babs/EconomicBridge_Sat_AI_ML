"""TenantContextMiddleware — read X-Tenant-Id and stamp request.state.

The middleware itself does NOT touch the database. It only validates the header
against the tenant allowlist and stashes the validated ID on `request.state`.
The DB session (db/engine.get_session) reads that state and applies
`SET search_path TO tenant_{id}, public` for the lifetime of the session.

Header is optional — anonymous / tenant-agnostic endpoints (e.g. /health) work
without it. If the header is present but unknown, the request is rejected with
a 404 so callers cannot probe the allowlist by error-message shape.

This middleware replaces the Step 3 stub. JWT-derived tenant identity is NOT
used (Step 5's auth layer was removed in favour of open access — see
docs/PROGRESS.md). When paid-tier auth lands, the auth layer will set
`request.state.tenant_id` BEFORE this middleware runs and we'll skip the header
check for authenticated requests.
"""
from __future__ import annotations

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from services.tenants import is_valid_tenant_id

TENANT_HEADER = "X-Tenant-Id"


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Read X-Tenant-Id, validate, and expose on request.state."""

    async def dispatch(self, request: Request, call_next) -> Response:
        raw = request.headers.get(TENANT_HEADER)
        if raw is None or raw.strip() == "":
            request.state.tenant_id = None
            return await call_next(request)

        tenant_id = raw.strip().lower()
        if not is_valid_tenant_id(tenant_id):
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "data": None,
                    "meta": {
                        "tenant_id": None,
                        "trace_id": str(getattr(request.state, "trace_id", "")),
                        "timestamp": None,
                        "pagination": None,
                    },
                    "error": {
                        "code": "TENANT_NOT_FOUND",
                        "message": f"Unknown tenant: {tenant_id!r}",
                        "trace_id": str(getattr(request.state, "trace_id", "")),
                    },
                },
            )

        request.state.tenant_id = tenant_id
        return await call_next(request)
