"""Pre-symptomatic disease detection via NDVI anomaly (Slice 04.d).

The 14-day early-warning claim works like this:

  1. Pull NDVI history for the tenant ROI — last 90 days at daily
     resolution. (Synthetic-per-tenant for now; real Sentinel-2
     B4/B8 → NDVI ingestion lands in a follow-up slice.)
  2. Split into:
       - `recent` window: the last RECENT_WINDOW_DAYS (default 14)
       - `baseline` window: the BASELINE_WINDOW_DAYS preceding that
  3. LINEAR-DETREND the baseline — NDVI has a strong seasonal
     trajectory and `std(raw_baseline)` would otherwise be dominated
     by the seasonal slope, not by short-term noise. Fitting a line
     and taking std of residuals isolates the noise floor.
  4. Project the baseline trend forward to the centre of the recent
     window — that's the "expected" NDVI under no disease. Compare
     actual recent mean against expected:
       z = (mean_recent - expected) / std_baseline_residuals
     A NEGATIVE z means vegetation is dimmer than the seasonal
     trajectory would predict → stress.
  5. If z ≤ -ANOMALY_Z_THRESHOLD, flag an anomaly.
  6. Project disease probability from |z| via a shifted sigmoid:
     at threshold p≈0.5; further out → 1.0.
  7. Confidence band from |z|: HIGH ≥ 2.5σ, MEDIUM ≥ 1.5σ, LOW under.

Pure Python — sample size is ~90 daily points; numpy overkill.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone


DETECTOR_NAME = "ndvi_anomaly_v1"
DETECTOR_VERSION = "0.1.0-statistical"

# Window math (CLAUDE.md §4.3 — extract magic numbers).
SERIES_LENGTH_DAYS: int = 90
RECENT_WINDOW_DAYS: int = 14
BASELINE_WINDOW_DAYS: int = 60
# z below this triggers an anomaly (negative = dimmer than baseline).
ANOMALY_Z_THRESHOLD: float = 1.5

# Per-tenant seasonal NDVI mean + amplitude (annual cycle). These are
# rough sub-Saharan agroclimatic priors — savanna belt tenants peak
# Aug/Sep, southern tenants peak Jun/Jul, Senegal coastal peaks Sep.
TENANT_SEASONAL_PROFILE: dict[str, tuple[float, float, int]] = {
    # tenant_id: (mean, amplitude, peak_day_of_year)
    "kebbi":    (0.45, 0.25, 240),   # late Aug
    "benue":    (0.55, 0.20, 220),   # early Aug
    "plateau":  (0.50, 0.22, 230),
    "kaduna":   (0.48, 0.23, 230),
    "niger":    (0.46, 0.24, 235),
    "zamfara":  (0.43, 0.26, 245),
    "nasarawa": (0.52, 0.21, 225),
    "fct":      (0.50, 0.22, 225),
    "ghana":    (0.58, 0.18, 210),   # earlier wet season
    "senegal":  (0.52, 0.20, 255),   # later wet season
}


@dataclass(frozen=True, slots=True)
class NdviSample:
    observed_at: date
    ndvi: float


@dataclass(frozen=True, slots=True)
class AnomalyResult:
    """One detection outcome — what the router persists + returns."""

    tenant_id: str
    detector_name: str
    detector_version: str
    window_start: date
    window_end: date
    ndvi_recent_mean: float
    ndvi_baseline_mean: float
    ndvi_baseline_std: float
    z_score: float
    disease_probability: float
    anomaly: bool
    confidence_band: str
    series: tuple[NdviSample, ...]
    crop: str | None
    # Days remaining in the early-warning window — how many days the
    # algorithm's "14 days before symptoms" lead-time we still have.
    days_early_warning: int


def synthetic_series(
    tenant_id: str,
    *,
    end: date | None = None,
    inject_anomaly: bool = False,
) -> tuple[NdviSample, ...]:
    """Generate a deterministic 90-day NDVI series for one tenant.

    Annual sinusoid centred on the tenant's seasonal mean + per-day
    md5-mixed noise (~2% of mean) so the series is reproducible per
    tenant + day. `inject_anomaly` synthetically drops the last 14
    days by 25% to simulate a vegetation stress event — used by the
    seed scan to produce a non-trivial dashboard rendering.
    """
    profile = TENANT_SEASONAL_PROFILE.get(tenant_id, (0.50, 0.20, 220))
    mean, amplitude, peak_doy = profile

    if end is None:
        end = date.today()
    samples: list[NdviSample] = []
    for offset in range(SERIES_LENGTH_DAYS - 1, -1, -1):
        d = end - timedelta(days=offset)
        # Annual sinusoid
        doy = d.timetuple().tm_yday
        seasonal = mean + amplitude * math.cos(
            2 * math.pi * (doy - peak_doy) / 365.0
        )
        # Deterministic noise from (tenant, day) hash.
        noise_byte = int.from_bytes(
            hashlib.md5(
                f"{tenant_id}|{d.isoformat()}".encode(),
                usedforsecurity=False,
            ).digest()[:2],
            "big",
        )
        noise = ((noise_byte / 65535.0) - 0.5) * 0.04
        ndvi = max(0.0, min(1.0, seasonal + noise))
        # Inject anomaly into the recent window for demo realism.
        if inject_anomaly and offset < RECENT_WINDOW_DAYS:
            ndvi = max(0.0, ndvi - 0.18)
        samples.append(NdviSample(observed_at=d, ndvi=ndvi))
    return tuple(samples)


def detect_anomaly(
    *,
    tenant_id: str,
    series: tuple[NdviSample, ...],
    crop: str | None = None,
) -> AnomalyResult:
    """Run the 14-day z-score detector over a 90-day series."""
    if len(series) < RECENT_WINDOW_DAYS + BASELINE_WINDOW_DAYS:
        raise ValueError(
            f"NDVI series too short: got {len(series)}, need at least "
            f"{RECENT_WINDOW_DAYS + BASELINE_WINDOW_DAYS}."
        )

    recent = series[-RECENT_WINDOW_DAYS:]
    baseline = series[
        -(RECENT_WINDOW_DAYS + BASELINE_WINDOW_DAYS): -RECENT_WINDOW_DAYS
    ]

    rmean = _mean(s.ndvi for s in recent)
    baseline_values = [s.ndvi for s in baseline]
    intercept, slope, residual_std = _linear_detrend_stats(baseline_values)
    # `expected` = where the seasonal trajectory would put us at the
    # CENTRE of the recent window (index = n_baseline + recent_window/2).
    expected_x = len(baseline_values) + RECENT_WINDOW_DAYS / 2.0
    expected = intercept + slope * expected_x

    bmean = expected
    bstd = max(residual_std, 1e-6)   # degenerate-series guard
    z = (rmean - expected) / bstd
    is_anomaly = z <= -ANOMALY_Z_THRESHOLD

    # Disease probability from |z| via shifted sigmoid:
    # at threshold p≈0.5; further out → 1.0.
    shifted = abs(z) - ANOMALY_Z_THRESHOLD if z < 0 else -abs(z)
    disease_probability = 1.0 / (1.0 + math.exp(-shifted))
    disease_probability = max(0.0, min(1.0, disease_probability))

    abs_z = abs(z)
    if abs_z >= 2.5:
        band = "HIGH"
    elif abs_z >= 1.5:
        band = "MEDIUM"
    else:
        band = "LOW"

    return AnomalyResult(
        tenant_id=tenant_id,
        detector_name=DETECTOR_NAME,
        detector_version=DETECTOR_VERSION,
        window_start=recent[0].observed_at,
        window_end=recent[-1].observed_at,
        ndvi_recent_mean=rmean,
        ndvi_baseline_mean=bmean,
        ndvi_baseline_std=bstd,
        z_score=z,
        disease_probability=disease_probability,
        anomaly=is_anomaly,
        confidence_band=band,
        series=series,
        crop=crop,
        days_early_warning=RECENT_WINDOW_DAYS,
    )


# ─── Pure math helpers ────────────────────────────────────────────────────


def _mean(values) -> float:
    vs = list(values)
    if not vs:
        return 0.0
    return sum(vs) / len(vs)


def _linear_detrend_stats(values: list[float]) -> tuple[float, float, float]:
    """Fit y = intercept + slope * i over `values` and return
    (intercept, slope, residual_std). Pure OLS on integer index.

    Residual std is the std of (values[i] - fitted[i]) — i.e., the
    short-term noise floor after the seasonal trend is removed.
    """
    n = len(values)
    if n < 2:
        return (values[0] if values else 0.0), 0.0, 0.0
    xs = list(range(n))
    xbar = (n - 1) / 2.0
    ybar = sum(values) / n
    num = sum((xs[i] - xbar) * (values[i] - ybar) for i in range(n))
    den = sum((x - xbar) ** 2 for x in xs)
    slope = num / den if den > 0 else 0.0
    intercept = ybar - slope * xbar
    # Residuals
    residuals = [values[i] - (intercept + slope * xs[i]) for i in range(n)]
    if len(residuals) < 2:
        return intercept, slope, 0.0
    rmean = sum(residuals) / len(residuals)
    rvar = sum((r - rmean) ** 2 for r in residuals) / (len(residuals) - 1)
    return intercept, slope, math.sqrt(rvar)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
