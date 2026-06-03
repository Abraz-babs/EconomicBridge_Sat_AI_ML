"""Per-tenant module access enforcement (pure-ASGI).

Blocks an API call to a module the active tenant isn't entitled to (403
MODULE_NOT_SUBSCRIBED). UI tab-hiding isn't security — this is the real gate.

Implemented as a pure-ASGI middleware (NOT BaseHTTPMiddleware) so it never
wraps/copies `request.state` — BaseHTTPMiddleware does, which corrupts the
trace-id/tenant-id propagation other middlewares rely on. We read the path +
X-Tenant-Id straight from the ASGI `scope`, short-circuit with a 403 when the
tenant lacks the module, and otherwise pass through untouched. Only paths that
map to a module are gated; control-plane paths (overview, admin, health, …) and
tenant-less requests pass through. Entitlements are cached (services/modules.py).
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from services.modules import PATH_PREFIX_TO_MODULE, enabled_modules_for


def _module_for_path(path: str) -> str | None:
    parts = [p for p in path.split("/") if p]
    if len(parts) < 3 or parts[0] != "api" or parts[1] != "v1":
        return None
    return PATH_PREFIX_TO_MODULE.get(parts[2])


class ModuleAccessMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        module = _module_for_path(scope.get("path", ""))
        if module is not None:
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            tenant = (headers.get("x-tenant-id") or "").strip().lower()
            if tenant:
                enabled = await enabled_modules_for(tenant)
                if module not in enabled:
                    await _forbidden(tenant, module)(scope, receive, send)
                    return

        await self.app(scope, receive, send)


def _forbidden(tenant: str, module: str) -> JSONResponse:
    trace = str(uuid4())
    return JSONResponse(
        status_code=403,
        content={
            "success": False,
            "data": None,
            "error": {
                "code": "MODULE_NOT_SUBSCRIBED",
                "message": (
                    f"Tenant '{tenant}' is not subscribed to the '{module}' "
                    "module. A super-admin controls module access."
                ),
                "trace_id": trace,
            },
            "meta": {
                "tenant_id": tenant,
                "trace_id": trace,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pagination": None,
            },
        },
    )
