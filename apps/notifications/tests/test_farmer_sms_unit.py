"""Farmer advisories must fit one SMS, stay in the cheap encoding, and never
claim to predict.

Three properties are pinned because each has a concrete cost:

* Over 160 GSM-7 characters the message splits and costs twice. The SMS budget
  is capped at $1/month, so a second segment is not a rounding error.
* A single accented character (e, a, n with diacritics) drops the limit from
  160 to 70 and doubles the cost of every message using it.
* Forecast wording is the failure this platform keeps producing. The rainfall
  advisory fires on rain ALREADY MEASURED; the first Hausa draft read "ana
  tsammanin" (is expected), which promises a forecast we cannot make.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from services.messages import (
    FARMER_ADVISORIES,
    FARMER_WITHHELD,
    SMS_SINGLE_SEGMENT_CHARS,
    render_farmer_sms,
)

# GSM-7 basic set. Anything outside forces UCS-2 and a 70-char limit.
GSM7 = set(
    "@\u00a3$\u00a5\u00e8\u00e9\u00f9\u00ec\u00f2\u00c7\u00d8\u00f8\u00c5\u00e5"
    "_\u00c6\u00e6\u00df\u00c9 !\"#\u00a4%&'()*+,-./0123456789:;<=>?"
    "\u00a1ABCDEFGHIJKLMNOPQRSTUVWXYZ\u00c4\u00d6\u00d1\u00dc\u00a7\u00bf"
    "abcdefghijklmnopqrstuvwxyz\u00e4\u00f6\u00f1\u00fc\u00e0\n\r"
)

# Worst case actually in the data, not an invented long string.
_CENTROIDS = json.loads(
    (pathlib.Path(__file__).resolve().parents[2] / "api" / "data"
     / "lga_centroids.json").read_text(encoding="utf-8")
)
LONGEST_LGA = max((g["lga"] for g in _CENTROIDS["kebbi"]), key=len)
LONGEST_STATE = "Federal Capital Territory"

CASES = [(lang, adv) for lang, pack in FARMER_ADVISORIES.items() for adv in pack]


@pytest.mark.parametrize("lang,advisory", CASES)
def test_fits_one_segment_for_the_longest_real_lga(lang: str, advisory: str):
    body = render_farmer_sms(advisory, lga=LONGEST_LGA, state="Kebbi", lang=lang)

    assert len(body) <= SMS_SINGLE_SEGMENT_CHARS, (
        f"{lang}/{advisory} is {len(body)} chars with LGA '{LONGEST_LGA}' — "
        f"splits into two segments and costs twice"
    )


@pytest.mark.parametrize("lang,advisory", CASES)
def test_stays_in_the_cheap_encoding(lang: str, advisory: str):
    body = render_farmer_sms(advisory, lga=LONGEST_LGA, state="Kebbi", lang=lang)
    outside = sorted({c for c in body if c not in GSM7})

    assert not outside, (
        f"{lang}/{advisory} contains {outside} — outside GSM-7, which drops the "
        f"limit to 70 characters and doubles the cost"
    )


@pytest.mark.parametrize("lang,advisory", CASES)
def test_every_message_carries_an_opt_out(lang: str, advisory: str):
    body = render_farmer_sms(advisory, lga="Argungu", state="Kebbi", lang=lang)

    assert "STOP" in body


def test_rainfall_states_an_observation_not_a_forecast():
    """We measure rain that has fallen. Nothing in the platform forecasts."""
    en = render_farmer_sms("rainfall", lga="Argungu", state="Kebbi", lang="en")
    ha = render_farmer_sms("rainfall", lga="Argungu", state="Kebbi", lang="ha")

    assert "recorded" in en
    for forecast_word in ("expected", "forecast", "will ", "coming"):
        assert forecast_word not in en.lower()
    # "ana tsammanin" = "is expected" — the wording of the first Hausa draft.
    assert "tsammanin" not in ha, "Hausa rainfall advisory must not forecast"


@pytest.mark.parametrize("withheld", FARMER_WITHHELD)
def test_withheld_advisories_refuse_to_render(withheld: str):
    """drought / flood / conflict are unvalidated. A caller passing the wrong
    string must get an error, not a message to a farmer."""
    with pytest.raises(ValueError, match="withheld"):
        render_farmer_sms(withheld, lga="Argungu", state="Kebbi")


def test_unknown_language_falls_back_to_english_rather_than_failing():
    body = render_farmer_sms("fire", lga="Argungu", state="Kebbi", lang="zz")

    assert "EconomicBridge" in body and "STOP" in body
