"""Slice 23 — every API error response uses the CLAUDE.md §7 envelope.

Before Slice 23 only the tenant middleware + DPA gate returned the
envelope; router HTTPExceptions and Pydantic 422s came back as
FastAPI's default {"detail": ...}. These tests lock the normalised
contract: error responses always carry {success:false, data:null,
error:{code,message,trace_id}, meta:{trace_id,...}}.

The handlers are unit-tested directly with a minimal fake Request so
the default CI run (no Postgres) never trips over an endpoint's
get_session dependency. A single end-to-end check is marked
@pytest.mark.integration for the live-DB run.
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request

from errors import http_exception_handler, validation_exception_handler


def _fake_request() -> Request:
    """Minimal ASGI scope — enough for handlers that only read
    request.state.trace_id (absent here → handler synthesises one)."""
    return Request({"type": "http", "headers": [], "method": "GET", "path": "/"})


def _body(response) -> dict:
    return json.loads(bytes(response.body))


def _assert_envelope(body: dict) -> None:
    assert body["success"] is False
    assert body["data"] is None
    assert set(body["error"]) >= {"code", "message", "trace_id"}
    assert "trace_id" in body["meta"]
    assert body["error"]["trace_id"] == body["meta"]["trace_id"]


# ─── http_exception_handler ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_string_detail_maps_to_status_derived_code():
    exc = HTTPException(status_code=400, detail="X-Tenant-Id header is required")
    resp = await http_exception_handler(_fake_request(), exc)
    assert resp.status_code == 400
    body = _body(resp)
    _assert_envelope(body)
    assert body["error"]["code"] == "BAD_REQUEST"
    # Original message text preserved (substring contract for old tests).
    assert "X-Tenant-Id" in body["error"]["message"]


@pytest.mark.asyncio
async def test_404_maps_to_not_found():
    resp = await http_exception_handler(
        _fake_request(), HTTPException(status_code=404, detail="nope"))
    assert _body(resp)["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_dict_detail_uses_explicit_code():
    """A router can raise HTTPException(detail={code, message}) to set a
    specific code without a custom exception class."""
    exc = HTTPException(
        status_code=409,
        detail={"code": "ALREADY_RESOLVED", "message": "Alert already resolved"},
    )
    body = _body(await http_exception_handler(_fake_request(), exc))
    assert body["error"]["code"] == "ALREADY_RESOLVED"
    assert body["error"]["message"] == "Alert already resolved"


@pytest.mark.asyncio
async def test_unknown_status_falls_back_to_error_code():
    body = _body(await http_exception_handler(
        _fake_request(), HTTPException(status_code=418, detail="teapot")))
    assert body["error"]["code"] == "ERROR"


# ─── validation_exception_handler ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_validation_summarises_into_message_not_raw_list():
    exc = RequestValidationError([
        {"loc": ("query", "limit"), "msg": "Input should be less than or equal to 200",
         "type": "less_than_equal"},
    ])
    resp = await validation_exception_handler(_fake_request(), exc)
    assert resp.status_code == 422
    body = _body(resp)
    _assert_envelope(body)
    assert body["error"]["code"] == "VALIDATION_ERROR"
    # Offending field surfaced; raw pydantic list NOT leaked.
    assert "limit" in body["error"]["message"]
    assert "detail" not in body


@pytest.mark.asyncio
async def test_validation_handler_handles_empty_error_list():
    resp = await validation_exception_handler(
        _fake_request(), RequestValidationError([]))
    assert resp.status_code == 422
    assert _body(resp)["error"]["code"] == "VALIDATION_ERROR"


# ─── End-to-end (live DB) ──────────────────────────────────────────────────


@pytest.mark.integration
def test_router_422_round_trip_uses_envelope():
    """Full HTTP path: out-of-range limit → 422 enveloped. Marked
    integration because the endpoint resolves get_session."""
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    r = client.get(
        "/api/v1/economic_mobility/indicators",
        headers={"X-Tenant-Id": "kebbi"},
        params={"limit": 9999},
    )
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "detail" not in body
