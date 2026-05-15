"""Random Forest conflict predictor + SHAP explainer.

Mirrors the proven Citadel Kebbi pattern (CLAUDE.md §2). Inputs are spatial
+ recent-history features extracted upstream from the satellite + alert
pipelines; the model outputs a 24–72hr conflict probability.

Features (the order matters — used for both training and inference)
  heat_signature_intensity   0..1   normalised peak brightness over ROI
  boundary_distance_km        0..50  closest detected heat → farmland boundary
  ndvi_delta                 -1..1  recent NDVI deviation from seasonal mean
  herder_density              0..1   estimated herder-group density in ROI
  historical_incidents        0..50  incidents within 30km / 365 days
  rainfall_anomaly           -1..1  recent rainfall vs seasonal mean
  is_new_geography             {0,1} 1 if no prior data for the ROI

The trained model is persisted to apps/ml/artifacts/conflict_predictor.joblib
and lazy-loaded on first predict() call. On disk-miss, the predictor trains a
fresh model from synthetic-but-plausible data — this lets the pipeline run
end-to-end in dev without Citadel's real training set. In production the
artifact ships with the Docker image (built from real historical data).
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
from sklearn.ensemble import RandomForestClassifier

from config import get_settings
from models.prediction import (
    ModelPrediction,
    band_for_confidence,
    utcnow,
)

log = logging.getLogger(__name__)

MODEL_NAME = "conflict_predictor"
MODEL_VERSION = "0.1.0-dev-synthetic"

# Feature order is the API contract — change only with a version bump.
FEATURE_NAMES: tuple[str, ...] = (
    "heat_signature_intensity",
    "boundary_distance_km",
    "ndvi_delta",
    "herder_density",
    "historical_incidents",
    "rainfall_anomaly",
    "is_new_geography",
)


@dataclass(frozen=True, slots=True)
class ConflictFeatures:
    """Input features for a single prediction."""

    heat_signature_intensity: float
    boundary_distance_km: float
    ndvi_delta: float
    herder_density: float
    historical_incidents: int
    rainfall_anomaly: float
    is_new_geography: bool

    def to_array(self) -> np.ndarray:
        return np.array(
            [
                self.heat_signature_intensity,
                self.boundary_distance_km,
                self.ndvi_delta,
                self.herder_density,
                self.historical_incidents,
                self.rainfall_anomaly,
                1.0 if self.is_new_geography else 0.0,
            ],
            dtype=np.float64,
        )

    def to_dict(self) -> dict[str, float | int | bool]:
        return {
            "heat_signature_intensity": self.heat_signature_intensity,
            "boundary_distance_km": self.boundary_distance_km,
            "ndvi_delta": self.ndvi_delta,
            "herder_density": self.herder_density,
            "historical_incidents": self.historical_incidents,
            "rainfall_anomaly": self.rainfall_anomaly,
            "is_new_geography": self.is_new_geography,
        }


# ─── Synthetic training data ──────────────────────────────────────────────


def _generate_synthetic_dataset(
    *, n_samples: int = 4096, seed: int = 42
) -> tuple[np.ndarray, np.ndarray]:
    """Produce a labelled training set with realistic signal.

    Not for production use — Citadel's real labelled dataset replaces this when
    the artifact ships in the Docker image. Used in dev so the API has working
    inference without a 500MB model checkpoint in the repo.

    Label is derived from a domain-grounded logit: higher heat + closer to
    boundary + negative NDVI + higher herder density + more historical
    incidents → higher conflict probability.
    """
    rng = np.random.default_rng(seed)

    heat = rng.uniform(0.0, 1.0, n_samples)
    distance = rng.uniform(0.0, 50.0, n_samples)
    ndvi = rng.uniform(-1.0, 1.0, n_samples)
    herder = rng.uniform(0.0, 1.0, n_samples)
    history = rng.integers(0, 50, n_samples)
    rainfall = rng.uniform(-1.0, 1.0, n_samples)
    is_new = rng.integers(0, 2, n_samples)

    logits = (
        3.4 * heat
        - 0.10 * distance
        - 1.8 * ndvi
        + 2.1 * herder
        + 0.06 * history
        - 1.2 * rainfall
        + 0.4 * is_new
        - 1.5
        + rng.normal(0.0, 0.5, n_samples)
    )
    proba = 1.0 / (1.0 + np.exp(-logits))
    y = (rng.uniform(0, 1, n_samples) < proba).astype(int)

    X = np.column_stack([heat, distance, ndvi, herder, history, rainfall, is_new])
    return X, y


def _train_model() -> tuple[RandomForestClassifier, shap.TreeExplainer]:
    X, y = _generate_synthetic_dataset()
    clf = RandomForestClassifier(
        n_estimators=160,
        max_depth=12,
        min_samples_leaf=4,
        random_state=42,
        n_jobs=-1,
    )
    clf.fit(X, y)
    explainer = shap.TreeExplainer(clf)
    return clf, explainer


# ─── Loader ───────────────────────────────────────────────────────────────


class ConflictPredictor:
    """Lazy-loaded RF + SHAP wrapper. One instance per process."""

    def __init__(self) -> None:
        self._model: RandomForestClassifier | None = None
        self._explainer: shap.TreeExplainer | None = None

    def _load_or_train(self) -> None:
        if self._model is not None:
            return

        settings = get_settings()
        artifact_dir = Path(settings.model_dir)
        artifact_path = artifact_dir / "conflict_predictor.joblib"

        if artifact_path.exists():
            log.info("conflict_predictor: loading from %s", artifact_path)
            bundle: dict[str, Any] = joblib.load(artifact_path)
            self._model = bundle["model"]
            self._explainer = bundle["explainer"]
            return

        log.warning(
            "conflict_predictor: no artifact at %s — training a fresh model "
            "from synthetic data (dev-mode only)",
            artifact_path,
        )
        self._model, self._explainer = _train_model()
        artifact_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {"model": self._model, "explainer": self._explainer},
            artifact_path,
            compress=3,
        )
        log.info("conflict_predictor: persisted artifact to %s", artifact_path)

    # ── public API ──────────────────────────────────────────────────────

    def predict(
        self, *, tenant_id: str, features: ConflictFeatures
    ) -> ModelPrediction:
        """Run inference for `tenant_id` over `features`. Returns the contract.

        Raises ValueError on malformed inputs (caught by router and surfaced
        as HTTP 422).
        """
        self._load_or_train()
        assert self._model is not None and self._explainer is not None

        started = time.monotonic()
        x = features.to_array().reshape(1, -1)
        probabilities = self._model.predict_proba(x)[0]
        # class index 1 = "conflict" (binary classifier)
        prediction = float(probabilities[1])
        # Confidence = how decisive the forest was; equals max(class probability)
        confidence = float(max(probabilities))

        # SHAP values for the positive class
        shap_raw = self._explainer.shap_values(x)
        shap_pos = _select_positive_class(shap_raw, num_features=x.shape[1])
        shap_dict = {name: float(v) for name, v in zip(FEATURE_NAMES, shap_pos)}
        base_value = _select_base_value(self._explainer)

        elapsed_ms = int((time.monotonic() - started) * 1000)
        band = band_for_confidence(confidence)
        # CLAUDE.md §9: new geography ALWAYS requires human review,
        # regardless of confidence.
        requires_review = band != "HIGH" or features.is_new_geography

        return ModelPrediction(
            model_name=MODEL_NAME,
            model_version=MODEL_VERSION,
            tenant_id=tenant_id,
            prediction=prediction,
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


# Module-level singleton — initialised lazily on first call.
_PREDICTOR: ConflictPredictor | None = None


def get_predictor() -> ConflictPredictor:
    """Return the process-wide ConflictPredictor (singleton)."""
    global _PREDICTOR
    if _PREDICTOR is None:
        _PREDICTOR = ConflictPredictor()
    return _PREDICTOR


# ─── helpers ──────────────────────────────────────────────────────────────


def hash_features(features: ConflictFeatures) -> str:
    """SHA-256 of the JSON-serialised feature vector (replay-safe input id)."""
    blob = json.dumps(features.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _select_positive_class(shap_raw: Any, *, num_features: int) -> Sequence[float]:
    """Return the SHAP value row for class=1.

    `shap.TreeExplainer.shap_values()` on a binary classifier may return a
    list of two arrays (one per class), or a 3-D array of shape
    (n_samples, n_features, n_classes), depending on shap version. Handle both.
    """
    # 3-D array path (newer SHAP)
    if isinstance(shap_raw, np.ndarray) and shap_raw.ndim == 3:
        return shap_raw[0, :, 1].tolist()
    # list-of-arrays path (older SHAP)
    if isinstance(shap_raw, list) and len(shap_raw) == 2:
        return shap_raw[1][0].tolist()
    # single-array path (regressor or single-class)
    if isinstance(shap_raw, np.ndarray) and shap_raw.ndim == 2:
        return shap_raw[0].tolist()
    raise RuntimeError(
        f"Unexpected SHAP return shape: type={type(shap_raw).__name__} "
        f"shape={getattr(shap_raw, 'shape', None)}"
    )


def _select_base_value(explainer: shap.TreeExplainer) -> float | None:
    bv = getattr(explainer, "expected_value", None)
    if bv is None:
        return None
    if isinstance(bv, (list, np.ndarray)):
        if len(bv) >= 2:
            return float(bv[1])
        return float(bv[0])
    return float(bv)
