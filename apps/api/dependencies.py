"""FastAPI dependencies (auth, tenant context, DPA enforcement).

Per CLAUDE.md §4.1 and §4.2:
  - `require_authenticated_user` — JWT bearer check; placeholder for now.
  - `require_signed_dpa` — DPA enforcement gate (Slice 14). Blocks
    PII-bearing routes until the organisation calling has a signed,
    unexpired DataProcessingAgreement covering the requested tenant.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session


async def require_authenticated_user() -> None:
    """Placeholder that rejects until JWT auth is implemented."""

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Authentication not yet implemented",
    )


# ─── DPA enforcement gate (Slice 14) ─────────────────────────────────────


ORG_HEADER = "X-Organisation-Id"


class DPAGateError(HTTPException):
    """403 with a stable error code so the frontend can branch on it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": code, "message": message},
        )


async def require_signed_dpa(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UUID:
    """Block the request unless a signed, unexpired DPA covers the
    (organisation, tenant) pair.

    Contract:
      * `X-Tenant-Id` must already be validated by TenantContextMiddleware
        (request.state.tenant_id non-None). Routes that need this gate
        therefore also require a tenant header — adding both at once.
      * `X-Organisation-Id` must be a valid UUID. We do NOT 401 on
        missing/invalid here — we 403 with `DPA_REQUIRED` so the error
        is consistent regardless of whether the org just forgot the
        header or genuinely has no DPA. The frontend treats both as
        "request access" CTAs.
      * One row in `public.data_processing_agreements` must match:
          organisation_id = :org_id
          AND tenant_id = :tenant_id
          AND status = 'signed'
          AND (expires_at IS NULL OR expires_at > NOW())

    Returns the organisation_id for the route handler to use (e.g. for
    audit-log enrichment). Also stamps it onto request.state so the
    AuditLogMiddleware can pick it up without re-parsing the header.

    Why a dependency rather than a middleware:
      * The set of "PII routes" is tiny relative to the API surface.
        Per-route opt-in is clearer than a path-pattern matcher in a
        middleware (which goes stale as routes are renamed).
      * Each route gets its own dependency injection point — easy to
        add per-action audit notes later.
      * Health/admin/free-tier routes simply omit the dependency.
    """
    # Tenant header is validated upstream by TenantContextMiddleware.
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise DPAGateError(
            "TENANT_REQUIRED",
            f"{ORG_HEADER} requires a valid X-Tenant-Id header on the same request.",
        )

    raw_org = request.headers.get(ORG_HEADER, "").strip()
    if not raw_org:
        raise DPAGateError(
            "DPA_REQUIRED",
            f"This endpoint requires {ORG_HEADER} matching a signed DPA "
            f"for tenant '{tenant_id}'.",
        )
    try:
        org_id = UUID(raw_org)
    except ValueError as exc:
        raise DPAGateError(
            "DPA_REQUIRED",
            f"{ORG_HEADER} must be a UUID.",
        ) from exc

    # Look up an active DPA. SQL not ORM because the dependency runs
    # before the route's session is committed for anything else, and
    # asyncpg encodes the UUID directly.
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
        {"org_id": org_id, "tenant_id": tenant_id},
    )
    if result.first() is None:
        raise DPAGateError(
            "DPA_REQUIRED",
            f"No signed Data Processing Agreement found for organisation "
            f"{org_id} on tenant '{tenant_id}'. Request access via the "
            f"compliance team.",
        )

    request.state.organisation_id = org_id
    return org_id
