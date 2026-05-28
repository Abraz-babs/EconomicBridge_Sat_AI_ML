"""Tests for POST /api/v1/predict/crop_disease/tiled.

Stub mode + persist=False so these don't touch torch or the DB.
"""
from __future__ import annotations

import base64
import io

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def _force_stub_mode():
    """Pin the singleton to stub mode — same trick as the single-leaf
    router tests so this suite doesn't depend on torch presence."""
    from models import crop_classifier as cc

    saved = cc._CLASSIFIER
    instance = cc.CropClassifier()
    instance._mode = "stub"
    cc._CLASSIFIER = instance
    yield
    cc._CLASSIFIER = saved


def _field_png_b64(width: int = 1024, height: int = 1024) -> str:
    """Build a real-bytes PNG of the requested size."""
    try:
        from PIL import Image
    except ImportError:
        return base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 64).decode()
    img = Image.new("RGB", (width, height), color=(140, 100, 70))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _body(**overrides) -> dict:
    base = {
        "tenant_id": "kebbi",
        "image_base64": _field_png_b64(),
        "rows": 4, "cols": 4,
        "persist": False,
    }
    base.update(overrides)
    return base


# ─── Happy path ───────────────────────────────────────────────────────────


def test_tiled_returns_envelope_with_16_tiles_default():
    response = client.post(
        "/api/v1/predict/crop_disease/tiled", json=_body(),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["tenant_id"] == "kebbi"
    assert data["rows"] == 4 and data["cols"] == 4
    assert len(data["tiles"]) == 16
    assert data["persisted"] is False
    assert data["model_name"] == "crop_classifier"


def test_tiled_hottest_tile_matches_max_in_tiles_list():
    response = client.post(
        "/api/v1/predict/crop_disease/tiled", json=_body(),
    )
    data = response.json()["data"]
    hottest = data["hottest_tile"]
    max_pred = max(t["prediction"] for t in data["tiles"])
    assert hottest["prediction"] == max_pred
    assert data["aggregate_prediction"] == hottest["prediction"]
    assert data["aggregate_class"] == hottest["predicted_class"]


def test_tiled_returns_source_and_tile_dims():
    response = client.post(
        "/api/v1/predict/crop_disease/tiled", json=_body(rows=2, cols=2),
    )
    data = response.json()["data"]
    assert data["source_width"] == 1024
    assert data["source_height"] == 1024
    assert data["tile_width"] == 512
    assert data["tile_height"] == 512


def test_tiled_custom_grid_shape():
    """Asymmetric 2×4 grid → 8 tiles."""
    response = client.post(
        "/api/v1/predict/crop_disease/tiled", json=_body(rows=2, cols=4),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["rows"] == 2 and data["cols"] == 4
    assert len(data["tiles"]) == 8


# ─── Validation ───────────────────────────────────────────────────────────


def test_tiled_unknown_tenant_returns_404():
    response = client.post(
        "/api/v1/predict/crop_disease/tiled",
        json=_body(tenant_id="atlantis"),
    )
    assert response.status_code == 404


def test_tiled_rejects_rows_above_max():
    response = client.post(
        "/api/v1/predict/crop_disease/tiled",
        json=_body(rows=99),
    )
    assert response.status_code == 422


def test_tiled_rejects_invalid_base64():
    response = client.post(
        "/api/v1/predict/crop_disease/tiled",
        json=_body(image_base64="not!!valid_base64@@"),
    )
    assert response.status_code == 422


def test_tiled_rejects_image_too_small_for_grid():
    """500×500 / 4×4 grid → 125×125 tiles, below MIN_TILE_PIXELS=224.
    The service raises ValueError → router returns 422."""
    response = client.post(
        "/api/v1/predict/crop_disease/tiled",
        json=_body(image_base64=_field_png_b64(500, 500), rows=4, cols=4),
    )
    assert response.status_code == 422
    # Slice 24: §7 envelope — message under error.message.
    assert "too small" in response.json()["error"]["message"].lower()


def test_tiled_rejects_unknown_fields():
    response = client.post(
        "/api/v1/predict/crop_disease/tiled",
        json=_body(mystery_field="x"),
    )
    assert response.status_code == 422


# ─── Geometry sanity ─────────────────────────────────────────────────────


def test_tiled_tiles_form_a_covering_grid():
    response = client.post(
        "/api/v1/predict/crop_disease/tiled", json=_body(rows=2, cols=2),
    )
    data = response.json()["data"]
    seen = set()
    for t in data["tiles"]:
        key = (t["row"], t["col"])
        assert key not in seen
        seen.add(key)
    # All four cells of the 2x2 grid are present.
    assert seen == {(0, 0), (0, 1), (1, 0), (1, 1)}
