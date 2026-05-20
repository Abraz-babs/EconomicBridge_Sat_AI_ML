"""Unit tests for models/crop_classifier.py.

Torch is NEVER imported here. CI runs on the stub-mode fallback so we
don't pay 750MB for a unit-test suite. The trained / untuned paths are
covered conceptually by the loader test which patches torch.import.
"""
from __future__ import annotations

import hashlib

import pytest

from models.crop_classifier import (
    CROP_CLASSES,
    CropClassifier,
    CropPredictionInput,
    _stub_probabilities,
    _top_k_entries,
    hash_image_bytes,
)


def _input(*, payload: bytes = b"a tiny png-like blob") -> CropPredictionInput:
    digest = hashlib.sha256(payload).hexdigest()
    return CropPredictionInput(
        image_bytes=payload,
        image_sha256=digest,
        image_source="inline",
    )


# ─── _stub_probabilities ───────────────────────────────────────────────────


def test_stub_probabilities_sums_to_one():
    sha = hashlib.sha256(b"hello").hexdigest()
    probs = _stub_probabilities(sha)
    assert len(probs) == len(CROP_CLASSES)
    assert pytest.approx(sum(probs), rel=1e-9) == 1.0
    assert all(0.0 <= p <= 1.0 for p in probs)


def test_stub_probabilities_deterministic_per_hash():
    sha = hashlib.sha256(b"reproducible").hexdigest()
    assert _stub_probabilities(sha) == _stub_probabilities(sha)


def test_stub_probabilities_differs_across_inputs():
    a = _stub_probabilities(hashlib.sha256(b"input-a").hexdigest())
    b = _stub_probabilities(hashlib.sha256(b"input-b").hexdigest())
    assert a != b


def test_stub_probabilities_has_distinct_top_class():
    sha = hashlib.sha256(b"need a winner").hexdigest()
    probs = _stub_probabilities(sha)
    top1, top2 = sorted(probs, reverse=True)[:2]
    # The boost should make top1 strictly larger.
    assert top1 > top2


# ─── _top_k_entries ────────────────────────────────────────────────────────


def test_top_k_entries_returns_descending_probabilities():
    probs = [0.1] * len(CROP_CLASSES)
    probs[5] = 0.4
    probs[8] = 0.3
    entries = _top_k_entries(probs, k=3)
    assert len(entries) == 3
    assert entries[0].class_name == CROP_CLASSES[5]
    assert entries[0].probability == 0.4
    assert entries[1].probability == 0.3
    assert entries[0].probability >= entries[1].probability >= entries[2].probability


def test_top_k_entries_caps_at_class_count():
    probs = [1.0 / len(CROP_CLASSES)] * len(CROP_CLASSES)
    entries = _top_k_entries(probs, k=len(CROP_CLASSES))
    assert len(entries) == len(CROP_CLASSES)
    # All class names appear exactly once.
    assert {e.class_name for e in entries} == set(CROP_CLASSES)


# ─── hash_image_bytes ──────────────────────────────────────────────────────


def test_hash_image_bytes_is_sha256():
    blob = b"\xff\xd8\xff\xe0" + b"fake-jpeg"
    assert hash_image_bytes(blob) == hashlib.sha256(blob).hexdigest()


def test_hash_image_bytes_differs_per_input():
    assert hash_image_bytes(b"a") != hash_image_bytes(b"b")


# ─── CropClassifier in stub mode ───────────────────────────────────────────


def _fresh_stub_classifier(monkeypatch) -> CropClassifier:
    """Force stub mode by making the torch import fail."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("torch is not available in this test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    return CropClassifier()


def test_classifier_stub_mode_returns_valid_prediction(monkeypatch):
    classifier = _fresh_stub_classifier(monkeypatch)

    prediction, top_k = classifier.predict(
        tenant_id="kebbi", image=_input(), top_k=3,
    )
    assert classifier.mode == "stub"
    assert prediction.model_name == "crop_classifier"
    assert prediction.model_version == "0.1.0-stub"
    assert prediction.tenant_id == "kebbi"
    assert 0.0 <= prediction.prediction <= 1.0
    assert 0.0 <= prediction.confidence <= 1.0
    assert prediction.confidence_band in ("HIGH", "MEDIUM", "LOW")
    # Stub mode never auto-routes.
    assert prediction.requires_human_review is True
    # The features blob carries the top-K class list.
    assert prediction.features["execution_mode"] == "stub"
    assert prediction.features["predicted_class"] in CROP_CLASSES
    assert len(prediction.features["top_k"]) == 3
    # SHAP intentionally empty in Slice 5a — arrives in Slice 5e.
    assert prediction.shap_values == {}
    # Top-K leaderboard mirrors the features blob.
    assert len(top_k) == 3
    assert top_k[0].class_name == prediction.features["predicted_class"]


def test_classifier_stub_mode_requires_human_review_always(monkeypatch):
    """Regardless of confidence, stub mode is never auto-routed."""
    classifier = _fresh_stub_classifier(monkeypatch)
    prediction, _ = classifier.predict(tenant_id="kebbi", image=_input())
    assert prediction.requires_human_review is True


def test_classifier_prediction_score_is_disease_probability_mass(monkeypatch):
    """`prediction` = total probability mass on disease (non-healthy) classes.

    Healthy top-1 pulls mass into healthy classes → prediction below the
    7/12 = 0.583 uniform baseline. Disease top-1 → prediction stays at or
    above the baseline. Either way, top-1's probability must be in the
    sum if it's a disease class."""
    classifier = _fresh_stub_classifier(monkeypatch)
    prediction, _ = classifier.predict(tenant_id="kebbi", image=_input())
    top1 = prediction.features["predicted_class"]
    if top1.endswith("_healthy"):
        assert prediction.prediction < 0.583  # below uniform baseline
    else:
        # Top-1 confidence is part of the disease-mass sum.
        assert prediction.prediction >= prediction.confidence


def test_classifier_rejects_top_k_zero(monkeypatch):
    classifier = _fresh_stub_classifier(monkeypatch)
    with pytest.raises(ValueError, match="top_k must be"):
        classifier.predict(tenant_id="kebbi", image=_input(), top_k=0)


def test_classifier_rejects_top_k_exceeding_class_count(monkeypatch):
    classifier = _fresh_stub_classifier(monkeypatch)
    with pytest.raises(ValueError, match="top_k must be"):
        classifier.predict(
            tenant_id="kebbi", image=_input(), top_k=len(CROP_CLASSES) + 1,
        )


def test_classifier_same_image_same_prediction(monkeypatch):
    """Stub mode must be deterministic per input."""
    classifier = _fresh_stub_classifier(monkeypatch)
    a, _ = classifier.predict(tenant_id="kebbi", image=_input(payload=b"X"))
    b, _ = classifier.predict(tenant_id="kebbi", image=_input(payload=b"X"))
    assert a.features["predicted_class"] == b.features["predicted_class"]
    assert a.confidence == b.confidence
    assert a.prediction == b.prediction


def test_classifier_different_images_different_predictions(monkeypatch):
    classifier = _fresh_stub_classifier(monkeypatch)
    a, _ = classifier.predict(tenant_id="kebbi", image=_input(payload=b"alpha"))
    b, _ = classifier.predict(tenant_id="kebbi", image=_input(payload=b"beta"))
    # Different images must produce different top-K leaderboards (not
    # necessarily different top-1 by chance, but the leaderboard order
    # or probabilities must differ).
    assert a.features["top_k"] != b.features["top_k"]


# ─── Class list contract ──────────────────────────────────────────────────


def test_class_list_has_exactly_twelve_classes():
    assert len(CROP_CLASSES) == 12


def test_class_list_covers_expected_crops():
    crops = {name.split("_")[0] for name in CROP_CLASSES}
    assert crops == {"cassava", "maize", "rice", "tomato", "plantain"}


def test_class_list_includes_healthy_variant_per_crop():
    healthy = {name for name in CROP_CLASSES if name.endswith("_healthy")}
    assert healthy == {
        "cassava_healthy", "maize_healthy", "rice_healthy",
        "tomato_healthy", "plantain_healthy",
    }
