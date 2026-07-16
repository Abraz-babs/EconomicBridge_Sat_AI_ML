"""Password-reset flow — token unit tests + DB-free HTTP contract checks."""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from jose import JWTError

from core.security import (
    create_invite_token,
    create_reset_token,
    decode_invite_token,
    decode_reset_token,
)
from main import app

client = TestClient(app)


# ─── Token semantics ──────────────────────────────────────────────────────


def test_reset_token_round_trips():
    uid = uuid4()
    assert decode_reset_token(create_reset_token(uid)) == uid


def test_reset_token_is_not_an_invite_and_vice_versa():
    """The `typ` claim keeps the two single-purpose tokens from ever being
    replayed as each other — an invite must not reset a password, and a
    reset link must not activate an account."""
    uid = uuid4()
    with pytest.raises(JWTError):
        decode_invite_token(create_reset_token(uid))
    with pytest.raises(JWTError):
        decode_reset_token(create_invite_token(uid))


def test_garbage_reset_token_rejected():
    with pytest.raises(JWTError):
        decode_reset_token("not-a-token")


# ─── HTTP contract (DB-free via OpenAPI) ──────────────────────────────────


def test_forgot_and_reset_routes_registered():
    spec = client.get("/api/openapi.json").json()
    assert "/api/v1/auth/forgot-password" in spec["paths"]
    assert "/api/v1/auth/reset-password" in spec["paths"]


def test_forgot_request_requires_valid_email_shape():
    r = client.post("/api/v1/auth/forgot-password", json={"email": "not-an-email"})
    assert r.status_code == 422


def test_reset_request_enforces_password_length():
    spec = client.get("/api/openapi.json").json()
    schema = spec["components"]["schemas"]["ResetPasswordRequest"]["properties"]
    assert schema["password"]["minLength"] == 8
    assert schema["password"]["maxLength"] == 72
