"""ActivityMiddleware — count each authenticated request against its account.

Pure-ASGI for the same reason as ModuleAccessMiddleware: `BaseHTTPMiddleware`
copies `request.state`, which corrupts trace-id/tenant-id propagation. We read
the path and headers straight off the ASGI `scope` and never touch state.

Costs one JWT decode and one dict increment per request — no I/O. The counts
are written by the background flusher in `services.activity`.

Anonymous traffic is deliberately not counted. The public overview is open by
design ([[feedback_open_access_model]]); there is no account to attribute it
to, and mixing it in would inflate every usage figure with crawler hits.
"""
from __future__ import annotations

from jose import JWTError
from starlette.types import ASGIApp, Receive, Scope, Send

from core.security import decode_access_token
from services.activity import record
from services.modules import PATH_PREFIX_TO_MODULE

# Paths that say nothing about how an account uses the platform. Health checks
# run every few seconds from the load balancer and would swamp the counts;
# token refresh and /me are machinery the dashboard calls on a timer, not
# something a person chose to look at.
#
# These are matched against real registered routes — `/api/v1/health`, not
# `/api/health`. A prefix that matches nothing fails silently (it just counts
# the traffic it was meant to exclude), so test_health_checks_are_not_counted
# in tests/test_admin_activity_integration.py pins them.
_IGNORED_PREFIXES: tuple[str, ...] = (
    "/api/v1/health",
    "/api/docs",
    "/api/redoc",
    "/api/openapi",
    "/api/v1/auth/refresh",
    "/api/v1/auth/me",
    "/api/v1/auth/my-modules",
)


def _module_for_path(path: str) -> str | None:
    parts = [p for p in path.split("/") if p]
    if len(parts) < 3 or parts[0] != "api" or parts[1] != "v1":
        return None
    return PATH_PREFIX_TO_MODULE.get(parts[2])


class ActivityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith(_IGNORED_PREFIXES):
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            self._count(path, headers)

        await self.app(scope, receive, send)

    @staticmethod
    def _count(path: str, headers: dict[str, str]) -> None:
        scheme, _, token = headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return
        try:
            claims = decode_access_token(token.strip())
        except JWTError:
            return  # an invalid token is not account activity

        user_id = claims.get("sub")
        if not user_id:
            return
        record(
            user_id=str(user_id),
            org_id=str(claims["org"]) if claims.get("org") else None,
            tenant_id=(headers.get("x-tenant-id") or "").strip().lower() or None,
            module=_module_for_path(path),
        )
