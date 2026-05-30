"""Tests for the ML-training prep (U-Net flood + ACLED conflict).

Covers the surfaces that don't need torch/GPU/ACLED: the FloodDetector stub
contract, ACLED response parsing (mocked HTTP), and the conflict dataset
builder. The actual GPU training + live ACLED fetch run offline.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from models.flood_detector import FloodDetector, MODEL_NAME  # noqa: E402
from scripts.acled_client import AcledClient, AcledError, _parse_event  # noqa: E402
from scripts.train_conflict_real import (  # noqa: E402
    FEATURE_ORDER,
    _historical_density,
    build_dataset,
    _synthetic_provider,
)
from scripts.acled_client import AcledEvent  # noqa: E402


# ─── FloodDetector stub contract ───────────────────────────────────────────


def test_flood_detector_untrained_is_stub(tmp_path):
    fd = FloodDetector(artifact_dir=tmp_path)  # empty dir → no artifact
    assert fd.trained is False
    with pytest.raises(NotImplementedError):
        fd.predict_mask(None)


def test_flood_model_name():
    assert MODEL_NAME == "flood_detector"


# ─── ACLED client parsing ──────────────────────────────────────────────────


def test_acled_not_configured_raises(monkeypatch):
    monkeypatch.delenv("ACLED_API_KEY", raising=False)
    monkeypatch.delenv("ACLED_EMAIL", raising=False)
    with pytest.raises(AcledError):
        AcledClient().fetch_events()


def test_acled_parses_events(monkeypatch):
    monkeypatch.setenv("ACLED_API_KEY", "k")
    monkeypatch.setenv("ACLED_EMAIL", "x@y.z")
    body = {"status": 200, "data": [
        {"event_date": "2024-03-01", "latitude": "9.1", "longitude": "8.2",
         "event_type": "Violence against civilians", "sub_event_type": "Attack",
         "fatalities": "4", "admin1": "Benue", "admin2": "Guma"},
        {"event_date": "2024-03-02", "latitude": "", "longitude": "8.3"},  # no coords → dropped
    ]}
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=json.dumps(body).encode()))
    client = AcledClient(http=httpx.Client(transport=transport))
    events = client.fetch_events(country="Nigeria")
    assert len(events) == 1
    assert events[0].fatalities == 4 and events[0].admin1 == "Benue"


def test_acled_non_200_raises(monkeypatch):
    monkeypatch.setenv("ACLED_API_KEY", "k")
    monkeypatch.setenv("ACLED_EMAIL", "x@y.z")
    transport = httpx.MockTransport(lambda req: httpx.Response(403, content=b"denied"))
    with pytest.raises(AcledError):
        AcledClient(http=httpx.Client(transport=transport)).fetch_events()


# ─── conflict dataset builder ──────────────────────────────────────────────


def test_historical_density_counts_prior_nearby():
    events = [
        AcledEvent("2024-01-01", 9.0, 8.0, "t", "s", 0, "a", "b"),
        AcledEvent("2024-02-01", 9.05, 8.05, "t", "s", 0, "a", "b"),
        AcledEvent("2024-03-01", 9.0, 8.0, "t", "s", 0, "a", "b"),
    ]
    # the 3rd event has 2 prior nearby incidents
    assert _historical_density(events[2], events) == 2


def test_build_dataset_shapes_and_labels():
    events = [AcledEvent("2024-01-01", 9.0 + i * 0.01, 8.0, "t", "s", 0, "a", "b") for i in range(20)]
    X, y = build_dataset(events, _synthetic_provider)
    assert X.shape[0] == y.shape[0] == 40          # 20 positives + 20 negatives
    assert X.shape[1] == len(FEATURE_ORDER) == 7
    assert set(y.tolist()) == {0, 1}
    assert y.sum() == 20
