"""ModelPrediction dataclass — the contract every ML inference must produce.

Mirrors CLAUDE.md §9. Every model serving endpoint returns one of these so
downstream systems (audit log, alerts pipeline, dashboards) can treat all
models uniformly.

`confidence_band` is a derived field — services should call
`band_for_confidence(confidence)` to pick the right level so the routing
thresholds live in exactly one place.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

ConfidenceBand = Literal["HIGH", "MEDIUM", "LOW"]

# CLAUDE.md §9 thresholds — single source of truth.
HIGH_THRESHOLD = 0.90
MEDIUM_THRESHOLD = 0.75


def band_for_confidence(confidence: float) -> ConfidenceBand:
    """Map raw confidence to the operational band (CLAUDE.md §9)."""
    if confidence >= HIGH_THRESHOLD:
        return "HIGH"
    if confidence >= MEDIUM_THRESHOLD:
        return "MEDIUM"
    return "LOW"


@dataclass(slots=True)
class ModelPrediction:
    """One inference, with everything we need to audit it later."""

    model_name: str
    model_version: str
    tenant_id: str
    prediction: float
    confidence: float
    shap_values: dict[str, float]
    input_hash: str
    inference_time_ms: int
    timestamp: datetime
    requires_human_review: bool
    confidence_band: ConfidenceBand
    features: dict[str, Any] = field(default_factory=dict)
    shap_base_value: float | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.prediction <= 1.0:
            raise ValueError(f"prediction out of [0, 1]: {self.prediction}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence out of [0, 1]: {self.confidence}")
        # Band must match the confidence — services may set this explicitly,
        # but if it disagrees with the value something is wrong.
        derived = band_for_confidence(self.confidence)
        if self.confidence_band != derived:
            raise ValueError(
                f"confidence_band {self.confidence_band!r} does not match "
                f"confidence={self.confidence!r} (expected {derived!r})"
            )


def utcnow() -> datetime:
    """Single helper so all timestamps are timezone-aware UTC."""
    return datetime.now(timezone.utc)
