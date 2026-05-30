"""Retrain the conflict predictor on REAL ACLED incidents (offline, CPU).

Replaces the synthetic-data artifact (MODEL_VERSION 0.1.0-dev-synthetic) with
one trained on real Nigerian conflict incidents from ACLED. Random Forest, so
this runs on CPU in minutes — no GPU needed (unlike the crop/flood models).

What's ready vs the remaining integration:
  * REAL + ready: ACLED labels (positives = real incidents; see acled_client),
    historical_incidents (prior-incident density), is_new_geography, and the
    severity signal from fatalities.
  * NEEDS A FEATURE PROVIDER: the satellite features at each incident's
    (lat, lon, date) — heat_signature_intensity, ndvi_delta, herder_density,
    rainfall_anomaly, boundary_distance_km — must be read from a TIME-MATCHED
    historical signal store. Pass a `feature_provider(lat, lon, date) -> dict`
    callable (e.g. backed by tenant heat_signatures + a herder/boundary layer).
    Without one, the real run refuses to fabricate those features.

Run:
    # smoke test the train→artifact path (synthetic feature provider):
    python -m scripts.train_conflict_real --smoke
    # real run (needs ACLED_API_KEY + ACLED_EMAIL + a feature provider wired):
    python -m scripts.train_conflict_real --country Nigeria --start 2018-01-01

Output: apps/ml/artifacts/conflict_predictor.joblib (model + SHAP explainer),
MODEL_VERSION stamped with the ACLED provenance. The ml service loads it
exactly as it loads the synthetic artifact today.
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

import numpy as np

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from scripts.acled_client import AcledClient, AcledEvent  # noqa: E402

log = logging.getLogger(__name__)

REAL_MODEL_VERSION = "0.2.0-acled"
FEATURE_ORDER = [
    "heat_signature_intensity", "boundary_distance_km", "ndvi_delta",
    "herder_density", "historical_incidents", "rainfall_anomaly", "is_new_geography",
]

# (lat, lon, iso_date) → {feature_name: value}. Operator wires this to the
# historical signal store; None means "not available" and the real path stops.
FeatureProvider = Callable[[float, float, str], dict[str, float]]


def _historical_density(ev: AcledEvent, events: list[AcledEvent], radius_deg: float = 0.25) -> int:
    """Prior incidents within radius — a real, ACLED-derivable feature."""
    n = 0
    for o in events:
        if o.event_date < ev.event_date and abs(o.latitude - ev.latitude) <= radius_deg \
           and abs(o.longitude - ev.longitude) <= radius_deg:
            n += 1
    return min(n, 50)


def build_dataset(
    events: list[AcledEvent], feature_provider: FeatureProvider,
    *, seed: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """Build (X, y): real ACLED incidents = positives, sampled background =
    negatives, features from the provider + ACLED-derived history."""
    rng = np.random.default_rng(seed)
    rows: list[list[float]] = []
    labels: list[int] = []

    def feat_row(lat: float, lon: float, d: str, is_pos: int) -> None:
        f = feature_provider(lat, lon, d)
        rows.append([
            f["heat_signature_intensity"], f["boundary_distance_km"], f["ndvi_delta"],
            f["herder_density"], float(f.get("historical_incidents", 0)),
            f["rainfall_anomaly"], f.get("is_new_geography", 0.0),
        ])
        labels.append(is_pos)

    for ev in events:
        f = feature_provider(ev.latitude, ev.longitude, ev.event_date)
        f.setdefault("historical_incidents", _historical_density(ev, events))
        rows.append([f[k] if k != "is_new_geography" else f.get(k, 0.0) for k in FEATURE_ORDER])
        labels.append(1)
        # one background negative jittered away from the incident
        feat_row(ev.latitude + rng.uniform(-1.5, 1.5),
                 ev.longitude + rng.uniform(-1.5, 1.5), ev.event_date, 0)

    return np.asarray(rows, dtype=np.float64), np.asarray(labels, dtype=int)


def train_and_save(X: np.ndarray, y: np.ndarray, output: Path) -> Path:
    """Train the RF + SHAP explainer and persist the joblib bundle."""
    import joblib
    import shap
    from sklearn.ensemble import RandomForestClassifier

    clf = RandomForestClassifier(
        n_estimators=160, max_depth=12, min_samples_leaf=4, random_state=42, n_jobs=-1,
    )
    clf.fit(X, y)
    explainer = shap.TreeExplainer(clf)
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"model": clf, "explainer": explainer, "model_version": REAL_MODEL_VERSION,
         "feature_order": FEATURE_ORDER},
        output,
    )
    log.info("saved conflict artifact (%s, n=%d) → %s", REAL_MODEL_VERSION, len(y), output)
    return output


def _synthetic_provider(lat: float, lon: float, d: str) -> dict[str, float]:
    """Smoke-test provider: plausible values so the harness runs without the
    real historical signal store. NOT for production — use a real provider."""
    rng = np.random.default_rng(abs(hash((round(lat, 2), round(lon, 2), d))) % (2**32))
    return {
        "heat_signature_intensity": float(rng.uniform(0, 1)),
        "boundary_distance_km": float(rng.uniform(0, 50)),
        "ndvi_delta": float(rng.uniform(-1, 1)),
        "herder_density": float(rng.uniform(0, 1)),
        "rainfall_anomaly": float(rng.uniform(-1, 1)),
        "is_new_geography": 0.0,
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--country", default="Nigeria")
    p.add_argument("--start", default="2018-01-01")
    p.add_argument("--end", default=date.today().isoformat())
    p.add_argument("--output", type=Path, default=ML_ROOT / "artifacts" / "conflict_predictor.joblib")
    p.add_argument("--smoke", action="store_true",
                   help="Use a synthetic feature provider + tiny ACLED stand-in to test the pipeline.")
    args = p.parse_args(argv)

    if args.smoke:
        log.info("SMOKE: synthetic feature provider + fabricated incidents")
        rng = np.random.default_rng(0)
        events = [
            AcledEvent("2024-01-01", float(9 + rng.uniform(-2, 2)), float(8 + rng.uniform(-2, 2)),
                       "Violence against civilians", "Attack", int(rng.integers(0, 10)), "X", "Y")
            for _ in range(200)
        ]
        provider: FeatureProvider = _synthetic_provider
    else:
        client = AcledClient()
        events = client.fetch_events(country=args.country, start=args.start, end=args.end)
        log.info("fetched %d ACLED incidents for %s", len(events), args.country)
        raise SystemExit(
            "Real run needs a feature_provider wired to your historical signal "
            "store (heat_signatures / NDVI / herder / boundary at incident time). "
            "See module docstring. ACLED fetch succeeded; wire the provider to proceed."
        )

    X, y = build_dataset(events, provider)
    train_and_save(X, y, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
