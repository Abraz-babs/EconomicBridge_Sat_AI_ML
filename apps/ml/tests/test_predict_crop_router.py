"""Tests for POST /api/v1/predict/crop_disease.

Same pattern as test_predict_router.py — `persist=False` for non-DB tests,
`persist=True` is integration-only. Torch is not installed in this test
suite, so the classifier runs in stub mode (which is what we want — keeps
the API contract honest while not paying a 750MB install for unit tests).
"""
from __future__ import annotations

import base64
import hashlib

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


# ─── Helpers ──────────────────────────────────────────────────────────────


def _tiny_png_b64() -> str:
    """A tiny PNG-looking blob that's enough for the request to validate.

    We're in stub mode (no torch) so the bytes are never actually decoded
    by PIL — the classifier hashes them and derives probabilities from
    the hash."""
    return base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 64).decode()


def _body(**overrides) -> dict:
    base = {
        "tenant_id": "kebbi",
        "image_base64": _tiny_png_b64(),
        "persist": False,
    }
    base.update(overrides)
    return base


# ─── Happy path ───────────────────────────────────────────────────────────


def test_predict_crop_returns_envelope_with_prediction_data():
    response = client.post("/api/v1/predict/crop_disease", json=_body())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["tenant_id"] == "kebbi"
    assert data["model_name"] == "crop_classifier"
    assert data["model_version"].startswith("0.1.0-")
    assert 0.0 <= data["prediction"] <= 1.0
    assert 0.0 <= data["confidence"] <= 1.0
    assert data["confidence_band"] in ("HIGH", "MEDIUM", "LOW")
    assert data["persisted"] is False
    assert data["prediction_id"] is None
    # Top-3 default.
    assert len(data["top_k"]) == 3
    # Image provenance.
    assert data["image_source"] == "inline"
    assert data["image_s3_key"] is None
    assert data["image_s3_bucket"] is None
    # SHA-256 of the decoded bytes.
    raw = base64.b64decode(_tiny_png_b64())
    assert data["image_sha256"] == hashlib.sha256(raw).hexdigest()


def test_predict_crop_respects_custom_top_k():
    response = client.post(
        "/api/v1/predict/crop_disease", json=_body(top_k=5),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["top_k"]) == 5


def test_predict_crop_stub_mode_requires_human_review():
    """Stub + untuned modes never auto-route."""
    response = client.post("/api/v1/predict/crop_disease", json=_body())
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["requires_human_review"] is True
    # Model version reflects stub mode.
    assert data["model_version"].endswith("-stub") or \
           data["model_version"].endswith("-untuned")


# ─── Validation ───────────────────────────────────────────────────────────


def test_predict_crop_unknown_tenant_returns_404():
    response = client.post(
        "/api/v1/predict/crop_disease", json=_body(tenant_id="atlantis"),
    )
    assert response.status_code == 404


def test_predict_crop_requires_image_source():
    body = _body()
    del body["image_base64"]
    response = client.post("/api/v1/predict/crop_disease", json=body)
    # Pydantic rejects with 422 because the model_validator fires.
    assert response.status_code == 422


def test_predict_crop_rejects_both_image_sources():
    body = _body(
        image_s3_bucket="eb-imagery",
        image_s3_key="kebbi/sentinel-2-l2a/2026/05/19/some.jpg",
    )
    response = client.post("/api/v1/predict/crop_disease", json=body)
    assert response.status_code == 422


def test_predict_crop_rejects_invalid_base64():
    body = _body(image_base64="not!!!valid_base64@@@")
    response = client.post("/api/v1/predict/crop_disease", json=body)
    assert response.status_code == 422


def test_predict_crop_rejects_empty_image():
    body = _body(image_base64=base64.b64encode(b"").decode())
    response = client.post("/api/v1/predict/crop_disease", json=body)
    assert response.status_code == 422


def test_predict_crop_rejects_oversized_inline_image():
    """Inline images must stay under MAX_INLINE_IMAGE_BYTES (8 MiB)."""
    huge = base64.b64encode(b"x" * (9 * 1024 * 1024)).decode()
    body = _body(image_base64=huge)
    response = client.post("/api/v1/predict/crop_disease", json=body)
    assert response.status_code == 422


def test_predict_crop_rejects_top_k_out_of_range():
    body = _body(top_k=0)
    response = client.post("/api/v1/predict/crop_disease", json=body)
    assert response.status_code == 422


def test_predict_crop_rejects_unknown_fields():
    body = _body(mystery_field="x")
    response = client.post("/api/v1/predict/crop_disease", json=body)
    assert response.status_code == 422


# ─── S3 path is gated behind 501 in Slice 5a ──────────────────────────────


def test_predict_crop_s3_path_returns_501_in_slice_5a():
    """The Pydantic schema accepts S3-keyed requests, but the route raises
    501 until Slice 5c wires the actual fetch. Callers get a clear signal
    instead of a confusing 500."""
    body = {
        "tenant_id": "kebbi",
        "image_s3_bucket": "eb-imagery",
        "image_s3_key": "kebbi/sentinel-2-l2a/2026/05/19/scene.jpg",
        "persist": False,
    }
    response = client.post("/api/v1/predict/crop_disease", json=body)
    assert response.status_code == 501
    assert "Slice 5c" in response.json()["detail"]


def test_predict_crop_s3_path_rejects_cross_tenant_key():
    """S3 key must be prefixed with the requesting tenant id."""
    body = {
        "tenant_id": "kebbi",
        "image_s3_bucket": "eb-imagery",
        "image_s3_key": "benue/sentinel-2-l2a/2026/05/19/scene.jpg",
        "persist": False,
    }
    response = client.post("/api/v1/predict/crop_disease", json=body)
    assert response.status_code == 422
    assert "cross-tenant" in str(response.json()).lower()


# ─── Top-K ordering contract ──────────────────────────────────────────────


def test_predict_crop_top_k_descending():
    response = client.post("/api/v1/predict/crop_disease", json=_body(top_k=4))
    assert response.status_code == 200
    top_k = response.json()["data"]["top_k"]
    probs = [entry["probability"] for entry in top_k]
    assert probs == sorted(probs, reverse=True)


def test_predict_crop_top1_matches_predicted_class():
    response = client.post("/api/v1/predict/crop_disease", json=_body())
    data = response.json()["data"]
    assert data["predicted_class"] == data["top_k"][0]["class_name"]
