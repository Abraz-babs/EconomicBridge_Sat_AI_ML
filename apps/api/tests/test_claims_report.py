"""Claims verification report: renders, never says "rejected", stays admin-only."""
from __future__ import annotations

from datetime import datetime, timezone

from services.claims_report import (
    FIELD_VISIT,
    OUTCOME_COLOUR,
    OUTCOME_LABEL,
    ClaimsBatch,
    ReportClaim,
    outcome_counts,
    render_claims_report,
)


def _result(conclusion: str, flood: str = "strong") -> dict:
    return {
        "lat": 11.3, "lon": 4.2167, "loss_date": "2024-09-07", "peril": "flood", "crop": "general",
        "area_ha": 1.44,
        "windows": {"before": "2024-07-09 to 2024-09-04", "after": "2024-09-05 to 2024-10-07"},
        "thresholds": {"water_vv_db_below": -17.0, "flood_strong_share": 0.4, "flood_partial_share": 0.15,
                       "ndvi_marked_drop": 0.15, "ndvi_moderate_drop": 0.08, "min_valid_fraction": 0.25},
        "ndvi_passes": [{"date": "2024-08-20", "ndvi": 0.31, "plot_seen": 0.9, "window": "before"}],
        "water_passes": [{"date": "2024-08-25", "water_share": 0.066, "plot_seen": 1.0, "window": "before"},
                         {"date": "2024-09-18", "water_share": 0.471, "plot_seen": 1.0, "window": "after"}],
        "metrics": {"water_share_before": 0.066, "water_share_after_peak": 0.471, "ndvi_before": 0.31,
                    "ndvi_after_low": 0.2, "ndvi_change": -0.11},
        "flood_evidence": flood, "vegetation_change": "moderate", "conclusion": conclusion,
        "summary": "Radar shows open water.", "recommendation": "Normal claim handling applies.",
        "limitations": ["Indicative."], "source": "copernicus_sentinel_claim_v1",
    }


def _batch() -> ClaimsBatch:
    return ClaimsBatch(client_name="Test Insurer", batch_ref="T-001", claims=[
        ReportClaim("C1", _result("supports"), insured_name="A. Farmer", location_note="Bagudo"),
        ReportClaim("C2", _result("not_supported", "none")),
        ReportClaim("C3", _result("inconclusive", "insufficient")),
    ])


def test_renders_a_pdf() -> None:
    pdf = render_claims_report(_batch(), generated_at=datetime(2026, 10, 8, tzinfo=timezone.utc))
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 5_000


def test_counts_and_field_visits() -> None:
    counts = outcome_counts(_batch())
    assert counts == {"supports": 1, "partly_supports": 0, "not_supported": 1, "inconclusive": 1}
    assert sum(counts[k] for k in FIELD_VISIT) == 2


def test_labels_never_reject_and_never_use_red() -> None:
    for label in OUTCOME_LABEL.values():
        low = label.lower()
        assert "reject" not in low and "deny" not in low and "fraud" not in low
    for colour in OUTCOME_COLOUR.values():
        assert colour.lower() not in ("#ff0000", "#cc0000", "#d32f2f", "#c0392b")


def test_endpoint_is_super_admin_only() -> None:
    """The router must depend on require_super_admin (downloads are paid)."""
    import inspect

    from routers import claims

    src = inspect.getsource(claims.claims_report)
    assert "require_super_admin" in src
