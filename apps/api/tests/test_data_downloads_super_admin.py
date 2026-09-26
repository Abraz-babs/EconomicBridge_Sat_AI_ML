"""Data downloads are a paid service: only the super-admin may take a file.

Partner accounts (NASRDA staff and similar) hold `tenant_admin`. They view on
the dashboard but can never download the village list or a report, and an
anonymous visitor can't either. Operator rule, 2026-09-26.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from core.security import create_access_token
from main import app



@pytest.fixture(scope="module")
def client():
    # One event loop for the whole module: the tenant middleware reads the
    # database, and a bare TestClient opens a new loop per request, which the
    # asyncpg pool (bound to the first loop) cannot survive.
    with TestClient(app) as c:
        yield c

DOWNLOADS = [
    "/api/v1/economic_visibility/village-light/export.csv?scope=unlit",
    "/api/v1/economic_visibility/village-light/export.csv?scope=all",
    "/api/v1/reports/export.csv?module=farmland",
    "/api/v1/reports/export.pdf?module=farmland",
]


def _token(role: str) -> str:
    return create_access_token(
        user_id=uuid4(), role=role, org_id=uuid4(),
        permitted_tenants=["kebbi", "niger"],
    )


@pytest.mark.parametrize("path", DOWNLOADS)
def test_anonymous_visitor_cannot_download(client, path):
    r = client.get(path, headers={"X-Tenant-Id": "kebbi"})
    assert r.status_code == 401


@pytest.mark.parametrize("path", DOWNLOADS)
def test_partner_account_cannot_download(client, path):
    r = client.get(path, headers={
        "X-Tenant-Id": "kebbi",
        "Authorization": f"Bearer {_token('tenant_admin')}",
    })
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"
