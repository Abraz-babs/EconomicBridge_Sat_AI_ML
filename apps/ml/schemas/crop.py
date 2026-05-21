"""Request + response schemas for POST /api/v1/predict/crop_disease."""
from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


# Hard cap on inline (base64) payloads — 8 MiB of raw image. JPEG/WebP
# at this size is plenty for ResNet-50's 224×224 input; anything bigger
# is probably a malformed request, not a real field photo.
MAX_INLINE_IMAGE_BYTES: int = 8 * 1024 * 1024


ConfidenceBand = Literal["HIGH", "MEDIUM", "LOW"]


class CropPredictionRequest(BaseModel):
    """Body of POST /api/v1/predict/crop_disease.

    Caller supplies the image one of two ways:
      * `image_base64` — raw bytes inline (small field photos, dashboard
        upload). Capped at MAX_INLINE_IMAGE_BYTES post-decode.
      * `image_s3_bucket` + `image_s3_key` — bucket-relative key into the
        tenant-prefixed imagery archive (Slice 3a). The router fetches
        the bytes server-side so the client never round-trips the image.

    Exactly one of the two must be supplied.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=50)

    image_base64: str | None = Field(
        default=None,
        description=(
            "Raw image bytes, base64-encoded. Used for inline submissions. "
            "Mutually exclusive with image_s3_key."
        ),
    )
    image_s3_bucket: str | None = Field(
        default=None, max_length=120,
        description="S3 bucket holding the image. Required with image_s3_key.",
    )
    image_s3_key: str | None = Field(
        default=None, max_length=500,
        description=(
            "S3 key. Must start with `<tenant_id>/` (CLAUDE.md §4.2). "
            "Mutually exclusive with image_base64."
        ),
    )

    # Optional spatial / field context — persisted if supplied.
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    lga: str | None = Field(default=None, max_length=120)
    zone_name: str | None = Field(default=None, max_length=200)

    # How many top classes to return. Default comes from settings.crop_top_k_classes.
    top_k: Annotated[int, Field(ge=1, le=12)] = 3

    # Opt-in Grad-CAM saliency overlay (Slice 5d). Adds ~150ms of compute
    # for the backward pass + PNG encode, so callers must request it.
    compute_saliency: bool = False

    # Caller controls persistence (dry-run for model evaluation).
    persist: bool = True

    @model_validator(mode="after")
    def _exactly_one_image_source(self) -> "CropPredictionRequest":
        has_inline = self.image_base64 is not None
        has_s3 = self.image_s3_key is not None
        if has_inline == has_s3:
            raise ValueError(
                "Exactly one of {image_base64, image_s3_key} must be supplied."
            )
        if has_s3 and not self.image_s3_bucket:
            raise ValueError(
                "image_s3_bucket is required when image_s3_key is supplied."
            )
        if has_s3 and not self.image_s3_key.startswith(f"{self.tenant_id}/"):
            raise ValueError(
                f"image_s3_key must be prefixed with the tenant id "
                f"({self.tenant_id!r}). Refusing cross-tenant read."
            )
        if has_inline:
            try:
                # Validate it actually decodes — but don't keep the bytes
                # around; the router will redo this and use the result.
                raw = base64.b64decode(self.image_base64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError(
                    f"image_base64 is not valid base64: {exc}"
                ) from exc
            if len(raw) > MAX_INLINE_IMAGE_BYTES:
                raise ValueError(
                    f"Inline image too large: {len(raw)} bytes > "
                    f"{MAX_INLINE_IMAGE_BYTES} bytes."
                )
            if len(raw) == 0:
                raise ValueError("image_base64 decodes to zero bytes.")
        return self


class CropTopKEntryResponse(BaseModel):
    class_name: str
    probability: float


class CropPredictionData(BaseModel):
    """Body of the SuccessResponse[T] returned by predict_crop_disease()."""

    prediction_id: UUID | None
    model_name: str
    model_version: str
    tenant_id: str

    # Inference output
    predicted_class: str
    prediction: float          # 0..1, higher = more concerning
    confidence: float          # top-1 probability
    confidence_band: str       # HIGH | MEDIUM | LOW
    requires_human_review: bool
    top_k: list[CropTopKEntryResponse]

    # Input provenance
    image_source: Literal["s3", "inline"]
    image_s3_bucket: str | None
    image_s3_key: str | None
    image_sha256: str

    # Grad-CAM saliency overlay (base64 PNG, 224×224). None unless the
    # request set compute_saliency=True AND the classifier is in a
    # torch-enabled mode (stub mode always returns None).
    saliency_b64: str | None = None

    input_hash: str
    inference_time_ms: int
    timestamp: datetime
    persisted: bool


# ─── Tiled mode (Slice 5e-a) ──────────────────────────────────────────────


class CropTiledPredictionRequest(BaseModel):
    """Body of POST /api/v1/predict/crop_disease/tiled.

    Chops `image_base64` into a `rows × cols` grid and predicts on each
    tile. Returns one row per tile plus the headline "hottest" tile.
    Useful for wide field photos and (later) Sentinel-2 chips.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=50)
    image_base64: str = Field(min_length=1)
    rows: Annotated[int, Field(ge=1, le=8)] = 4
    cols: Annotated[int, Field(ge=1, le=8)] = 4
    top_k: Annotated[int, Field(ge=1, le=12)] = 3

    # Optional spatial / field context — same fields as the single-leaf
    # request so the persistence path can write them through.
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    lga: str | None = Field(default=None, max_length=120)
    zone_name: str | None = Field(default=None, max_length=200)

    persist: bool = True

    @model_validator(mode="after")
    def _decode_image(self) -> "CropTiledPredictionRequest":
        try:
            raw = base64.b64decode(self.image_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(
                f"image_base64 is not valid base64: {exc}"
            ) from exc
        if len(raw) == 0:
            raise ValueError("image_base64 decodes to zero bytes.")
        if len(raw) > MAX_INLINE_IMAGE_BYTES:
            raise ValueError(
                f"Image too large: {len(raw)} bytes > "
                f"{MAX_INLINE_IMAGE_BYTES} bytes."
            )
        return self


class TileResultResponse(BaseModel):
    row: int
    col: int
    bbox_x: int
    bbox_y: int
    bbox_w: int
    bbox_h: int
    predicted_class: str
    prediction: float
    confidence: float
    confidence_band: ConfidenceBand
    top_k: list[CropTopKEntryResponse]


class CropTiledPredictionData(BaseModel):
    """Body of the SuccessResponse[T] returned by predict_crop_disease_tiled."""

    prediction_id: UUID | None
    model_name: str
    model_version: str
    tenant_id: str

    rows: int
    cols: int
    source_width: int
    source_height: int
    tile_width: int
    tile_height: int

    # Aggregate (= hottest tile).
    aggregate_class: str
    aggregate_prediction: float
    hottest_tile: TileResultResponse

    tiles: list[TileResultResponse]

    image_sha256: str
    total_inference_time_ms: int
    timestamp: datetime
    persisted: bool
