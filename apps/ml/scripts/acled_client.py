"""ACLED client — real labelled conflict incidents for training (offline).

ACLED (Armed Conflict Location & Event Data, acleddata.com) is the standard
open conflict dataset: geocoded, dated incidents with event type + fatalities.
We use it to replace the conflict predictor's *synthetic* training labels with
real Nigerian incidents.

Auth: free registration → an API key + the registered email. This is an
OFFLINE training-time client (not the running service), so it reads
ACLED_API_KEY + ACLED_EMAIL straight from the environment — never hardcode.

    https://acleddata.com/  → Access → Register → API key
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

ACLED_BASE_URL = "https://api.acleddata.com/acled/read"


@dataclass(frozen=True, slots=True)
class AcledEvent:
    """One geocoded conflict incident."""

    event_date: str
    latitude: float
    longitude: float
    event_type: str
    sub_event_type: str
    fatalities: int
    admin1: str
    admin2: str


class AcledError(RuntimeError):
    """Non-200 or malformed ACLED response."""


class AcledClient:
    def __init__(self, *, http: httpx.Client | None = None) -> None:
        self._key = os.environ.get("ACLED_API_KEY", "")
        self._email = os.environ.get("ACLED_EMAIL", "")
        self._http = http

    @property
    def configured(self) -> bool:
        return bool(self._key and self._email)

    def fetch_events(
        self, *, country: str = "Nigeria",
        start: str = "2018-01-01", end: str = "2025-12-31",
        limit: int = 0,
    ) -> list[AcledEvent]:
        """Fetch incidents for a country + date range (limit=0 → all rows)."""
        if not self.configured:
            raise AcledError(
                "ACLED not configured — set ACLED_API_KEY + ACLED_EMAIL "
                "(register free at acleddata.com)."
            )
        params = {
            "key": self._key, "email": self._email, "country": country,
            "event_date": f"{start}|{end}", "event_date_where": "BETWEEN",
            "limit": str(limit),
        }
        client = self._http or httpx.Client(timeout=120.0)
        resp = client.get(ACLED_BASE_URL, params=params)
        if resp.status_code != 200:
            raise AcledError(f"ACLED {resp.status_code}: {resp.text[:200]}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise AcledError("ACLED: non-JSON body") from exc
        return [_parse_event(r) for r in (payload.get("data") or []) if _has_coords(r)]


def _has_coords(r: dict) -> bool:
    return bool(r.get("latitude") and r.get("longitude"))


def _parse_event(r: dict) -> AcledEvent:
    return AcledEvent(
        event_date=str(r.get("event_date", "")),
        latitude=float(r["latitude"]),
        longitude=float(r["longitude"]),
        event_type=str(r.get("event_type", "")),
        sub_event_type=str(r.get("sub_event_type", "")),
        fatalities=int(r.get("fatalities", 0) or 0),
        admin1=str(r.get("admin1", "")),
        admin2=str(r.get("admin2", "")),
    )
