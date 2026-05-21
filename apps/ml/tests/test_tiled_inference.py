"""Unit tests for services/tiled_inference.py.

The classifier is stubbed via a tiny FakeClassifier that mirrors the
narrow surface tile_and_predict touches: `version` property + `predict()`
returning (ModelPrediction, list[CropTopKEntry]). That way these tests
exercise the tiling + aggregation logic without paying torch's load
cost or asking for a trained .pth.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import pytest

from models.crop_classifier import (  # noqa: E402 — order after importorskip
    CROP_CLASSES,
    CropPredictionInput,
    CropTopKEntry,
)
from models.prediction import ModelPrediction  # noqa: E402
from services.tiled_inference import (  # noqa: E402
    MAX_GRID_DIM,
    tile_and_predict,
)

PIL_Image = pytest.importorskip("PIL.Image")


# ─── Fake classifier ──────────────────────────────────────────────────────


@dataclass
class FakeClassifier:
    """Deterministic stub: top-1 class index = sum(image bytes) mod 12,
    confidence = 0.10 + (sum mod 90) / 100. Lets us assert that
    different tiles produce different predictions without torch."""

    version: str = "0.1.0-stub"
    call_count: int = 0

    def predict(
        self, *, tenant_id: str, image: CropPredictionInput, top_k: int | None = None,
    ) -> tuple[ModelPrediction, list[CropTopKEntry]]:
        self.call_count += 1
        # Derive a stable index from the image hash so each tile gets
        # its own answer.
        digest_byte = int(image.image_sha256[:2], 16)
        idx = digest_byte % len(CROP_CLASSES)
        confidence = 0.10 + (digest_byte % 90) / 100.0
        predicted_class = CROP_CLASSES[idx]
        flagged = not predicted_class.endswith("_healthy")
        prediction_score = confidence if flagged else 1.0 - confidence
        from models.prediction import band_for_confidence
        band = band_for_confidence(confidence)
        entries = [
            CropTopKEntry(class_name=predicted_class, probability=confidence),
        ]
        # Fill out to top_k if asked
        k = top_k or 1
        for i in range(1, k):
            other_idx = (idx + i) % len(CROP_CLASSES)
            entries.append(
                CropTopKEntry(
                    class_name=CROP_CLASSES[other_idx],
                    probability=max(0.0, (confidence - 0.05 * i)),
                )
            )
        prediction = ModelPrediction(
            model_name="crop_classifier",
            model_version=self.version,
            tenant_id=tenant_id,
            prediction=prediction_score,
            confidence=confidence,
            shap_values={},
            input_hash=image.image_sha256,
            inference_time_ms=0,
            timestamp=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc,
            ),
            requires_human_review=band != "HIGH",
            confidence_band=band,
            features={
                "predicted_class": predicted_class,
                "image_source": image.image_source,
                "execution_mode": "stub",
                "top_k": [
                    {"class_name": e.class_name, "probability": e.probability}
                    for e in entries
                ],
            },
        )
        return prediction, entries


def _gradient_png(width: int, height: int) -> bytes:
    """Make a colorful gradient image so each tile differs visibly."""
    import numpy as np
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        for x in range(width):
            arr[y, x] = (x % 256, y % 256, (x + y) % 256)
    buf = io.BytesIO()
    PIL_Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


# ─── Grid validation ──────────────────────────────────────────────────────


def test_tile_and_predict_rejects_rows_below_one():
    with pytest.raises(ValueError, match="rows must be"):
        tile_and_predict(
            tenant_id="kebbi",
            image_bytes=_gradient_png(1024, 1024),
            classifier=FakeClassifier(),
            rows=0, cols=4,
        )


def test_tile_and_predict_rejects_cols_above_max():
    with pytest.raises(ValueError, match="cols must be"):
        tile_and_predict(
            tenant_id="kebbi",
            image_bytes=_gradient_png(1024, 1024),
            classifier=FakeClassifier(),
            rows=4, cols=MAX_GRID_DIM + 1,
        )


def test_tile_and_predict_rejects_image_too_small_for_grid():
    """A 900×900 image / 4×4 grid → 225×225 tiles, just over min. But
    900 / 5 = 180 < MIN_TILE_PIXELS=224 → reject."""
    with pytest.raises(ValueError, match="too small"):
        tile_and_predict(
            tenant_id="kebbi",
            image_bytes=_gradient_png(900, 900),
            classifier=FakeClassifier(),
            rows=5, cols=5,
        )


def test_tile_and_predict_rejects_undecodable_image():
    with pytest.raises(ValueError, match="decode source image"):
        tile_and_predict(
            tenant_id="kebbi",
            image_bytes=b"not-an-image",
            classifier=FakeClassifier(),
            rows=2, cols=2,
        )


# ─── Tiling math ──────────────────────────────────────────────────────────


def test_tile_and_predict_produces_rows_times_cols_tiles():
    classifier = FakeClassifier()
    result = tile_and_predict(
        tenant_id="kebbi",
        image_bytes=_gradient_png(1024, 1024),
        classifier=classifier,
        rows=4, cols=4,
    )
    assert len(result.tiles) == 16
    assert classifier.call_count == 16


def test_tile_and_predict_tile_dims_use_floor_division():
    """1023 / 4 = 255 (floor) — last column's right edge ends at
    255 * 4 = 1020. The remaining 3 px on the right are intentionally
    discarded to keep tiles uniform."""
    result = tile_and_predict(
        tenant_id="kebbi",
        image_bytes=_gradient_png(1023, 1023),
        classifier=FakeClassifier(),
        rows=4, cols=4,
    )
    assert result.tile_width == 255
    assert result.tile_height == 255


def test_tile_and_predict_bboxes_tile_the_image():
    result = tile_and_predict(
        tenant_id="kebbi",
        image_bytes=_gradient_png(1024, 1024),
        classifier=FakeClassifier(),
        rows=4, cols=4,
    )
    # No overlap: bboxes form a covering grid.
    seen = set()
    for t in result.tiles:
        bbox = (t.bbox_x, t.bbox_y, t.bbox_w, t.bbox_h)
        assert bbox not in seen, f"Duplicate bbox {bbox}"
        seen.add(bbox)
        # bbox must be inside the source.
        assert 0 <= t.bbox_x < result.source_width
        assert 0 <= t.bbox_y < result.source_height


def test_tile_and_predict_row_col_indices_are_consistent():
    result = tile_and_predict(
        tenant_id="kebbi",
        image_bytes=_gradient_png(1024, 1024),
        classifier=FakeClassifier(),
        rows=4, cols=4,
    )
    for t in result.tiles:
        # row/col map back into bbox via tile dims.
        assert t.bbox_x == t.col * result.tile_width
        assert t.bbox_y == t.row * result.tile_height


# ─── Aggregation ──────────────────────────────────────────────────────────


def test_hottest_tile_is_max_by_prediction():
    result = tile_and_predict(
        tenant_id="kebbi",
        image_bytes=_gradient_png(1024, 1024),
        classifier=FakeClassifier(),
        rows=4, cols=4,
    )
    hottest = max(result.tiles, key=lambda t: t.prediction)
    assert result.hottest_tile == hottest
    assert result.aggregate_prediction == hottest.prediction
    assert result.aggregate_class == hottest.predicted_class


def test_total_inference_time_is_non_negative():
    result = tile_and_predict(
        tenant_id="kebbi",
        image_bytes=_gradient_png(1024, 1024),
        classifier=FakeClassifier(),
        rows=2, cols=2,
    )
    assert result.total_inference_time_ms >= 0


def test_image_sha256_is_of_source_bytes_not_tiles():
    """The aggregate row's input_hash references the SOURCE image so
    callers can re-run the analysis to reproduce per-tile detail."""
    image_bytes = _gradient_png(1024, 1024)
    result = tile_and_predict(
        tenant_id="kebbi",
        image_bytes=image_bytes,
        classifier=FakeClassifier(),
        rows=2, cols=2,
    )
    import hashlib
    expected = hashlib.sha256(image_bytes).hexdigest()
    assert result.image_sha256 == expected


# ─── Trivial grid (1×1) — same as single predict ──────────────────────────


def test_one_by_one_grid_is_a_single_tile():
    classifier = FakeClassifier()
    result = tile_and_predict(
        tenant_id="kebbi",
        image_bytes=_gradient_png(256, 256),  # 256 ≥ MIN_TILE_PIXELS=224
        classifier=classifier,
        rows=1, cols=1,
    )
    assert len(result.tiles) == 1
    assert classifier.call_count == 1
    only = result.tiles[0]
    assert only.bbox_x == 0 and only.bbox_y == 0
    assert only.bbox_w == 256 and only.bbox_h == 256
    assert result.hottest_tile == only
