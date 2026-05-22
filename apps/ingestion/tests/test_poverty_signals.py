"""Unit tests for processors/poverty_signals.py."""
from __future__ import annotations

from datetime import datetime, timezone

from processors.poverty_signals import (
    PovertySettlementInput,
    compose_signals,
)
from sources.viirs_black_marble import BlackMarbleGranule
from sources.worldpop import WorldPopLayer


def _granule(name: str = "VNP46A2.A2026140.h16v07.001.x.h5") -> BlackMarbleGranule:
    return BlackMarbleGranule(
        granule_id=name,
        product="VNP46A2",
        captured_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
        tile_h=16,
        tile_v=7,
        download_url="https://ladsweb...",
        size_bytes=12_345_678,
    )


def _layer(year: int = 2024) -> WorldPopLayer:
    return WorldPopLayer(
        dataset_id=42,
        iso3="NGA",
        year=year,
        title="Nigeria population",
        resolution_m=100,
        download_url="https://data.worldpop.org/.../nga_ppp_2024.tif",
        file_size_bytes=87_654_321,
    )


def _settlement(name: str = "Argungu settlement 1") -> PovertySettlementInput:
    return PovertySettlementInput(
        settlement_name=name, lga="Argungu", lon=4.5, lat=12.0,
    )


# ─── Source tagging ───────────────────────────────────────────────────────


def test_both_signals_present_tags_viirs_v2():
    signals = compose_signals(
        tenant_id="kebbi", settlements=[_settlement()],
        viirs_granule=_granule(), worldpop_layer=_layer(),
    )
    assert signals[0].source == "viirs_v2"
    assert signals[0].viirs_pixel_radiance is not None
    assert signals[0].worldpop_estimate is not None


def test_only_worldpop_tags_worldpop_v1():
    signals = compose_signals(
        tenant_id="kebbi", settlements=[_settlement()],
        viirs_granule=None, worldpop_layer=_layer(),
    )
    assert signals[0].source == "worldpop_v1"
    assert signals[0].viirs_pixel_radiance is None
    assert signals[0].worldpop_estimate is not None


def test_only_viirs_tags_viirs_v2():
    signals = compose_signals(
        tenant_id="kebbi", settlements=[_settlement()],
        viirs_granule=_granule(), worldpop_layer=None,
    )
    assert signals[0].source == "viirs_v2"
    assert signals[0].viirs_pixel_radiance is not None
    assert signals[0].worldpop_estimate is None


def test_no_catalogs_falls_back_to_seed():
    signals = compose_signals(
        tenant_id="kebbi", settlements=[_settlement()],
        viirs_granule=None, worldpop_layer=None,
    )
    assert signals[0].source == "seed_v1"


# ─── Bounded outputs ──────────────────────────────────────────────────────


def test_dimness_bounded_zero_to_one():
    """Dimness must always land in [0, 1] regardless of input combination."""
    for granule in (None, _granule()):
        for layer in (None, _layer()):
            sigs = compose_signals(
                tenant_id="kebbi", settlements=[_settlement(f"v-{granule}-{layer}")],
                viirs_granule=granule, worldpop_layer=layer,
            )
            assert 0.0 <= sigs[0].nightlight_dimness <= 1.0


def test_poverty_score_bounded_zero_to_one():
    sigs = compose_signals(
        tenant_id="kebbi",
        settlements=[_settlement(f"v-{i}") for i in range(20)],
        viirs_granule=_granule(), worldpop_layer=_layer(),
    )
    for s in sigs:
        assert 0.0 <= s.poverty_score <= 1.0


def test_population_at_least_floor():
    sigs = compose_signals(
        tenant_id="kebbi", settlements=[_settlement()],
        viirs_granule=_granule(), worldpop_layer=_layer(),
    )
    assert sigs[0].population >= 50


def test_radiance_within_published_bounds():
    sigs = compose_signals(
        tenant_id="kebbi",
        settlements=[_settlement(f"v-{i}") for i in range(20)],
        viirs_granule=_granule(), worldpop_layer=_layer(),
    )
    for s in sigs:
        assert s.viirs_pixel_radiance is not None
        # Dim floor 0.10 nW/cm²/sr, bright cap 6.0 — published Citadel range.
        assert 0.10 <= s.viirs_pixel_radiance <= 6.0


def test_households_unreached_does_not_exceed_population():
    """Sanity: unreached households × avg_size shouldn't exceed population."""
    sigs = compose_signals(
        tenant_id="kebbi",
        settlements=[_settlement(f"v-{i}") for i in range(20)],
        viirs_granule=_granule(), worldpop_layer=_layer(),
    )
    for s in sigs:
        assert s.households_unreached * 4 <= s.population


# ─── Determinism ──────────────────────────────────────────────────────────


def test_compose_is_deterministic_per_inputs():
    """Same inputs → identical signals across runs."""
    a = compose_signals(
        tenant_id="kebbi", settlements=[_settlement()],
        viirs_granule=_granule(), worldpop_layer=_layer(),
    )
    b = compose_signals(
        tenant_id="kebbi", settlements=[_settlement()],
        viirs_granule=_granule(), worldpop_layer=_layer(),
    )
    assert a == b


def test_different_granules_yield_different_radiance():
    """Switching to a newer granule changes the radiance draw — that's
    what lets the dashboard show day-to-day variation when real raster
    sampling lands."""
    g1 = _granule("VNP46A2.A2026140.h16v07.001.x.h5")
    g2 = _granule("VNP46A2.A2026141.h16v07.001.x.h5")
    a = compose_signals(
        tenant_id="kebbi", settlements=[_settlement()],
        viirs_granule=g1, worldpop_layer=_layer(),
    )
    b = compose_signals(
        tenant_id="kebbi", settlements=[_settlement()],
        viirs_granule=g2, worldpop_layer=_layer(),
    )
    assert a[0].viirs_pixel_radiance != b[0].viirs_pixel_radiance


def test_different_tenants_yield_different_signals():
    sigs_a = compose_signals(
        tenant_id="kebbi", settlements=[_settlement()],
        viirs_granule=_granule(), worldpop_layer=_layer(),
    )
    sigs_b = compose_signals(
        tenant_id="benue", settlements=[_settlement()],
        viirs_granule=_granule(), worldpop_layer=_layer(),
    )
    assert sigs_a[0].nightlight_dimness != sigs_b[0].nightlight_dimness
