"""Tests for the Slice 14 DPA enforcement gate.

The gate is a FastAPI dependency (`dependencies.require_signed_dpa`)
applied to PII routes — currently GET + PATCH on
`/api/v1/dpa/data-subject-requests`. It rejects requests whose calling
organisation has no signed, unexpired Data Processing Agreement for the
requested tenant.

Two layers of coverage:

* **Unit tests** (default `pytest`): exercise every short-circuit path
  that does NOT need the DB — missing/invalid headers, OpenAPI shape.
* **Integration tests** (`@pytest.mark.integration`): full round-trip
  against the live DB, seeding Organisation + DataProcessingAgreement
  rows to verify each DPA status / expiry combination.

Known cascade: Python 3.12 + asyncpg teardown emits
'RuntimeError: Event loop is closed' when multiple TestClient(app)
instances run in sequence. Each unit test passes in isolation
(`pytest tests/test_dpa_enforcement.py::<name>`) but pytest reports
2 failures when all run together. Same issue surfaces across the
codebase (test_predict_router.py, etc.) — out of scope for Slice 14.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


# ─── Unit tests (no DB) ───────────────────────────────────────────────────


def test_dsr_list_without_any_headers_returns_403_tenant_required():
    """No X-Tenant-Id → tenant check fires first, gate doesn't reach DB."""
    r = client.get("/api/v1/dpa/data-subject-requests")
    assert r.status_code == 403, r.text
    body = r.json()
    assert body["detail"]["code"] == "TENANT_REQUIRED"


def test_dsr_list_with_tenant_but_no_org_returns_403_dpa_required():
    r = client.get(
        "/api/v1/dpa/data-subject-requests",
        headers={"X-Tenant-Id": "kebbi"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "DPA_REQUIRED"


def test_dsr_list_with_invalid_org_uuid_returns_403_dpa_required():
    """A garbage X-Organisation-Id value is the same UX as no DPA: ask
    the caller to register an agreement. We don't 400 here so the
    frontend can branch on a single error code."""
    r = client.get(
        "/api/v1/dpa/data-subject-requests",
        headers={
            "X-Tenant-Id": "kebbi",
            "X-Organisation-Id": "not-a-uuid",
        },
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "DPA_REQUIRED"
    assert "UUID" in r.json()["detail"]["message"]


def test_dsr_patch_inherits_the_same_gate():
    """PATCH on a DSR has the same gate as GET — confirm one of the
    short-circuits fires before the path even reaches the row lookup."""
    fake_id = uuid.uuid4()
    r = client.patch(
        f"/api/v1/dpa/data-subject-requests/{fake_id}",
        json={"status": "in_review"},
        headers={"X-Tenant-Id": "kebbi"},  # tenant set, org missing
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "DPA_REQUIRED"


def test_dsr_post_is_not_gated():
    """Submitting a DSR is the data subject's right — anyone can do it.
    Slice 14 intentionally does NOT gate POST so subjects with no
    organisational affiliation can still file requests."""
    r = client.post(
        "/api/v1/dpa/data-subject-requests",
        json={
            "tenant_id": "kebbi",
            "request_type": "access",
            "subject_phone_e164": "+2348012345678",
        },
    )
    # Without DB the create endpoint will likely 500 or succeed (depending
    # on whether the test runs against a live DB). The important assertion
    # is that it does NOT come back 403 DPA_REQUIRED.
    if r.status_code == 403:
        body = r.json()
        assert body.get("detail", {}).get("code") != "DPA_REQUIRED"


def test_dsr_list_openapi_advertises_the_dpa_gate():
    """The OpenAPI description must mention the gate so partners know
    they need a DPA before integrating."""
    spec = client.get("/api/openapi.json").json()
    op = spec["paths"]["/api/v1/dpa/data-subject-requests"]["get"]
    description = op.get("description", "")
    assert "DPA" in description or "Data Processing Agreement" in description


def test_dsr_patch_openapi_advertises_the_dpa_gate():
    spec = client.get("/api/openapi.json").json()
    op = spec["paths"]["/api/v1/dpa/data-subject-requests/{dsr_id}"]["patch"]
    description = op.get("description", "")
    assert "DPA" in description or "Data Processing Agreement" in description


# ─── Integration tests (live DB) ──────────────────────────────────────────


def _create_org_and_dpa(
    *,
    tenant_id: str,
    dpa_status: str = "signed",
    expires_at: datetime | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed an Organisation + a DPA row. Returns (org_id, dpa_id) so the
    test can clean up the DPA via the same connection.

    The Organisation row is NOT cleaned up because of an
    audit_log_actor_org_id_fkey + audit_log INSERT-only RULE
    interaction that breaks Postgres' FK validation on DELETE. Leaving
    orgs in public.organisations is harmless — UUID PK guarantees no
    name collision between test runs."""
    from sqlalchemy import create_engine, text
    from config import get_settings

    sync_url = get_settings().database_url_sync
    engine = create_engine(sync_url, future=True)
    org_id = uuid.uuid4()
    dpa_id = uuid.uuid4()
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO public.organisations (
                        id, org_id, name, type,
                        permitted_tenants, bilateral_agreements,
                        dpa_signed, is_active
                    ) VALUES (
                        :id, :code, :name, 'ngo',
                        ARRAY[:tenant_id]::varchar[],
                        ARRAY[]::varchar[],
                        false, true
                    )
                    """
                ),
                {
                    "id": org_id,
                    "code": f"slice14-test-{org_id.hex[:8]}",
                    "name": f"Slice14 Test Org {org_id.hex[:8]}",
                    "tenant_id": tenant_id,
                },
            )
            # agreement_type CHECK constraint allows
            # 'mou' | 'dpa' | 'bilateral' | 'research' (see migration 0010).
            conn.execute(
                text(
                    """
                    INSERT INTO public.data_processing_agreements (
                        id, organisation_id, tenant_id, agreement_type,
                        status, signed_at, expires_at
                    ) VALUES (
                        :id, :org_id, :tenant_id, 'dpa',
                        :status,
                        CASE WHEN :status = 'signed'
                             THEN NOW() ELSE NULL END,
                        :expires_at
                    )
                    """
                ),
                {
                    "id": dpa_id,
                    "org_id": org_id,
                    "tenant_id": tenant_id,
                    "status": dpa_status,
                    "expires_at": expires_at,
                },
            )
    finally:
        engine.dispose()
    return org_id, dpa_id


def _cleanup(org_id: uuid.UUID, dpa_id: uuid.UUID) -> None:
    """Delete only the DPA — the org row is left in place (see the
    Organisation comment in `_create_org_and_dpa`)."""
    from sqlalchemy import create_engine, text
    from config import get_settings

    engine = create_engine(get_settings().database_url_sync, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM public.data_processing_agreements WHERE id = :id"),
                {"id": dpa_id},
            )
    finally:
        engine.dispose()
    # The org_id parameter is kept on the function signature for symmetry
    # with _create_org_and_dpa and to document the lifecycle contract.
    _ = org_id


@pytest.mark.integration
def test_dsr_list_with_signed_dpa_succeeds():
    org_id, dpa_id = _create_org_and_dpa(tenant_id="kebbi", dpa_status="signed")
    try:
        r = client.get(
            "/api/v1/dpa/data-subject-requests",
            headers={
                "X-Tenant-Id": "kebbi",
                "X-Organisation-Id": str(org_id),
            },
        )
        assert r.status_code == 200, r.text
    finally:
        _cleanup(org_id, dpa_id)


@pytest.mark.integration
def test_dsr_list_with_pending_dpa_returns_403():
    org_id, dpa_id = _create_org_and_dpa(tenant_id="kebbi", dpa_status="pending")
    try:
        r = client.get(
            "/api/v1/dpa/data-subject-requests",
            headers={
                "X-Tenant-Id": "kebbi",
                "X-Organisation-Id": str(org_id),
            },
        )
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "DPA_REQUIRED"
    finally:
        _cleanup(org_id, dpa_id)


@pytest.mark.integration
def test_dsr_list_with_expired_dpa_returns_403():
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    org_id, dpa_id = _create_org_and_dpa(
        tenant_id="kebbi", dpa_status="signed", expires_at=yesterday,
    )
    try:
        r = client.get(
            "/api/v1/dpa/data-subject-requests",
            headers={
                "X-Tenant-Id": "kebbi",
                "X-Organisation-Id": str(org_id),
            },
        )
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "DPA_REQUIRED"
    finally:
        _cleanup(org_id, dpa_id)


@pytest.mark.integration
def test_dsr_list_with_dpa_for_different_tenant_returns_403():
    """Cross-tenant isolation: a DPA for Kebbi must NOT grant access to
    Zamfara. This is the core of multi-tenant compliance."""
    org_id, dpa_id = _create_org_and_dpa(tenant_id="kebbi", dpa_status="signed")
    try:
        r = client.get(
            "/api/v1/dpa/data-subject-requests",
            headers={
                "X-Tenant-Id": "zamfara",
                "X-Organisation-Id": str(org_id),
            },
        )
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "DPA_REQUIRED"
    finally:
        _cleanup(org_id, dpa_id)
