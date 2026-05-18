"""AuditLogMiddleware — writes one row to public.audit_log per mutating request.

Captures the WHO/WHAT/WHEN/WHERE for every POST / PUT / PATCH / DELETE that
the API serves, per CLAUDE.md §4.6:

  > EVERY data-modifying operation writes to the audit log.
  > Audit log table is INSERT-only — the application user has no DELETE permission.

Design notes:
* The audit write happens AFTER `call_next` returns so we know the response's
  status_code. We never leak the response body into audit metadata — only the
  envelope-level shape (method, path, status, tenant, trace).
* The insert uses a brand-new session, NOT the per-request session injected by
  the route handler. That session's transaction is already committed/rolled-back
  by the time we get here, so we'd be writing to a closed scope. A separate
  session also ensures audit failures cannot rollback business writes.
* Fail-soft. If the audit insert itself errors (DB down, RLS, etc.) we log it
  and return the original response. CLAUDE.md says "ALL data-modifying ops
  write to the audit log" — but a transient audit-insert failure must not
  break a customer-facing 200. Operators get the stderr trail.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = logging.getLogger(__name__)

MUTATING_METHODS: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _action_type(method: str, path: str) -> str:
    """Derive a coarse action label from the HTTP method + URL path.

    Designed to be queryable: `SELECT count(*) WHERE action_type='UPDATE_ALERT'`
    is more useful than a free-text method+path concatenation. Falls back to
    `<METHOD>_<resource>` for unrecognised routes.
    """
    p = path.lower()
    if "/farmland/alerts" in p:
        if method == "PATCH":
            return "UPDATE_ALERT"
        if method == "POST":
            return "CREATE_ALERT"
        if method == "DELETE":
            return "DELETE_ALERT"
    if "/subscribers" in p:
        if method == "POST":
            return "CREATE_SUBSCRIBER"
        if method == "PATCH":
            return "UPDATE_SUBSCRIBER"
        if method == "DELETE":
            return "DELETE_SUBSCRIBER"
    if "/notify/" in p:
        return "DISPATCH_NOTIFICATION"
    if "/dpa/agreements" in p:
        if method == "POST":
            return "CREATE_DPA_AGREEMENT"
        if method == "PATCH":
            return "UPDATE_DPA_AGREEMENT"
    if "/dpa/data-subject-requests" in p:
        if method == "POST":
            return "CREATE_DSR"
        if method == "PATCH":
            return "UPDATE_DSR"
    # Generic fallback so we always have *something* to query on.
    segments = [s for s in p.strip("/").split("/") if s and not s.startswith("api")]
    resource = segments[-1] if segments else "ROOT"
    return f"{method}_{resource.upper()}"


def _data_type(path: str) -> str | None:
    """Coarse resource label so analytics can group rows by data domain."""
    p = path.lower()
    if "/farmland/alerts" in p:
        return "alert_event"
    if "/subscribers" in p:
        return "alert_subscriber"
    if "/notify/" in p:
        return "sms_dispatch"
    if "/dpa/agreements" in p:
        return "dpa_agreement"
    if "/dpa/data-subject-requests" in p:
        return "data_subject_request"
    return None


def _client_ip(request: Request) -> str | None:
    """Best-effort client IP: trust X-Forwarded-For first, fall back to client.host."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


def _severity_for_status(status_code: int) -> str:
    if status_code >= 500:
        return "ERROR"
    if status_code >= 400:
        return "WARNING"
    return "INFO"


class AuditLogMiddleware(BaseHTTPMiddleware):
    """INSERT one row into public.audit_log per mutating request."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        path = request.url.path
        skip_audit = (
            request.method not in MUTATING_METHODS
            or path.startswith("/api/docs")
            or path.startswith("/api/openapi")
        )

        # Wrap call_next so we log unhandled 5xx errors too. Starlette re-raises
        # exceptions through middleware in debug mode; without this `try` an
        # exception-derived 500 would bypass our audit insert entirely.
        try:
            response = await call_next(request)
        except Exception:
            if not skip_audit:
                synthetic = Response(status_code=500)
                try:
                    await self._insert(request, synthetic)
                except Exception:  # noqa: BLE001
                    log.exception(
                        "audit-log INSERT failed for unhandled exception path=%s",
                        path,
                    )
            raise

        if skip_audit:
            return response

        try:
            await self._insert(request, response)
        except Exception:  # noqa: BLE001 — fail-soft per docstring
            log.exception(
                "audit-log INSERT failed (request still served) method=%s path=%s",
                request.method,
                path,
            )
        return response

    async def _insert(self, request: Request, response: Response) -> None:
        # Local import keeps the module importable when db.engine isn't yet
        # configured (e.g. during unit tests that bypass the engine entirely).
        from db.engine import get_session_factory

        trace_id = getattr(request.state, "trace_id", None)
        if trace_id is None:
            # TraceIdMiddleware should always set this; if it didn't, there's
            # a wiring bug. Skip rather than write a row with NULL trace_id
            # (the column is NOT NULL).
            log.warning("audit-log skipped: trace_id missing on request.state")
            return

        tenant_id = getattr(request.state, "tenant_id", None)
        params: dict[str, Any] = {
            "trace_id": trace_id,
            "tenant_schema": f"tenant_{tenant_id}" if tenant_id else None,
            "action_type": _action_type(request.method, request.url.path),
            "http_method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "ip_address": _client_ip(request),
            "data_type": _data_type(request.url.path),
            "severity": _severity_for_status(response.status_code),
        }

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO public.audit_log (
                        trace_id, tenant_schema, action_type, http_method,
                        path, status_code, ip_address, data_type, severity
                    ) VALUES (
                        :trace_id, :tenant_schema, :action_type, :http_method,
                        :path, :status_code, CAST(:ip_address AS INET), :data_type, :severity
                    )
                    """
                ),
                params,
            )
            await session.commit()
