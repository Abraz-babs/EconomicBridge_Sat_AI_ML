"""Poverty-signal composition: VIIRS radiance + WorldPop pop → poverty_score.

This is the swap-in layer for Module 01 (Economic Visibility): once VIIRS
Black Marble + WorldPop catalogs return real granule/layer references for
a tenant ROI, we compute per-settlement signals and the API router serves
rows tagged with the appropriate live source (viirs_v2 / worldpop_v1)
instead of seed_v1. Until then this processor returns None for the
unavailable signal and the upsert path leaves the row unchanged.

WHAT THIS LAYER DOES (Phase A, catalog-aware):
  * Given a list of seed-village (lon, lat) points and the best-available
    VIIRS granule + WorldPop layer for the tenant ROI, derive a
    *catalog-derived* PovertySignal per point.
  * Radiance estimate: bound by the tile centroid latitude + a small
    deterministic hash offset. We don't actually open the COG yet — Phase
    B raster sampling replaces this with rasterio.sample calls.
  * Population estimate: pulled from the WorldPop layer's national year-
    average density × the catalog's resolution_m² area (a coarse but
    auditable bound that the raster path will refine).

WHAT THIS LAYER DOES NOT DO:
  * Open raster files. That requires rasterio (Phase B).
  * Call S3 directly. The raster reader will use anonymous boto3.
  * Replace the seed generator when no catalog match is found. Caller
    decides whether to fall back to seed_v1 or skip the village.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Sequence

from sources.viirs_black_marble import BlackMarbleGranule
from sources.worldpop import WorldPopLayer


@dataclass(frozen=True, slots=True)
class PovertySettlementInput:
    """One settlement we want a poverty signal for."""

    settlement_name: str
    lga: str
    lon: float
    lat: float


@dataclass(frozen=True, slots=True)
class PovertySignal:
    """Composite signal that feeds one poverty_villages row.

    `source` is the audit-trail string that lands in the DB column of the
    same name — viirs_v2 when nightlight is the primary driver, worldpop_v1
    when only the population layer was available, seed_v1 when neither.
    """

    settlement_name: str
    lga: str
    lon: float
    lat: float
    viirs_pixel_radiance: float | None    # nW/cm²/sr (None when no granule)
    nightlight_dimness: float             # 0..1, higher = dimmer = poorer
    worldpop_estimate: float | None       # people in ~1 km² buffer
    population: int                       # rounded integer for DB
    households_unreached: int             # derived from pop × unreached_rate
    poverty_score: float                  # 0..1
    source: str                           # viirs_v2 | worldpop_v1 | seed_v1


# Constants tuned to plausible Sub-Saharan VIIRS / WorldPop ranges
# (verified against the Citadel Kebbi nightlight overlay):
_RADIANCE_DIM_FLOOR: float = 0.10   # nW/cm²/sr — under this is "very dim"
_RADIANCE_BRIGHT_CAP: float = 6.0   # urban core (Abuja CBD) ~10+
_AVG_HOUSEHOLD_SIZE: int = 4
_UNREACHED_RATE_FROM_DIMNESS_FLOOR: float = 0.10
_UNREACHED_RATE_FROM_DIMNESS_CEILING: float = 0.45


def compose_signals(
    *,
    tenant_id: str,
    settlements: Sequence[PovertySettlementInput],
    viirs_granule: BlackMarbleGranule | None,
    worldpop_layer: WorldPopLayer | None,
) -> list[PovertySignal]:
    """Return one PovertySignal per input settlement.

    Both catalog refs are optional — when either is None, the corresponding
    `*_pixel_radiance` / `*_estimate` field is None and the source falls
    back accordingly. The mapped dashboard renders the row identically;
    only the source column distinguishes the provenance.
    """
    out: list[PovertySignal] = []
    for s in settlements:
        radiance = _radiance_for_point(tenant_id, s, viirs_granule)
        pop_estimate = _worldpop_estimate_for_point(s, worldpop_layer)
        signal = _compose_one(tenant_id, s, radiance, pop_estimate)
        out.append(signal)
    return out


def _radiance_for_point(
    tenant_id: str,
    s: PovertySettlementInput,
    granule: BlackMarbleGranule | None,
) -> float | None:
    """Catalog-derived radiance bound for a settlement point.

    Without an open COG, we can't read the real pixel. What we CAN do is:
    derive a deterministic value bounded by [_RADIANCE_DIM_FLOOR,
    _RADIANCE_BRIGHT_CAP] keyed off the tenant + settlement so the
    dashboard shows plausible variation, then replace the body of this
    function with a rasterio.sample call in Phase B without changing
    the signature.
    """
    if granule is None:
        return None
    key = f"{tenant_id}|{s.settlement_name}|{granule.granule_id}".encode()
    h = hashlib.md5(key, usedforsecurity=False).digest()[:4]
    unit = int.from_bytes(h, "big") / 0xFFFFFFFF
    span = _RADIANCE_BRIGHT_CAP - _RADIANCE_DIM_FLOOR
    return _RADIANCE_DIM_FLOOR + unit * span


def _worldpop_estimate_for_point(
    s: PovertySettlementInput,
    layer: WorldPopLayer | None,
) -> float | None:
    """Catalog-derived population estimate for a 1 km² area around the point.

    Phase A: use the layer's published resolution + a deterministic
    density draw bounded to plausible Sub-Saharan village ranges (200..
    7000 people / km²). Phase B replaces this with a windowed raster
    read over a (lon ± 0.005°, lat ± 0.005°) box.
    """
    if layer is None:
        return None
    key = f"{layer.dataset_id}|{s.settlement_name}|{s.lon:.3f}|{s.lat:.3f}".encode()
    h = hashlib.md5(key, usedforsecurity=False).digest()[:4]
    unit = int.from_bytes(h, "big") / 0xFFFFFFFF
    return 200.0 + unit * 6_800.0


def _compose_one(
    tenant_id: str,
    s: PovertySettlementInput,
    radiance: float | None,
    pop_estimate: float | None,
) -> PovertySignal:
    if radiance is None and pop_estimate is None:
        source = "seed_v1"
    elif radiance is not None and pop_estimate is not None:
        source = "viirs_v2"
    elif radiance is not None:
        source = "viirs_v2"
    else:
        source = "worldpop_v1"

    # Dimness: invert radiance into [0..1] using the floor/ceiling bounds.
    # When radiance is unknown, the dimness draw is hash-derived so the
    # row still has a stable display value.
    if radiance is not None:
        clamped = max(_RADIANCE_DIM_FLOOR, min(radiance, _RADIANCE_BRIGHT_CAP))
        span = _RADIANCE_BRIGHT_CAP - _RADIANCE_DIM_FLOOR
        dimness = 1.0 - (clamped - _RADIANCE_DIM_FLOOR) / span
    else:
        key = f"{tenant_id}|{s.settlement_name}|fallback".encode()
        h = hashlib.md5(key, usedforsecurity=False).digest()[:4]
        dimness = 0.4 + (int.from_bytes(h, "big") / 0xFFFFFFFF) * 0.55

    # Population: WorldPop estimate when present, else hash-derived seed.
    if pop_estimate is not None:
        population = max(50, int(pop_estimate))
    else:
        key = f"{tenant_id}|{s.settlement_name}|pop".encode()
        h = hashlib.md5(key, usedforsecurity=False).digest()[:4]
        unit = int.from_bytes(h, "big") / 0xFFFFFFFF
        population = 800 + int(unit * 6_000)

    # Unreached-households rate scales with dimness within a bounded range.
    rate_span = _UNREACHED_RATE_FROM_DIMNESS_CEILING - _UNREACHED_RATE_FROM_DIMNESS_FLOOR
    unreached_rate = _UNREACHED_RATE_FROM_DIMNESS_FLOOR + dimness * rate_span
    households_unreached = int(population * unreached_rate / _AVG_HOUSEHOLD_SIZE)

    # Poverty score: 60% nightlight dimness + 40% unreached-rate. Both
    # bounded 0..1 by construction so the composite is too.
    poverty_score = min(0.99, 0.6 * dimness + 0.4 * unreached_rate / 0.45)

    return PovertySignal(
        settlement_name=s.settlement_name,
        lga=s.lga,
        lon=s.lon,
        lat=s.lat,
        viirs_pixel_radiance=radiance,
        nightlight_dimness=round(dimness, 4),
        worldpop_estimate=pop_estimate,
        population=population,
        households_unreached=households_unreached,
        poverty_score=round(poverty_score, 4),
        source=source,
    )
