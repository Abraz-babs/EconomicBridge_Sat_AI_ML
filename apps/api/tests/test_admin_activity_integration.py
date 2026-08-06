"""The activity panel is super-admin only.

A partner account (NASRDA and similar) holds `tenant_admin` and must never be
able to enumerate other accounts, even though it can read every pilot tenant's
data. Counting behaviour is covered in test_activity_unit.py, against the
middleware directly — it needs no database and so stays deterministic.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from core.security import create_access_token
from main import app

ENDPOINT = "/api/v1/admin/activity"

# One client for the module, matching the rest of the suite. A per-test client
# would spin up a new event loop each time while the asyncpg pool stays bound
# to the first one, so the second DB-touching test in the file fails with
# "Event loop is closed" — a fixture artefact, not a defect in the code.
client = TestClient(app)


def _token(role: str) -> str:
    return create_access_token(
        user_id=uuid4(), role=role, org_id=uuid4(),
        permitted_tenants=["kebbi", "niger"],
    )


def test_anonymous_is_401():
    assert client.get(ENDPOINT).status_code == 401


def test_tenant_admin_is_403():
    """A partner account can read tenant data but not the account roster."""
    r = client.get(ENDPOINT, headers={"Authorization": f"Bearer {_token('tenant_admin')}"})

    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"


def test_detail_endpoint_is_also_403_for_tenant_admin():
    r = client.get(
        f"{ENDPOINT}/{uuid4()}",
        headers={"Authorization": f"Bearer {_token('tenant_admin')}"},
    )

    assert r.status_code == 403
