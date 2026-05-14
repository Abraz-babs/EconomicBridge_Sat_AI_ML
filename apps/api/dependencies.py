"""FastAPI dependencies (auth, tenant context).

These are placeholders until JWT auth lands in a later step. Endpoints that should remain
public (health, openapi) skip the auth dependency entirely. Once JWT is
implemented:
  - `require_authenticated_user` verifies the bearer token and returns the User
  - `get_tenant_id` returns the tenant_id from the verified claims (never from body)
See CLAUDE.md §4.1 and §4.2.
"""
from fastapi import HTTPException, status


async def require_authenticated_user() -> None:
    """Placeholder that rejects until JWT auth is implemented."""

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Authentication not yet implemented",
    )
