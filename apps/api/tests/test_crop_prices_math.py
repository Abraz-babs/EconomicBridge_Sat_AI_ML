"""Tests for the pure-math helpers in routers/cropguard_prices.py and
the deterministic seed builder in scripts/seed_crop_prices.py.

No DB needed — both targets are pure functions.
"""
from __future__ import annotations

import math

import pytest

from routers.cropguard_prices import _correlation_matrix, _pearson
from scripts.seed_crop_prices import CROPS, REGION_FACTORS, build_rows


# ─── Pearson r ────────────────────────────────────────────────────────────


def test_pearson_returns_one_for_identical_series():
    xs = [0.01, -0.02, 0.03, 0.005, -0.015]
    assert _pearson(xs, xs) == pytest.approx(1.0)


def test_pearson_returns_minus_one_for_perfectly_anti_correlated():
    xs = [0.01, -0.02, 0.03, 0.005, -0.015]
    ys = [-x for x in xs]
    assert _pearson(xs, ys) == pytest.approx(-1.0)


def test_pearson_returns_zero_for_zero_variance_series():
    xs = [0.5, 0.5, 0.5, 0.5]
    ys = [0.1, -0.1, 0.2, -0.2]
    # zero variance on xs → denominator is zero, returns 0 not NaN
    assert _pearson(xs, ys) == 0.0


def test_pearson_handles_mismatched_lengths_gracefully():
    assert _pearson([1, 2, 3], [1, 2]) == 0.0


def test_pearson_close_to_zero_for_random_uncorrelated():
    # Deterministic pseudo-random pair — true Pearson r ~ 0 for independent xs/ys.
    xs = [math.sin(i * 0.3) for i in range(40)]
    ys = [math.cos(i * 1.7) for i in range(40)]
    r = _pearson(xs, ys)
    assert abs(r) < 0.5


# ─── Correlation matrix ───────────────────────────────────────────────────


def test_correlation_matrix_diagonal_is_one():
    crops = ["maize", "rice", "yam"]
    aligned = [f"2026-{m:02d}" for m in range(1, 8)]
    # Same series for every crop → all r = 1.0
    series = {c: {ym: 100.0 + i * 5 for i, ym in enumerate(aligned)} for c in crops}
    m = _correlation_matrix(crops, series, aligned)
    for i in range(len(crops)):
        assert m[i][i] == pytest.approx(1.0)


def test_correlation_matrix_is_symmetric():
    crops = ["maize", "rice", "yam"]
    aligned = [f"2026-{m:02d}" for m in range(1, 8)]
    series = {
        "maize": {ym: 800 + i * 10 for i, ym in enumerate(aligned)},
        "rice":  {ym: 1900 - i * 5 for i, ym in enumerate(aligned)},
        "yam":   {ym: 1500 + i * 3 for i, ym in enumerate(aligned)},
    }
    m = _correlation_matrix(crops, series, aligned)
    for i in range(len(crops)):
        for j in range(len(crops)):
            assert m[i][j] == pytest.approx(m[j][i])


def test_correlation_matrix_returns_identity_with_too_few_points():
    crops = ["maize", "rice"]
    aligned = ["2026-01", "2026-02"]   # < 3 → no log-returns
    series = {c: {ym: 100.0 for ym in aligned} for c in crops}
    m = _correlation_matrix(crops, series, aligned)
    assert m == [[1.0, 0.0], [0.0, 1.0]]


# ─── Seed builder ─────────────────────────────────────────────────────────


def test_seed_builder_produces_full_crop_region_grid():
    """24 months × 14 crops × 10 regions = 3360 rows."""
    rows = build_rows(months=24)
    assert len(rows) == 24 * len(CROPS) * len(REGION_FACTORS)


def test_seed_builder_is_deterministic():
    rows_a = build_rows(months=12)
    rows_b = build_rows(months=12)
    assert [(r.crop, r.region, r.observed_at, r.price_ngn_per_kg) for r in rows_a] == \
           [(r.crop, r.region, r.observed_at, r.price_ngn_per_kg) for r in rows_b]


def test_seed_builder_prices_are_positive():
    for row in build_rows(months=6):
        assert row.price_ngn_per_kg > 0


def test_seed_builder_regional_factors_are_applied():
    """FCT (factor 1.15) should price higher than Kebbi (0.85) for the
    same crop in the same month."""
    rows = build_rows(months=3)
    # Pick the latest month + the same crop in both regions.
    same_month = max(r.observed_at for r in rows)
    fct_rows = [r for r in rows if r.region == "fct" and r.observed_at == same_month]
    kebbi_rows = [r for r in rows if r.region == "kebbi" and r.observed_at == same_month]
    by_crop_fct = {r.crop: r.price_ngn_per_kg for r in fct_rows}
    by_crop_kebbi = {r.crop: r.price_ngn_per_kg for r in kebbi_rows}
    # Average price across crops in FCT > Kebbi (since 1.15 > 0.85, noise
    # is bounded at ±6% so the inequality must hold on the mean).
    fct_mean = sum(by_crop_fct.values()) / len(by_crop_fct)
    kebbi_mean = sum(by_crop_kebbi.values()) / len(by_crop_kebbi)
    assert fct_mean > kebbi_mean
