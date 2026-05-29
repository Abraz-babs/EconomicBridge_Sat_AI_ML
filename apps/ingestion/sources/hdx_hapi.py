"""HDX HAPI (Humanitarian API) client — Module 02 (Aid Coordination).

HAPI is the curated, standardised humanitarian API on top of HDX. It is
keyless: the only thing it asks for is an "app identifier" for attribution,
which is just base64("<app>:<email>") — not a credential. We derive it from
config so no token is stored.

This client reads the `operational-presence` dataset ("who does what where"):
which humanitarian organisations operate in which admin-2 area (≈ LGA) and in
which sector. The aid ingest aggregates that into per-LGA agency coverage
tagged source='hapi_v1', so the dashboard shows real coordination data
alongside the seed baseline.

Coverage is real and therefore uneven — HAPI carries the states where
humanitarian partners actually operate (concentrated in NE Nigeria), so some
pilot LGAs have rich data and others none. That's the honest picture.
"""
from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass

import httpx

from config import get_settings

log = logging.getLogger(__name__)


_PAGE_SIZE = 1000        # HAPI default; max 10000
_MAX_PAGES = 25          # safety cap (25k rows) so a runaway never hangs ingest


@dataclass(frozen=True, slots=True)
class OrgPresence:
    """One humanitarian org operating in one admin-2 area."""

    admin1_name: str
    admin2_name: str
    admin2_code: str
    org_name: str
    org_acronym: str
    sector_name: str
    reference_period_end: str | None


class HapiError(RuntimeError):
    """Non-200 or malformed body from HAPI."""


def slugify(text: str, *, max_len: int = 40) -> str:
    """Lower-kebab slug capped at max_len (aid_agencies.slug is VARCHAR(40))."""
    s = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return s[:max_len].strip("-") or "unknown"


class HapiClient:
    """Async client for the keyless HDX HAPI operational-presence endpoint."""

    def __init__(self, *, http: httpx.AsyncClient | None = None) -> None:
        self._settings = get_settings()
        self._http = http

    @property
    def configured(self) -> bool:
        """Keyless — always configured."""
        return True

    def _app_identifier(self) -> str:
        raw = f"{self._settings.hdx_app_name}:{self._settings.hdx_app_email}"
        return base64.b64encode(raw.encode()).decode()

    async def fetch_operational_presence(
        self,
        *,
        location_code: str,
        admin1_name: str | None = None,
    ) -> list[OrgPresence]:
        """Operational-presence rows for a country, optionally one admin-1.

        admin1_name filters client-side (HAPI returns the admin-1 label on
        every row), so a Nigerian state tenant gets only its own LGAs while a
        country tenant (Ghana/Senegal) gets all admin-2 areas.
        """
        url = f"{self._settings.hdx_hapi_base_url}/coordination-context/operational-presence"
        base_params = {
            "location_code": location_code,
            "admin_level": "2",
            "output_format": "json",
            "app_identifier": self._app_identifier(),
            "limit": str(_PAGE_SIZE),
        }
        rows: list[OrgPresence] = []
        async with self._http_ctx() as client:
            for page in range(_MAX_PAGES):
                params = {**base_params, "offset": str(page * _PAGE_SIZE)}
                resp = await client.get(
                    url, params=params,
                    headers={"Accept": "application/json"},
                    timeout=60.0, follow_redirects=True,
                )
                if resp.status_code != 200:
                    raise HapiError(
                        f"HAPI operational-presence {resp.status_code}: {resp.text[:200]}"
                    )
                try:
                    payload = resp.json()
                except ValueError as exc:
                    raise HapiError(f"HAPI: non-JSON body: {resp.text[:200]}") from exc
                batch = payload.get("data") if isinstance(payload, dict) else payload
                if not isinstance(batch, list) or not batch:
                    break
                rows.extend(_parse_rows(batch, admin1_name))
                if len(batch) < _PAGE_SIZE:
                    break
        return rows

    def _http_ctx(self) -> "httpx.AsyncClient | _Borrowed":
        if self._http is not None:
            return _Borrowed(self._http)
        return httpx.AsyncClient()


def _parse_rows(batch: list, admin1_name: str | None) -> list[OrgPresence]:
    """Filter a HAPI page to valid rows for the requested admin-1 (if any)."""
    out: list[OrgPresence] = []
    for r in batch:
        if not isinstance(r, dict):
            continue
        a1 = r.get("admin1_name") or ""
        a2 = r.get("admin2_name") or ""
        org = r.get("org_name") or r.get("org_acronym") or ""
        if not a2 or not org:
            continue
        if admin1_name is not None and a1.strip().lower() != admin1_name.strip().lower():
            continue
        out.append(OrgPresence(
            admin1_name=a1,
            admin2_name=a2,
            admin2_code=r.get("admin2_code") or "",
            org_name=org,
            org_acronym=r.get("org_acronym") or "",
            sector_name=r.get("sector_name") or "unknown",
            reference_period_end=r.get("reference_period_end"),
        ))
    return out


class _Borrowed:
    """Async-context wrapper that does NOT close an injected client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, *_exc: object) -> None:
        return None
