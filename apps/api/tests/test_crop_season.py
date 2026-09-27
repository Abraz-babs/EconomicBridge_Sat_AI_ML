"""Season watch: farmland per season, like-for-like change, weakest gain first."""
from routers.cropguard import _patch_kind, _season_lgas


def _v(lga, year, crops, rng, common=None, prev_common=None, seen=None, lga_ha=100_000.0):
    return {"lga": lga, "season_year": year, "lga_ha": lga_ha,
            "greened_on_crops_ha": crops, "greened_on_rangeland_ha": rng,
            "greened_ha_common": common, "prev_greened_ha_common": prev_common,
            "common_observed_ha": seen}


VEG = [
    _v("Aleiro", 2024, 1874.2, 15133.9),
    _v("Aleiro", 2025, 1691.4, 13446.7, 16077.0, 18049.1, 26877.5, 26904.7),
    _v("Aleiro", 2026, 1998.2, 16842.0, 19953.5, 16082.3, 26882.7, 26904.7),
    _v("Ngaski", 2025, 20000.0, 154368.0),
    _v("Ngaski", 2026, 22292.0, 160360.0, 104500.0, 100000.0, 82000.0),
    _v("Benue-like", 2026, 500.0, 900.0, None, None, 10000.0),
]


def test_farmland_is_crops_plus_rangeland_per_season():
    rows, latest, prev = _season_lgas(VEG, {})
    aleiro = next(r for r in rows if r.lga == "Aleiro")
    assert (latest, prev) == (2026, 2025)
    assert aleiro.farmland_ha[2024] == round(1874.2 + 15133.9, 1)
    assert aleiro.farmland_ha[2026] == round(1998.2 + 16842.0, 1)
    assert aleiro.crops_ha == 1998.2


def test_like_for_like_compares_the_same_ground():
    rows, _, _ = _season_lgas(VEG, {})
    aleiro = next(r for r in rows if r.lga == "Aleiro")
    assert aleiro.like_for_like_pct == round(100 * (19953.5 / 16082.3 - 1), 1)
    assert aleiro.seen_pct == round(100 * 26882.7 / 26904.7)


def test_weakest_gain_first_and_uncomparable_last():
    rows, _, _ = _season_lgas(VEG, {"Ngaski": 11})
    assert [r.lga for r in rows] == ["Ngaski", "Aleiro", "Benue-like"]
    assert rows[0].stopped_growing == 11
    assert rows[-1].like_for_like_pct is None  # cloud: shown as a gap, not a number


def test_patch_kind_reads_the_detection_text():
    assert _patch_kind("… crops that greened in 2024 and 2025 stayed bare …") == "crops"
    assert _patch_kind("… rangeland that greened in 2024 and 2025 …") == "rangeland"
    assert _patch_kind(None) == "farmland"


def test_nothing_measured_nothing_invented():
    rows, latest, prev = _season_lgas([], {})
    assert rows == [] and latest is None and prev is None
