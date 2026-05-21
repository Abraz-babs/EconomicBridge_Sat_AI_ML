"""Synthetic training-data generator + per-crop reference tables.

Lives separate from yield_predictor.py so the predictor module stays
under the CLAUDE.md §4.3 300-line cap and so callers can unit-test
the synthesis logic without instantiating the full predictor.

Real production training will replace `_generate_synthetic_dataset`
with a loader for NBS Agricultural Performance Survey + FAOSTAT
crop-yield CSVs. The reference + baseline tables stay correct in
either mode — they're the normalisation constants the inference layer
applies to map raw yield (tons/ha) to the canonical [0..1] score.
"""
from __future__ import annotations

import numpy as np
import shap
from sklearn.ensemble import RandomForestRegressor

from schemas.yield_predictor import SUPPORTED_CROPS


# Reference max yields per crop in tons/hectare (FAOSTAT/NBS APS upper
# bound under good management). The 0..1 `prediction` score is the
# normalized fraction of this max.
CROP_REFERENCE_MAX_T_HA: dict[str, float] = {
    "maize":        6.0,
    "rice":         5.5,
    "cassava":      14.0,
    "yam":          10.0,
    "sorghum":      4.0,
    "millet":       3.0,
    "cowpea":       2.0,
    "groundnut":    2.5,
    "soybean":      3.5,
    "tomato":       8.0,
    "pepper":       4.0,
    "onion":        7.0,
    "plantain":     10.0,
    "sweet_potato": 8.0,
}

# Per-crop "well-tended" baseline yield used to weight synthetic data
# generation. Tuned to FAOSTAT 2020-2023 sub-Saharan smallholder mean.
CROP_BASELINE_T_HA: dict[str, float] = {
    "maize":        2.0,
    "rice":         2.2,
    "cassava":      9.0,
    "yam":          6.0,
    "sorghum":      1.2,
    "millet":       0.9,
    "cowpea":       0.8,
    "groundnut":    1.0,
    "soybean":      1.4,
    "tomato":       3.5,
    "pepper":       1.6,
    "onion":        3.2,
    "plantain":     6.5,
    "sweet_potato": 4.0,
}


def generate_synthetic_dataset(
    *, n_samples: int = 4096, seed: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """Domain-grounded synthetic training set.

    Yield = crop_baseline × site_modifier × stress_factor + noise.
    Site modifier scales with NDVI + soil + historical performance;
    stress factor penalises drought/excess + days_to_harvest risk.
    """
    rng = np.random.default_rng(seed)
    crops = rng.integers(0, len(SUPPORTED_CROPS), n_samples)
    baselines = np.array(
        [CROP_BASELINE_T_HA[SUPPORTED_CROPS[c]] for c in crops]
    )
    ndvi = rng.uniform(0.0, 1.0, n_samples)
    ndvi_anom = rng.uniform(-1.0, 1.0, n_samples)
    rain = rng.uniform(0.0, 2000.0, n_samples)
    rain_anom = rng.uniform(-1.0, 1.0, n_samples)
    soil = rng.uniform(0.0, 1.0, n_samples)
    history = rng.uniform(0.5, 8.0, n_samples)
    dth = rng.integers(0, 200, n_samples)

    site_mod = 0.4 + 1.4 * ndvi + 0.5 * soil + 0.18 * (history / 8.0)
    stress = (
        1.0
        + 0.30 * ndvi_anom
        + 0.20 * rain_anom
        - 0.18 * np.maximum(0, -rain_anom)   # drought bites harder
        - 0.10 * (dth / 200.0)
    )
    yield_t_ha = baselines * site_mod * stress
    yield_t_ha = np.clip(yield_t_ha, 0.0, None)
    yield_t_ha += rng.normal(0.0, 0.10 * yield_t_ha, n_samples)
    yield_t_ha = np.clip(yield_t_ha, 0.0, None)

    X = np.column_stack(
        [ndvi, ndvi_anom, rain, rain_anom, soil, history, dth, crops]
    )
    return X, yield_t_ha


def train_synthetic_model() -> tuple[RandomForestRegressor, shap.TreeExplainer]:
    """Fit a fresh RF + SHAP explainer on the synthetic dataset.

    Called from YieldPredictor._load_or_train when no real artifact
    is on disk. Deterministic via the seed in generate_synthetic_dataset.
    """
    X, y = generate_synthetic_dataset()
    reg = RandomForestRegressor(
        n_estimators=160,
        max_depth=14,
        min_samples_leaf=4,
        random_state=42,
        n_jobs=-1,
    )
    reg.fit(X, y)
    explainer = shap.TreeExplainer(reg)
    return reg, explainer
