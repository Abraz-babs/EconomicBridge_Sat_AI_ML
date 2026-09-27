"""GRID3 school register loader — parsing one ArcGIS feature into a row."""
from __future__ import annotations

from datetime import date

from scripts.load_grid3_schools import parse_feature


def _feature(**attrs):
    base = {
        "globalid": "{ABC}", "name": " Shanga Model Primary School ", "category": "Primary",
        "management": "Public", "education": "Formal", "wardcode": "52105",
        "lga_name": "Shanga", "state_name": "Kebbi", "no_of_stud": 0, "no_of_teac": 12,
        "source": "NMIS", "timestamp": 1589328000000,
    }
    base.update(attrs)
    return {"attributes": base, "geometry": {"x": 4.578, "y": 11.215}}


def test_parses_a_school():
    row = parse_feature(_feature())
    assert row["gid"] == "{ABC}" and row["name"] == "Shanga Model Primary School"
    assert row["lga"] == "Shanga" and row["state"] == "Kebbi"
    assert (row["lon"], row["lat"]) == (4.578, 11.215)
    assert row["surveyed_at"] == date(2020, 5, 13)


def test_zero_counts_are_unknown_not_zero():
    row = parse_feature(_feature())
    assert row["students"] is None and row["teachers"] == 12


def test_skips_unnamed_or_unplaced_schools():
    assert parse_feature(_feature(name="  ")) is None
    assert parse_feature({"attributes": _feature()["attributes"], "geometry": None}) is None
    assert parse_feature(_feature(globalid=None)) is None


def test_missing_timestamp_is_none():
    assert parse_feature(_feature(timestamp=None))["surveyed_at"] is None
