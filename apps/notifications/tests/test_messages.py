"""Unit tests for SMS template + subscriber preference matching."""
from __future__ import annotations

import pytest

from services.messages import (
    RenderContext,
    is_verified,
    render_conflict_sms,
    should_dispatch,
    VERIFIED_LANGUAGES,
)


def _ctx(**kw) -> RenderContext:
    base = dict(
        tenant_id="kebbi",
        severity="critical",
        alert_type="conflict",
        lga="Argungu",
        zone_name=None,
        affected_area_ha=82.0,
        livelihoods_at_risk=412,
        eta_hours=6,
    )
    base.update(kw)
    return RenderContext(**base)


def test_render_includes_severity_and_state() -> None:
    body = render_conflict_sms(_ctx())
    assert "[CRITICAL]" in body
    assert "Kebbi" in body
    assert "EconomicBridge" in body


def test_render_includes_lga_when_present() -> None:
    body = render_conflict_sms(_ctx(lga="Argungu"))
    assert "Argungu" in body


def test_render_falls_back_to_zone_name_when_no_lga() -> None:
    body = render_conflict_sms(_ctx(lga=None, zone_name="NW Boundary"))
    assert "NW Boundary" in body


def test_render_includes_eta_when_provided() -> None:
    assert "ETA 6h" in render_conflict_sms(_ctx(eta_hours=6))


def test_render_skips_eta_when_none() -> None:
    body = render_conflict_sms(_ctx(eta_hours=None))
    assert "ETA" not in body


def test_render_skips_area_when_zero_or_none() -> None:
    assert "ha at risk" not in render_conflict_sms(_ctx(affected_area_ha=0))
    assert "ha at risk" not in render_conflict_sms(_ctx(affected_area_ha=None))


def test_render_includes_opt_out_footer() -> None:
    body = render_conflict_sms(_ctx())
    assert "STOP" in body
    assert "opt out" in body


def test_render_clamps_to_480_chars() -> None:
    body = render_conflict_sms(_ctx(zone_name="x" * 600))
    assert len(body) <= 480


# ─── multilingual rendering (Hausa / Yoruba / Igbo / French / Portuguese) ──


@pytest.mark.parametrize("lang", ["en", "fr", "pt", "ha", "yo", "ig"])
def test_render_all_six_languages_nonempty_and_localised(lang: str) -> None:
    body = render_conflict_sms(_ctx(), lang)
    assert body  # non-empty
    assert "EconomicBridge" in body          # brand kept
    assert "STOP" in body                    # opt-out kept in every language
    assert "Argungu" in body                 # LGA interpolated
    assert len(body) <= 480


def test_render_languages_actually_differ() -> None:
    en = render_conflict_sms(_ctx(), "en")
    fr = render_conflict_sms(_ctx(), "fr")
    ha = render_conflict_sms(_ctx(), "ig")
    assert en != fr != ha
    assert "livestock" in en          # English action phrase
    assert "betail" in fr             # French action phrase (ASCII)


def test_render_unknown_language_falls_back_to_english() -> None:
    assert render_conflict_sms(_ctx(), "zz") == render_conflict_sms(_ctx(), "en")


def test_default_language_is_english() -> None:
    assert render_conflict_sms(_ctx()) == render_conflict_sms(_ctx(), "en")


def test_verified_languages_are_en_fr_pt_only() -> None:
    # HA/YO/IG are DRAFT pending native-speaker review — must NOT be flagged
    # production-verified until reviewed.
    assert VERIFIED_LANGUAGES == frozenset({"en", "fr", "pt"})
    assert is_verified("en") and is_verified("fr") and is_verified("pt")
    assert not is_verified("ha")
    assert not is_verified("yo")
    assert not is_verified("ig")


# ─── should_dispatch ─────────────────────────────────────────────────────


def test_should_dispatch_high_severity_matches_high_threshold() -> None:
    assert should_dispatch(
        severity="high", threshold="high",
        alert_types=None, incoming_alert_type="conflict",
    )


def test_should_dispatch_medium_severity_fails_high_threshold() -> None:
    assert not should_dispatch(
        severity="medium", threshold="high",
        alert_types=None, incoming_alert_type="conflict",
    )


def test_should_dispatch_all_threshold_accepts_any() -> None:
    assert should_dispatch(
        severity="low", threshold="all",
        alert_types=None, incoming_alert_type="conflict",
    )


def test_should_dispatch_filters_by_alert_type() -> None:
    assert should_dispatch(
        severity="critical", threshold="high",
        alert_types=["conflict"], incoming_alert_type="conflict",
    )
    assert not should_dispatch(
        severity="critical", threshold="high",
        alert_types=["flood"], incoming_alert_type="conflict",
    )


def test_should_dispatch_empty_alert_types_accepts_all() -> None:
    assert should_dispatch(
        severity="critical", threshold="high",
        alert_types=None, incoming_alert_type="conflict",
    )
    assert should_dispatch(
        severity="critical", threshold="high",
        alert_types=[], incoming_alert_type="flood",
    )
