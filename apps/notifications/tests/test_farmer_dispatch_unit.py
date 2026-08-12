"""Farmer-advisory dispatch — the path that carries the copy farmers receive.

These are unit tests over the dispatcher's decisions (who matches, what is
rendered, how a failed INSERT is classified). The gateway and session are
doubles; nothing here touches a database or sends an SMS.

The IntegrityError tests exist because of a live defect: `_insert_outbox_row`
caught IntegrityError and reported every failure as `skipped_duplicate`. A
CHECK violation therefore looked like "nothing new to send" while delivering
nothing — and that is precisely what would have happened on the first real
Kebbi send, because 'sns' was missing from `chk_sms_outbox_provider` until
migration 0043.
"""
from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from services.dispatcher import (
    DispatchOutcome,
    SubscriberRow,
    _is_duplicate_violation,
    dispatch_farmer_advisory,
)
from services.messages import FARMER_WITHHELD, STATE_NAMES, render_farmer_sms
from uuid import uuid4


class _FakeOrig:
    """Stands in for the driver error SQLAlchemy wraps (asyncpg: .sqlstate)."""

    def __init__(self, sqlstate: str) -> None:
        self.sqlstate = sqlstate


def _integrity_error(sqlstate: str) -> IntegrityError:
    return IntegrityError("stmt", {}, _FakeOrig(sqlstate))


# ─── classification of a failed INSERT ────────────────────────────────────


def test_unique_violation_is_a_duplicate() -> None:
    assert _is_duplicate_violation(_integrity_error("23505")) is True


def test_check_violation_is_not_a_duplicate() -> None:
    """23514 is the SNS-provider case. Reporting it as a duplicate is the bug."""
    assert _is_duplicate_violation(_integrity_error("23514")) is False


def test_not_null_violation_is_not_a_duplicate() -> None:
    assert _is_duplicate_violation(_integrity_error("23502")) is False


def test_missing_sqlstate_fails_closed() -> None:
    """Unknown driver shape must surface the error, never mask it as a dup."""
    err = IntegrityError("stmt", {}, Exception("no sqlstate here"))
    assert _is_duplicate_violation(err) is False


# ─── withheld advisory types ──────────────────────────────────────────────


@pytest.mark.parametrize("advisory", FARMER_WITHHELD)
def test_withheld_advisories_raise_rather_than_render(advisory: str) -> None:
    """drought / flood / conflict must not reach a farmer on a caller's typo."""
    with pytest.raises(ValueError, match="withheld"):
        render_farmer_sms(advisory, lga="Argungu", state="Kebbi")


def test_unknown_advisory_raises() -> None:
    with pytest.raises(ValueError, match="unknown farmer advisory"):
        render_farmer_sms("locusts", lga="Argungu", state="Kebbi")


# ─── dispatch behaviour ───────────────────────────────────────────────────


class _FakeGateway:
    name = "sns"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, *, phone_e164: str, message: str):  # noqa: ANN201
        from gateways.base import SendResult

        self.sent.append((phone_e164, message))
        return SendResult(
            status="sent", provider_message_id="msg-1",
            error_message=None, cost_units=1.0, cost_currency="USD",
        )


@pytest.mark.asyncio
async def test_dry_run_sends_nothing_and_returns_the_body(monkeypatch) -> None:
    """A dry run must render real copy while spending nothing."""
    subs = [
        SubscriberRow(
            id=uuid4(), phone_e164="+2348010000001", language="ha",
            lga="Argungu", severity_threshold="high", alert_types=None,
        ),
    ]

    async def _fake_fetch(session, **kwargs):  # noqa: ANN001, ANN202
        return subs

    monkeypatch.setattr(
        "services.dispatcher.fetch_advisory_subscribers", _fake_fetch,
    )
    gw = _FakeGateway()

    outcomes = await dispatch_farmer_advisory(
        session=None,  # never touched on the dry-run path
        tenant_id="kebbi", advisory="rainfall", lga="Argungu", state="Kebbi",
        related_alert_id=None, trace_id=uuid4(), gateway=gw, dry_run=True,
    )

    assert gw.sent == [], "dry run must not call the gateway"
    assert len(outcomes) == 1
    out: DispatchOutcome = outcomes[0]
    assert out.status == "dry_run"
    assert out.language == "ha"
    # The Hausa rainfall copy says the rain FELL, never that it is expected.
    assert "an yi ruwan sama" in (out.error_message or "")
    assert "Argungu" in (out.error_message or "")


@pytest.mark.asyncio
async def test_no_subscribers_returns_empty(monkeypatch) -> None:
    async def _none(session, **kwargs):  # noqa: ANN001, ANN202
        return []

    monkeypatch.setattr("services.dispatcher.fetch_advisory_subscribers", _none)
    outcomes = await dispatch_farmer_advisory(
        session=None, tenant_id="kebbi", advisory="fire", lga="Zuru",
        state="Kebbi", related_alert_id=None, trace_id=uuid4(),
        gateway=_FakeGateway(), dry_run=True,
    )
    assert outcomes == []


@pytest.mark.asyncio
async def test_withheld_type_raises_before_any_send(monkeypatch) -> None:
    """The safety gate must fire even with subscribers waiting."""
    subs = [
        SubscriberRow(
            id=uuid4(), phone_e164="+2348010000001", language="en",
            lga="Argungu", severity_threshold="high", alert_types=None,
        ),
    ]

    async def _fake_fetch(session, **kwargs):  # noqa: ANN001, ANN202
        return subs

    monkeypatch.setattr(
        "services.dispatcher.fetch_advisory_subscribers", _fake_fetch,
    )
    gw = _FakeGateway()
    with pytest.raises(ValueError, match="withheld"):
        await dispatch_farmer_advisory(
            session=None, tenant_id="kebbi", advisory="drought", lga="Argungu",
            state="Kebbi", related_alert_id=None, trace_id=uuid4(),
            gateway=gw, dry_run=True,
        )
    assert gw.sent == []


# ─── the copy itself ──────────────────────────────────────────────────────


def test_english_rainfall_states_observation_not_forecast() -> None:
    body = render_farmer_sms("rainfall", lga="Argungu", state="Kebbi", lang="en")
    assert "recorded" in body
    assert "expected" not in body.lower()
    assert "Reply STOP" in body


def test_unknown_language_falls_back_to_english() -> None:
    body = render_farmer_sms("fire", lga="Zuru", state="Kebbi", lang="zz")
    assert body == render_farmer_sms("fire", lga="Zuru", state="Kebbi", lang="en")


# ─── message length, measured against real LGA names ──────────────────────
#
# Length is a cost control, not cosmetics: over 160 GSM-7 characters the
# message splits into two segments and costs twice as much, which matters while
# the SNS spend cap is $1/month. A single accented character is worse still —
# it forces UCS-2 and drops the limit to 70.
#
# These tests read the real centroid file rather than inventing a worst case.
# An earlier version of this test paired the longest LGA name in the platform
# with the longest state name and "failed" on a combination that cannot occur
# (Wasagu/Danko is in Kebbi, not Nasarawa).

_ADVISORIES = ("enrolment", "rainfall", "fire", "crop_stress", "land_change")
_GSM7_SINGLE_SEGMENT = 160

# Measured 2026-08-12. Hausa is longer than English almost everywhere, so the
# three below cross 160 at Zamfara's longest LGA name, "Birnin Magaji-Kiyaw"
# (19 chars). They are pinned rather than silently tolerated: shortening the
# Hausa is the operator's call — it is their translation — and this set makes
# both a regression and a fix visible.
_KNOWN_OVERFLOW_OUTSIDE_KEBBI = {
    ("ha", "enrolment"),    # 167 chars
    ("ha", "fire"),         # 165
    ("ha", "crop_stress"),  # 168
}


def _lga_data() -> dict:
    import json
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[3] / "apps" / "api" / "data"
        / "lga_centroids.json"
    )
    if not path.exists():
        pytest.skip(f"LGA centroid data not available at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _worst(tenants, lang: str, advisory: str) -> tuple[int, str, str]:
    data = _lga_data()
    hi = (0, "", "")
    for tenant in tenants:
        state = STATE_NAMES.get(tenant, tenant.title())
        for row in data.get(tenant, []):
            body = render_farmer_sms(
                advisory, lga=row["lga"], state=state, lang=lang,
            )
            if len(body) > hi[0]:
                hi = (len(body), row["lga"], state)
    return hi


@pytest.mark.parametrize("lang", ["en", "ha"])
@pytest.mark.parametrize("advisory", _ADVISORIES)
def test_pilot_copy_fits_one_segment(lang: str, advisory: str) -> None:
    """Kebbi is the live pilot — Hausa-speaking, on SNS, real recipients.

    Every advisory must fit one segment at every Kebbi LGA. Worst measured
    case is 159 characters (ha/crop_stress at Birnin Kebbi): one to spare, so
    a regression here is real and not rounding.
    """
    chars, lga, state = _worst(["kebbi"], lang, advisory)
    assert chars <= _GSM7_SINGLE_SEGMENT, (
        f"{lang}/{advisory} is {chars} chars at {lga}, {state} — two segments"
    )


@pytest.mark.parametrize("lang", ["en", "ha"])
@pytest.mark.parametrize("advisory", _ADVISORIES)
def test_copy_is_ascii_everywhere(lang: str, advisory: str) -> None:
    """One accented character drops the segment limit from 160 to 70."""
    body = render_farmer_sms(
        advisory, lga="Birnin Magaji-Kiyaw", state="Zamfara", lang=lang,
    )
    assert body.isascii(), f"{lang}/{advisory} contains non-GSM-7 characters"


def test_english_fits_one_segment_across_all_nigerian_tenants() -> None:
    data = _lga_data()
    ng = [t for t in data if t not in ("ghana", "senegal")]
    for advisory in _ADVISORIES:
        chars, lga, state = _worst(ng, "en", advisory)
        assert chars <= _GSM7_SINGLE_SEGMENT, (
            f"en/{advisory} is {chars} chars at {lga}, {state}"
        )


def test_hausa_overflow_outside_kebbi_matches_the_known_set() -> None:
    """Pins which Hausa advisories cost two segments beyond the pilot.

    Fails if a new one appears (regression) or a pinned one is fixed (update
    _KNOWN_OVERFLOW_OUTSIDE_KEBBI). Either way the change is deliberate.
    """
    data = _lga_data()
    ng = [t for t in data if t not in ("ghana", "senegal")]
    actual = {
        ("ha", advisory)
        for advisory in _ADVISORIES
        if _worst(ng, "ha", advisory)[0] > _GSM7_SINGLE_SEGMENT
    }
    assert actual == _KNOWN_OVERFLOW_OUTSIDE_KEBBI
