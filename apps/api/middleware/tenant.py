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
from jose import JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from core.security import decode_access_token
from services.tenants import is_valid_tenant_id

TENANT_HEADER = "X-Tenant-Id"
_ROLE_SUPER_ADMIN = "super_admin"


def _auth_claims(request: Request) -> dict | None:
    """Decoded access-token claims if a valid Bearer token is present, else None.

    A missing/invalid/expired token → None (treated as anonymous). Anonymous
    requests are NOT tenant-scoped here — the public overview teaser must keep
    working; scoping applies only to authenticated tenant accounts.
    """
    auth = request.headers.get("Authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    try:
        return decode_access_token(token.strip())
    except JWTError:
        return None


def _envelope(status_code: int, code: str, message: str, request: Request) -> JSONResponse:
    trace = str(getattr(request.state, "trace_id", ""))
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "data": None,
            "meta": {"tenant_id": None, "trace_id": trace, "timestamp": None, "pagination": None},
            "error": {"code": code, "message": message, "trace_id": trace},
        },
    )


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Read X-Tenant-Id, validate, scope authenticated users, expose on state."""

    async def dispatch(self, request: Request, call_next) -> Response:
        raw = request.headers.get(TENANT_HEADER)
        if raw is None or raw.strip() == "":
            request.state.tenant_id = None
            return await call_next(request)

        tenant_id = raw.strip().lower()
        if not is_valid_tenant_id(tenant_id):
            return _envelope(404, "TENANT_NOT_FOUND",
                             f"Unknown tenant: {tenant_id!r}", request)

        # Per-tenant access control: an AUTHENTICATED non-super-admin may only
        # reach tenants in their permitted_tenants (from the org). super-admin
        # and anonymous (public overview) are unrestricted. This is the security
        # boundary behind the UI's selector filtering — it stops a tenant account
        # (or its token) from reading another tenant's data.
        claims = _auth_claims(request)
        if claims is not None and claims.get("role") != _ROLE_SUPER_ADMIN:
            permitted = claims.get("tenants") or []
            if tenant_id not in permitted:
                return _envelope(
                    403, "TENANT_FORBIDDEN",
                    f"Your account does not have access to tenant '{tenant_id}'.",
                    request,
                )

        request.state.tenant_id = tenant_id
        return await call_next(request)
