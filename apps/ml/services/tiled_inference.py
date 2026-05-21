"""Tile a large field photo into a grid and predict on each tile.

Slice 5e-a — the inner loop of the Sentinel-2 pipeline (Slice 5e-b)
without depending on Sentinel-2 imagery. Any uploaded large image
gets chopped into `rows × cols` tiles; each tile runs through the
existing `CropClassifier.predict()`; results are aggregated so the
dashboard can render a heatmap grid and surface the worst-affected
tile as the headline result.

Tile extraction is deterministic: floor(W/cols) × floor(H/rows). Any
remainder pixels along the right + bottom edges are discarded — they
would otherwise produce ragged tiles that bias the prediction.

Per-tile saliency is OFF by default (computing 16× Grad-CAM passes
adds ~2.4s on CPU). The caller can opt in for the hottest tile only
via the `saliency_for_hottest_tile` request flag handled at the
router layer.

The classifier instance is shared across tiles (one warm load).
"""
from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.crop_classifier import CropClassifier, CropTopKEntry

log = logging.getLogger(__name__)


# Hard cap so a malicious / accidental request can't grind the service
# to a halt by asking for 100×100 = 10 000 tiles.
MAX_GRID_DIM: int = 8
MIN_GRID_DIM: int = 1

# Min source-image dimension per tile. Anything smaller is rejected
# loudly — ResNet-50 wants 224×224 inputs and tiles smaller than this
# produce blurry, low-information predictions.
MIN_TILE_PIXELS: int = 224


# ─── Dataclasses ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TileResult:
    """One tile's prediction. Geometry is in the ORIGINAL image's pixel space."""

    row: int
    col: int
    bbox_x: int       # left edge in original-image px
    bbox_y: int       # top edge in original-image px
    bbox_w: int       # tile width in px
    bbox_h: int       # tile height in px
    predicted_class: str
    prediction: float
    confidence: float
    confidence_band: str   # HIGH | MEDIUM | LOW
    top_k: tuple["CropTopKEntry", ...]


@dataclass(frozen=True, slots=True)
class TiledInferenceResult:
    """Aggregate of all tile predictions for one analysis."""

    tenant_id: str
    rows: int
    cols: int
    source_width: int
    source_height: int
    tile_width: int
    tile_height: int
    tiles: tuple[TileResult, ...]
    # Headline: the most concerning tile (highest prediction score).
    hottest_tile: TileResult
    # Aggregate prediction = the hottest tile's prediction. Same scale,
    # but lets the dashboard's "score" widget read a single value.
    aggregate_prediction: float
    aggregate_class: str
    model_name: str
    model_version: str
    total_inference_time_ms: int
    image_sha256: str        # SHA-256 of the SOURCE image bytes


# ─── Entry point ──────────────────────────────────────────────────────────


def tile_and_predict(
    *,
    tenant_id: str,
    image_bytes: bytes,
    classifier: "CropClassifier",
    rows: int = 4,
    cols: int = 4,
    top_k: int | None = None,
) -> TiledInferenceResult:
    """Chop `image_bytes` into rows × cols, predict on each, aggregate.

    Raises:
        ValueError: bad grid dims, tiny source image, or undecodable bytes.
    """
    _validate_grid(rows=rows, cols=cols)

    from PIL import Image  # local — keeps module importable without Pillow

    try:
        with Image.open(io.BytesIO(image_bytes)) as raw:
            source = raw.convert("RGB")
            source.load()
    except Exception as exc:
        raise ValueError(f"Could not decode source image: {exc}") from exc

    source_w, source_h = source.size
    tile_w = source_w // cols
    tile_h = source_h // rows
    if tile_w < MIN_TILE_PIXELS or tile_h < MIN_TILE_PIXELS:
        raise ValueError(
            f"Source image {source_w}×{source_h} too small for {rows}×{cols} "
            f"grid: per-tile size {tile_w}×{tile_h} below "
            f"MIN_TILE_PIXELS={MIN_TILE_PIXELS}. Use a larger image or "
            "smaller grid."
        )

    import time
    from models.crop_classifier import CropPredictionInput

    image_sha = hashlib.sha256(image_bytes).hexdigest()
    started = time.monotonic()
    tile_results: list[TileResult] = []

    for row in range(rows):
        for col in range(cols):
            x = col * tile_w
            y = row * tile_h
            crop = source.crop((x, y, x + tile_w, y + tile_h))
            tile_bytes = _encode_png(crop)
            tile_sha = hashlib.sha256(tile_bytes).hexdigest()
            tile_input = CropPredictionInput(
                image_bytes=tile_bytes,
                image_sha256=tile_sha,
                image_source="inline",
            )
            prediction, topk_entries = classifier.predict(
                tenant_id=tenant_id, image=tile_input, top_k=top_k,
            )
            tile_results.append(
                TileResult(
                    row=row, col=col,
                    bbox_x=x, bbox_y=y, bbox_w=tile_w, bbox_h=tile_h,
                    predicted_class=prediction.features["predicted_class"],
                    prediction=prediction.prediction,
                    confidence=prediction.confidence,
                    confidence_band=prediction.confidence_band,
                    top_k=tuple(topk_entries),
                ),
            )

    hottest = max(tile_results, key=lambda t: t.prediction)
    elapsed_ms = int((time.monotonic() - started) * 1000)

    return TiledInferenceResult(
        tenant_id=tenant_id,
        rows=rows, cols=cols,
        source_width=source_w, source_height=source_h,
        tile_width=tile_w, tile_height=tile_h,
        tiles=tuple(tile_results),
        hottest_tile=hottest,
        aggregate_prediction=hottest.prediction,
        aggregate_class=hottest.predicted_class,
        model_name="crop_classifier",
        model_version=classifier.version,
        total_inference_time_ms=elapsed_ms,
        image_sha256=image_sha,
    )


# ─── Helpers ──────────────────────────────────────────────────────────────


def _validate_grid(*, rows: int, cols: int) -> None:
    if not MIN_GRID_DIM <= rows <= MAX_GRID_DIM:
        raise ValueError(
            f"rows must be {MIN_GRID_DIM}..{MAX_GRID_DIM} (got {rows})"
        )
    if not MIN_GRID_DIM <= cols <= MAX_GRID_DIM:
        raise ValueError(
            f"cols must be {MIN_GRID_DIM}..{MAX_GRID_DIM} (got {cols})"
        )


def _encode_png(image) -> bytes:
    """Encode a PIL.Image to PNG bytes for re-hashing per tile."""
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=False)
    return buf.getvalue()
