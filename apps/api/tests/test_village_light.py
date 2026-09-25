"""Economic Visibility village-light API — the village reach list export, DB-free."""
from __future__ import annotations

# ─── Village reach list (CSV) ────────────────────────────────────────────

def test_export_rows_rank_coordinates_and_directions():
    from routers.economic_visibility import EXPORT_COLUMNS, export_rows
    rows = export_rows([
        ("Unguwar Hakimi", "Shanga", "Shanga", 4.5812345, 11.2123456, "unlit", "unlit", 0.21, 0.3, 9355, 1870),
        ("Sawashi", None, "Shanga", 4.6, 11.3, "unlit", None, None, None, 5516, 1103),
    ], "2026", "VIIRS; HRSL; GRID3")
    assert len(rows[0]) == len(EXPORT_COLUMNS)
    first = dict(zip(EXPORT_COLUMNS, rows[0]))
    assert first["rank"] == 1 and first["latitude"] == 11.21235 and first["longitude"] == 4.58123
    assert first["directions"].endswith("destination=11.21235,4.58123")
    second = dict(zip(EXPORT_COLUMNS, rows[1]))
    assert second["rank"] == 2 and second["ward"] == "" and second["radiance_dry_nw"] == ""


def test_export_columns_say_the_people_figures_are_estimates():
    from routers.economic_visibility import EXPORT_COLUMNS
    assert "people_estimate" in EXPORT_COLUMNS and "under5_estimate" in EXPORT_COLUMNS


def test_export_requires_a_tenant():
    from fastapi.testclient import TestClient
    from main import app
    r = TestClient(app).get("/api/v1/economic_visibility/village-light/export.csv")
    assert r.status_code == 400
