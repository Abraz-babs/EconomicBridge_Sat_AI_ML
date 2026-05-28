"""FastAPI dependencies for the notifications service.

Currently exposes only `require_signed_dpa` (Slice 17): the same DPA
enforcement gate Slice 14 applied to the API service's DSR endpoints,
ported to the notifications service for routes that touch subscriber
phone numbers or fire real SMS.

Why a separate copy instead of importing from apps/api/:
  * The two services have distinct DB engines + session factories
    (apps/notifications/db.py vs apps/api/db/engine.py). Cross-service
    Python imports would entangle their dependency stacks.
  * The notifications service has no TenantContextMiddleware — every
    route reads `X-Tenant-Id` from headers directly via
    `_require_tenant(request)`. The API service's gate reads
    `request.state.tenant_id` set by middleware. This copy mirrors
    the notifications convention: read the header here too.

If a third service ever needs DPA enforcement, the pattern's small
enough to copy again rather than build a shared package.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from db import get_session_factory, is_valid_tenant_id


ORG_HEADER = "X-Organisation-Id"
TENANT_HEADER = "X-Tenant-Id"


class DPAGateError(HTTPException):
    """403 with a stable error code so the frontend can branch on it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": code, "message": message},
        )


async def dpa_gate_exception_handler(
    request: Request, exc: DPAGateError,
) -> JSONResponse:
    """Render DPAGateError in the standard response envelope (CLAUDE.md §7).
    Mirror of the API service's handler — keeps the 403 shape consistent
    across services so a single frontend error-parser handles both."""
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    trace = getattr(request.state, "trace_id", None)
    trace_str = str(trace) if trace else str(uuid4())
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "data": None,
            "error": {
                "code": detail.get("code", "DPA_REQUIRED"),
                "message": detail.get("message", "Access denied."),
                "trace_id": trace_str,
            },
            "meta": {
                "tenant_id": None,
                "trace_id": trace_str,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pagination": None,
            },
        },
    )


async def require_signed_dpa(request: Request) -> UUID:
    """Block the request unless a signed, unexpired DPA covers the
    (organisation, tenant) pair.

    Headers:
      * `X-Tenant-Id` — pilot tenant slug (validated against allowlist).
      * `X-Organisation-Id` — UUID matching a row in
        `public.data_processing_agreements` with status='signed' AND
        (expires_at IS NULL OR expires_at > NOW()).

    Returns the organisation_id so the route can use it for audit
    enrichment, and stamps it on request.state for the trace logger.

    DB session is acquired lazily inside the function (after the
    header checks short-circuit) so the reject path never opens a
    Postgres connection. Same pattern as the API service's gate,
    avoids the CI "connection refused" failure when no DB exists.
    """
    raw_tenant = (request.headers.get(TENANT_HEADER) or "").strip().lower()
    if not raw_tenant:
        raise DPAGateError(
            "TENANT_REQUIRED",
            f"{ORG_HEADER} requires a valid {TENANT_HEADER} header on the same request.",
        )
    if not is_valid_tenant_id(raw_tenant):
        raise DPAGateError(
            "TENANT_REQUIRED",
            f"Unknown tenant: {raw_tenant!r}",
        )

    raw_org = (request.headers.get(ORG_HEADER) or "").strip()
    if not raw_org:
        raise DPAGateError(
            "DPA_REQUIRED",
            f"This endpoint requires {ORG_HEADER} matching a signed DPA "
            f"for tenant '{raw_tenant}'.",
        )
    try:
        org_id = UUID(raw_org)
    except ValueError as exc:
        raise DPAGateError(
            "DPA_REQUIRED",
            f"{ORG_HEADER} must be a UUID.",
        ) from exc

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                """
                SELECT 1
                  FROM public.data_processing_agreements
                 WHERE organisation_id = :org_id
                   AND tenant_id = :tenant_id
                   AND status = 'signed'
                   AND (expires_at IS NULL OR expires_at > NOW())
                 LIMIT 1
                """
            ),
            {"org_id": org_id, "tenant_id": raw_tenant},
        )
        if result.first() is None:
            raise DPAGateError(
                "DPA_REQUIRED",
                f"No signed Data Processing Agreement found for organisation "
                f"{org_id} on tenant '{raw_tenant}'. Request access via the "
                f"compliance team.",
            )

    request.state.organisation_id = org_id
    return org_id
