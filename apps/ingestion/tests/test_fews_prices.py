"""Unit tests for sources/fews_prices.py. No network (CLAUDE.md §11).

The failure modes worth guarding are all silent: a volume or a count treated as
a mass, a wholesale price mixed into a retail series, or one market's outlier
presented as a state price.
"""
from __future__ import annotations

from datetime import date

from sources.fews_prices import (
    CROP_BY_PRODUCT,
    TENANT_BY_ADMIN1,
    MarketPrice,
    kg_multiplier,
    parse_rows,
)


def _row(**kw):
    base = {
        "value": 100.0, "price_type": "Retail", "currency": "NGN",
        "admin_1": "Kebbi", "admin_2": "Argungu", "market": "Argungu",
        "product": "Maize Grain (White)", "unit": "kg", "unit_type": "Weight",
        "period_date": "2026-06-30",
    }
    base.update(kw)
    return base


# ─── units: mass only ─────────────────────────────────────────────────────


def test_weight_units_convert_by_their_quantity() -> None:
    assert kg_multiplier("kg", "Weight") == 1.0
    assert kg_multiplier("50_kg", "Weight") == 0.02
    assert kg_multiplier("100_kg", "Weight") == 0.01


def test_volume_and_item_units_are_skipped_not_guessed() -> None:
    """Oil is litres, bread and livestock are counts, yams are sold by tuber —
    none has a stated weight, so none may be converted to a per-kg price."""
    for unit, utype in (("L", "Volume"), ("30_L", "Volume"), ("ea", "Item"),
                        ("100_tubers", "Item"), ("60_tubers", "Item")):
        assert kg_multiplier(unit, utype) is None, unit


def test_bulk_sack_price_is_divided_to_per_kg() -> None:
    rows = parse_rows([_row(value=45000.0, unit="100_kg")])
    assert rows[0].price_ngn_per_kg == 450.0


def test_rows_with_unusable_units_produce_nothing() -> None:
    assert parse_rows([
        _row(product="Palm Oil (Refined)", unit="L", unit_type="Volume"),
        _row(product="Bread", unit="ea", unit_type="Item"),
    ]) == []


# ─── filtering ────────────────────────────────────────────────────────────


def test_wholesale_is_excluded_so_the_series_stays_comparable_to_nbs() -> None:
    """NBS publishes retail. Mixing wholesale in would silently depress the
    series and make the two sources incomparable for the same crop."""
    rows = parse_rows([
        _row(value=100.0, price_type="Retail"),
        _row(value=40.0, price_type="Wholesale"),
    ])
    assert len(rows) == 1
    assert rows[0].price_ngn_per_kg == 100.0


def test_states_we_do_not_run_are_ignored() -> None:
    assert parse_rows([_row(admin_1="Borno")]) == []


def test_unmapped_products_are_ignored() -> None:
    assert parse_rows([_row(product="Cattle (Male)", unit="ea", unit_type="Item")]) == []


def test_non_ngn_rows_are_ignored() -> None:
    assert parse_rows([_row(currency="USD")]) == []


def test_since_filters_older_months() -> None:
    rows = parse_rows(
        [_row(period_date="2024-01-31"), _row(period_date="2026-06-30")],
        since=date(2026, 1, 1),
    )
    assert [r.observed_at for r in rows] == [date(2026, 6, 30)]


# ─── aggregation ──────────────────────────────────────────────────────────


def test_multiple_markets_are_reduced_by_median_not_mean() -> None:
    """A single mis-keyed market must not drag the state price. Median of
    100/110/1000 is 110; the mean would be ~403."""
    rows = parse_rows([
        _row(value=100.0, market="A"),
        _row(value=110.0, market="B"),
        _row(value=1000.0, market="C"),
    ])
    assert len(rows) == 1
    assert rows[0].price_ngn_per_kg == 110.0
    assert rows[0].markets == 3


def test_market_count_is_reported_so_thin_evidence_is_visible() -> None:
    """One market backing a whole state is legitimate but must be visible —
    it is the difference between a state price and one trader's price."""
    rows = parse_rows([_row(value=250.0)])
    assert rows[0].markets == 1


def test_rows_are_grouped_per_crop_tenant_and_month() -> None:
    rows = parse_rows([
        _row(product="Maize Grain (White)", admin_1="Kebbi"),
        _row(product="Millet (Pearl)", admin_1="Kebbi"),
        _row(product="Maize Grain (White)", admin_1="Zamfara"),
        _row(product="Maize Grain (White)", admin_1="Kebbi", period_date="2026-05-31"),
    ])
    assert len(rows) == 4
    assert {(r.crop, r.tenant, r.observed_at.month) for r in rows} == {
        ("maize", "kebbi", 6), ("millet", "kebbi", 6),
        ("maize", "zamfara", 6), ("maize", "kebbi", 5),
    }


def test_bad_values_are_dropped_not_zeroed() -> None:
    assert parse_rows([
        _row(value=None), _row(value=0), _row(value=-5),
        _row(value="not-a-number"), _row(period_date=None),
    ]) == []


# ─── vocabulary alignment with NBS ────────────────────────────────────────


def test_crop_keys_overlap_the_nbs_vocabulary() -> None:
    """Both sources must name the same crop identically or the merge silently
    creates duplicate series for one commodity. Base names only — "Maize", not
    "Maize (white)"."""
    from sources.nbs_food_prices import UNIT_BASIS

    nbs_crops = {crop for crop, _ in UNIT_BASIS.values()}
    fews_crops = set(CROP_BY_PRODUCT.values())
    shared = nbs_crops & fews_crops
    assert {"maize", "rice", "cowpea", "cassava", "yam"} <= shared


def test_every_mapped_tenant_is_a_real_pilot() -> None:
    assert set(TENANT_BY_ADMIN1.values()) == {
        "kebbi", "kaduna", "zamfara", "niger", "benue",
        "plateau", "nasarawa", "fct",
    }


def test_marketprice_is_per_kg_by_construction() -> None:
    p = MarketPrice(crop="maize_white", tenant="kebbi", admin_1="Kebbi",
                    observed_at=date(2026, 6, 30), price_ngn_per_kg=387.48, markets=2)
    assert p.price_ngn_per_kg > 0 and p.markets == 2


# ─── the ingest task: two sources, kept distinct ──────────────────────────


def test_sources_are_written_as_separate_rows_not_averaged() -> None:
    """NBS is a ZONE average; FEWS is a state figure. Averaging them would
    invent a number neither publisher stands behind, and would change meaning
    month to month depending on which source had data."""
    import inspect

    from tasks import food_prices_ingest

    src = inspect.getsource(food_prices_ingest)
    assert "NBS_SOURCE" in src and "FEWS_SOURCE" in src
    for bad in ("mean(", "average(", "/ 2"):
        assert bad not in src, f"sources look combined via {bad}"


def test_ingest_is_idempotent_per_source_and_month() -> None:
    """Re-running a month must correct it, not duplicate it."""
    import inspect

    from tasks import food_prices_ingest

    src = inspect.getsource(food_prices_ingest._replace_slice)
    assert "DELETE FROM public.crop_prices" in src
    assert "source = :s" in src and "observed_at = :d" in src


def test_run_audit_uses_real_ingestion_runs_columns() -> None:
    import inspect

    from tasks import food_prices_ingest

    cols = inspect.getsource(food_prices_ingest._record_run)
    cols = cols.split("INSERT INTO public.ingestion_runs (", 1)[1].split(")", 1)[0]
    assert "records_ingested" in cols and "error_message" in cols and "dry_run" in cols


def test_schema_drift_is_recorded_not_swallowed() -> None:
    """An NBS layout change must surface in the run record, not vanish."""
    import inspect

    from tasks import food_prices_ingest

    src = inspect.getsource(food_prices_ingest.ingest)
    assert "NbsSchemaError" in src
    assert "result.errors.append" in src


def test_lookback_covers_late_nbs_publication() -> None:
    from datetime import date as _d

    from tasks.food_prices_ingest import LOOKBACK_MONTHS, _months_back

    assert LOOKBACK_MONTHS >= 2, "NBS lags a month; a 1-month window misses it"
    months = _months_back(3, today=_d(2026, 3, 15))
    assert months == [_d(2026, 1, 1), _d(2026, 2, 1), _d(2026, 3, 1)]


def test_food_price_job_registered_monthly() -> None:
    import inspect

    from scheduler import JOB_ID_FOOD_PRICES_MONTHLY, setup_scheduler

    src = inspect.getsource(setup_scheduler)
    assert "run_food_price_ingest" in src
    # the source references the constant by NAME, so assert the reference and
    # the constant's value separately
    assert "JOB_ID_FOOD_PRICES_MONTHLY" in src
    assert JOB_ID_FOOD_PRICES_MONTHLY == "food_prices_monthly_5th_0930utc"
    assert "day=5" in src            # monthly, not daily


def test_region_is_the_tenant_id_so_the_panel_can_query_it() -> None:
    """routers/cropguard_prices.py resolves `region` from X-Tenant-Id, so a row
    written with the FEWS spelling ("Zamfara") or the NBS zone ("NORTH WEST")
    lands in the table and can NEVER be queried by the panel. Writing 26 real
    prices that nobody could see is exactly how this failed the first time."""
    import inspect

    from tasks import food_prices_ingest

    src = inspect.getsource(food_prices_ingest.ingest)
    assert '"region": mp.tenant' in src        # FEWS -> tenant id
    assert '"region": tenant' in src           # NBS zone fanned out per tenant
    assert '"region": mp.admin_1' not in src
    assert '"region": zp.zone' not in src


def test_nbs_zone_figure_is_fanned_out_to_every_tenant_in_that_zone() -> None:
    """A North West figure must reach kebbi, kaduna AND zamfara — but stay
    tagged nbs_zone_v1 so it is never mistaken for a state-specific price."""
    import inspect

    from sources.nbs_food_prices import ZONE_BY_TENANT
    from tasks import food_prices_ingest

    src = inspect.getsource(food_prices_ingest.ingest)
    assert "ZONE_BY_TENANT" in src
    nw = [t for t, z in ZONE_BY_TENANT.items() if z == "NORTH WEST"]
    assert set(nw) == {"kebbi", "kaduna", "zamfara"}


def test_no_two_products_map_to_the_same_crop() -> None:
    """One reference variety per crop. If both white and yellow maize mapped to
    "maize" we would write two different prices for the same crop/region/month
    and no chart could say which one it was showing."""
    crops = list(CROP_BY_PRODUCT.values())
    assert len(crops) == len(set(crops)), "a crop has two source products"


def test_crop_names_are_base_names_not_varieties() -> None:
    """Operator decision 2026-07-27: keep "maize", not "maize_white"."""
    from sources.nbs_food_prices import UNIT_BASIS

    for crop in {*CROP_BY_PRODUCT.values(), *(c for c, _ in UNIT_BASIS.values())}:
        assert not any(
            crop.endswith(sfx)
            for sfx in ("_white", "_yellow", "_brown", "_local", "_imported")
        ), crop
