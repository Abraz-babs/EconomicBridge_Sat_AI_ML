"""WorldPop population grid catalog client.

WorldPop publishes 100 m gridded population estimates per country per year
under an open data license. We use the REST catalog at
worldpop.org/rest/data/{dataset}/{iso3} to look up the published layer
(year, resolution, download href) that covers a tenant ROI, then later
Phase B reads the raster off the open S3 bucket (s3://worldpop-data).

This client is the catalog/metadata layer only — anonymous, no auth.
We resolve tenant_id → ISO3 country code via a small lookup that mirrors
tenants.yaml. For Nigerian state tenants the country is NGA; for ECOWAS
country tenants it's the ISO3 of that country.

The processor downstream combines a WorldPop layer reference + a VIIRS
nightlight granule reference to write a poverty_villages row tagged
`source='worldpop_v1'` (or `viirs_v2'` if the dim-lights signal is the
primary driver for that settlement).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from config import get_settings

log = logging.getLogger(__name__)


# Tenant → ISO3 country code. Nigerian states all map to NGA; ECOWAS
# country tenants map to their own ISO3. Source of truth is tenants.yaml.
TENANT_TO_ISO3: dict[str, str] = {
    "kebbi": "NGA", "benue": "NGA", "plateau": "NGA", "kaduna": "NGA",
    "niger": "NGA", "zamfara": "NGA", "nasarawa": "NGA", "fct": "NGA",
    "ghana": "GHA", "senegal": "SEN",
}


@dataclass(frozen=True, slots=True)
class WorldPopLayer:
    """One published WorldPop dataset layer (country × year × resolution)."""

    dataset_id: int           # WorldPop's internal record id
    iso3: str                 # NGA, GHA, SEN, …
    year: int
    title: str
    resolution_m: int | None  # 100 m / 1 km / 30 arc-second
    download_url: str         # public S3 https URL
    file_size_bytes: int | None


class WorldPopError(RuntimeError):
    """Non-200, malformed body, or missing tenant-ISO3 mapping."""


class WorldPopClient:
    """Async REST client for the WorldPop catalog at worldpop.org/rest/data."""

    def __init__(self, *, http: httpx.AsyncClient | None = None) -> None:
        self._settings = get_settings()
        self._http = http

    @property
    def configured(self) -> bool:
        """Catalog is anonymous — always configured."""
        return True

    async def list_layers(
        self,
        *,
        iso3: str,
        year: int | None = None,
        dataset: str | None = None,
        max_results: int = 20,
    ) -> list[WorldPopLayer]:
        """List published layers for a country × year.

        Args:
            iso3: ISO 3166-1 alpha-3 country code (NGA, GHA, SEN, …).
            year: Calendar year (defaults to settings.worldpop_default_year).
            dataset: Product family ('pop' constrained, 'wpgp' unconstrained).
            max_results: cap on returned layers.

        Returns:
            List of WorldPopLayer, latest year first. Empty when the
            country/year combo has no published layer (legitimate — the
            processor falls back to seed_v1 in that case).
        """
        ds = dataset or self._settings.worldpop_default_dataset
        url = f"{self._settings.worldpop_rest_base_url}/{ds}/{iso3.upper()}"

        async with self._http_ctx() as client:
            resp = await client.get(
                url,
                headers={"Accept": "application/json"},
                timeout=30.0,
            )
        if resp.status_code == 404:
            return []
        if resp.status_code != 200:
            raise WorldPopError(
                f"WorldPop REST {resp.status_code}: {resp.text[:200]}"
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise WorldPopError(
                f"WorldPop REST: non-JSON body: {resp.text[:200]}"
            ) from exc

        rows = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            return []
        layers = [_parse_layer(r) for r in rows]
        layers = [layer for layer in layers if layer is not None]
        if year is not None:
            layers = [layer for layer in layers if layer.year == year]
        layers.sort(key=lambda x: x.year, reverse=True)
        return layers[:max_results]

    async def latest_layer_for_tenant(
        self,
        tenant_id: str,
        *,
        year: int | None = None,
    ) -> WorldPopLayer | None:
        """Resolve tenant → ISO3 → latest WorldPop layer.

        Returns None for unknown tenants OR when the catalog has no
        layer for that country/year — both are legitimate fallback cases.
        """
        iso3 = TENANT_TO_ISO3.get(tenant_id)
        if not iso3:
            log.warning("worldpop: no ISO3 mapping for tenant %s", tenant_id)
            return None
        layers = await self.list_layers(iso3=iso3, year=year)
        return layers[0] if layers else None

    def _http_ctx(self) -> httpx.AsyncClient | _Borrowed:
        if self._http is not None:
            return _Borrowed(self._http)
        return httpx.AsyncClient()


# ─── Parsers ──────────────────────────────────────────────────────────────


def _parse_layer(row: Any) -> WorldPopLayer | None:
    """Translate one WorldPop REST row into a WorldPopLayer."""
    if not isinstance(row, dict):
        return None
    try:
        dataset_id = int(row.get("id") or row.get("ID") or 0)
    except (TypeError, ValueError):
        return None
    if dataset_id == 0:
        return None
    iso3 = row.get("iso3") or row.get("country_iso") or row.get("alpha3")
    if not isinstance(iso3, str) or len(iso3) != 3:
        return None
    year_raw = row.get("popyear") or row.get("year")
    try:
        year = int(year_raw) if year_raw is not None else 0
    except (TypeError, ValueError):
        return None
    if year == 0:
        return None
    title = str(row.get("title") or row.get("name") or "")
    download_url = str(
        row.get("data_file")
        or row.get("download_url")
        or row.get("file")
        or ""
    )
    resolution_m = _resolution_metres(row.get("resolution"))
    size_raw = row.get("file_size") or row.get("size")
    try:
        size_bytes = int(size_raw) if size_raw is not None else None
    except (TypeError, ValueError):
        size_bytes = None

    return WorldPopLayer(
        dataset_id=dataset_id,
        iso3=iso3.upper(),
        year=year,
        title=title,
        resolution_m=resolution_m,
        download_url=download_url,
        file_size_bytes=size_bytes,
    )


def _resolution_metres(value: Any) -> int | None:
    """Normalise WorldPop's mixed-format resolution field to metres.

    Examples we see in the wild:
        "100m"   → 100
        "1km"    → 1000
        "30s"    → 1000  (30 arc-second ≈ 1 km at the equator)
        100      → 100
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip().lower()
    if s.endswith("km"):
        try:
            return int(float(s[:-2]) * 1000)
        except ValueError:
            return None
    if s.endswith("m"):
        try:
            return int(float(s[:-1]))
        except ValueError:
            return None
    if s.endswith("s"):
        return 1000   # 30s ~= 1 km — close enough for catalog gating
    try:
        return int(s)
    except ValueError:
        return None


# ─── HTTP context wrapper ─────────────────────────────────────────────────


class _Borrowed:
    """Async-context wrapper that does NOT close the injected client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, *_exc: object) -> None:
        return None
