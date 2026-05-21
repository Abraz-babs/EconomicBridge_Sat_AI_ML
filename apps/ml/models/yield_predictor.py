"""Random Forest yield predictor + SHAP explainer (Slice 04.c).

Predicts expected harvest yield in tons/hectare for one (crop, region,
field-state) tuple. Lazy-load + synthetic-on-miss mirrors the
conflict_predictor pattern so the API runs end-to-end without a real
NBS / FAOSTAT artifact.

Features (order pinned in FEATURE_NAMES):
  ndvi_mean_30d, ndvi_anomaly, rainfall_30d_mm, rainfall_anomaly,
  soil_quality_index, historical_yield_mean_t_ha, days_to_harvest, crop_id

Output:
  raw yield (tons/ha) + 80% PI from per-tree variance + canonical
  ModelPrediction (CLAUDE.md §9) whose `prediction` field is the
  normalized yield / CROP_REFERENCE_MAX_T_HA[crop].

Synthetic training set + reference constants live in yield_training.py.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import joblib
import numpy as np
import shap
from sklearn.ensemble import RandomForestRegressor

from config import get_settings
from models.prediction import (
    ModelPrediction,
    band_for_confidence,
    utcnow,
)
from models.yield_training import (
    CROP_REFERENCE_MAX_T_HA,
    train_synthetic_model,
)
from schemas.yield_predictor import SUPPORTED_CROPS

log = logging.getLogger(__name__)

MODEL_NAME = "yield_predictor"
MODEL_VERSION = "0.1.0-dev-synthetic"

FEATURE_NAMES: tuple[str, ...] = (
    "ndvi_mean_30d",
    "ndvi_anomaly",
    "rainfall_30d_mm",
    "rainfall_anomaly",
    "soil_quality_index",
    "historical_yield_mean_t_ha",
    "days_to_harvest",
    "crop_id",
)


@dataclass(frozen=True, slots=True)
class YieldFeatures:
    """Input features for one prediction."""

    crop: str
    ndvi_mean_30d: float
    ndvi_anomaly: float
    rainfall_30d_mm: float
    rainfall_anomaly: float
    soil_quality_index: float
    historical_yield_mean_t_ha: float
    days_to_harvest: int

    def crop_id(self) -> int:
        try:
            return SUPPORTED_CROPS.index(self.crop)
        except ValueError as exc:
            raise ValueError(
                f"Unsupported crop {self.crop!r} (must be one of "
                f"{list(SUPPORTED_CROPS)})"
            ) from exc

    def to_array(self) -> np.ndarray:
        return np.array(
            [
                self.ndvi_mean_30d,
                self.ndvi_anomaly,
                self.rainfall_30d_mm,
                self.rainfall_anomaly,
                self.soil_quality_index,
                self.historical_yield_mean_t_ha,
                float(self.days_to_harvest),
                float(self.crop_id()),
            ],
            dtype=np.float64,
        )

    def to_dict(self) -> dict[str, float | int | str]:
        return {
            "crop": self.crop,
            "ndvi_mean_30d": self.ndvi_mean_30d,
            "ndvi_anomaly": self.ndvi_anomaly,
            "rainfall_30d_mm": self.rainfall_30d_mm,
            "rainfall_anomaly": self.rainfall_anomaly,
            "soil_quality_index": self.soil_quality_index,
            "historical_yield_mean_t_ha": self.historical_yield_mean_t_ha,
            "days_to_harvest": self.days_to_harvest,
        }


class YieldPredictor:
    """Lazy-loaded RF regressor + SHAP wrapper. One instance per process."""

    def __init__(self) -> None:
        self._model: RandomForestRegressor | None = None
        self._explainer: shap.TreeExplainer | None = None

    def _load_or_train(self) -> None:
        if self._model is not None:
            return

        settings = get_settings()
        artifact_dir = Path(settings.model_dir)
        artifact_path = artifact_dir / "yield_predictor.joblib"

        if artifact_path.exists():
            log.info("yield_predictor: loading from %s", artifact_path)
            bundle: dict[str, Any] = joblib.load(artifact_path)
            self._model = bundle["model"]
            self._explainer = bundle["explainer"]
            return

        log.warning(
            "yield_predictor: no artifact at %s — training fresh on "
            "synthetic data (dev-mode only)", artifact_path,
        )
        self._model, self._explainer = train_synthetic_model()
        artifact_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {"model": self._model, "explainer": self._explainer},
            artifact_path, compress=3,
        )

    def predict(
        self, *, tenant_id: str, features: YieldFeatures,
    ) -> tuple[ModelPrediction, float, float | None, float | None]:
        """Run inference. Returns (prediction, yield_t_ha, pi_low, pi_high).

        ModelPrediction carries the normalized [0..1] score; raw yield
        and 80% prediction interval ride alongside so the router can
        persist all three.
        """
        self._load_or_train()
        assert self._model is not None and self._explainer is not None

        started = time.monotonic()
        x = features.to_array().reshape(1, -1)

        # Per-tree predictions → variance for a prediction interval.
        tree_outputs = np.array([
            tree.predict(x)[0] for tree in self._model.estimators_
        ])
        yield_t_ha = float(np.clip(tree_outputs.mean(), 0.0, None))
        sigma = float(tree_outputs.std())
        pi_low = max(0.0, yield_t_ha - 1.28 * sigma)   # 80% one-sided
        pi_high = yield_t_ha + 1.28 * sigma

        # Narrow PI relative to reference max → high confidence.
        ref_max = CROP_REFERENCE_MAX_T_HA[features.crop]
        relative_width = min(1.0, (pi_high - pi_low) / max(ref_max, 1e-6))
        confidence = float(np.clip(1.0 - relative_width, 0.0, 1.0))
        prediction_score = float(np.clip(yield_t_ha / ref_max, 0.0, 1.0))

        # SHAP for regressors: 2-D array (n_samples × n_features)
        shap_raw = self._explainer.shap_values(x)
        shap_row = _select_shap_row(shap_raw)
        shap_dict = {
            name: float(v) for name, v in zip(FEATURE_NAMES, shap_row)
        }
        base_value = _select_base_value(self._explainer)

        band = band_for_confidence(confidence)
        # CLAUDE.md §9: new geography (no history) ALWAYS requires review.
        new_geography = features.historical_yield_mean_t_ha <= 0.01
        requires_review = band != "HIGH" or new_geography

        elapsed_ms = int((time.monotonic() - started) * 1000)
        prediction = ModelPrediction(
            model_name=MODEL_NAME,
            model_version=MODEL_VERSION,
            tenant_id=tenant_id,
            prediction=prediction_score,
            confidence=confidence,
            shap_values=shap_dict,
            shap_base_value=base_value,
            input_hash=hash_features(features),
            inference_time_ms=elapsed_ms,
            timestamp=utcnow(),
            requires_human_review=requires_review,
            confidence_band=band,
            features=features.to_dict(),
        )
        return prediction, yield_t_ha, pi_low, pi_high


_PREDICTOR: YieldPredictor | None = None


def get_predictor() -> YieldPredictor:
    global _PREDICTOR
    if _PREDICTOR is None:
        _PREDICTOR = YieldPredictor()
    return _PREDICTOR


def hash_features(features: YieldFeatures) -> str:
    blob = json.dumps(features.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _select_shap_row(shap_raw: Any) -> Sequence[float]:
    if isinstance(shap_raw, np.ndarray) and shap_raw.ndim == 2:
        return shap_raw[0].tolist()
    if isinstance(shap_raw, list) and len(shap_raw) > 0:
        first = shap_raw[0]
        if isinstance(first, np.ndarray):
            return first[0].tolist() if first.ndim == 2 else first.tolist()
    raise RuntimeError(
        f"Unexpected SHAP return shape: type={type(shap_raw).__name__} "
        f"shape={getattr(shap_raw, 'shape', None)}"
    )


def _select_base_value(explainer: shap.TreeExplainer) -> float | None:
    bv = getattr(explainer, "expected_value", None)
    if bv is None:
        return None
    if isinstance(bv, (list, np.ndarray)):
        return float(bv[0])
    return float(bv)
