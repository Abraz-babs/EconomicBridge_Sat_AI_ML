"""Hand-curated LGA / district centroids for all pilot tenants.

Single source of truth for `(tenant_id, lga)` → `(lon, lat)` lookups
shared by every Module 02 / 06 / 07 seed script. Previously each script
computed a synthetic 8-direction fan around the tenant centroid, which
could place rural LGAs across the state line into neighbours (e.g. an
FCT LGA spilling into southern Kaduna). Real centroids keep every row
inside its tenant's actual administrative boundary.

Coordinates were captured from LGA-headquarters town locations rather
than polygon centroids — accurate enough that reverse-geocoding the
result returns the correct state / region. Where the LGA name differs
from the headquarters town, the comment notes the HQ town used.

Add new tenants by extending the per-tenant dicts below. Tests in
`tests/test_lga_geo.py` (see `_tenant_bounds`) enforce that every
coordinate stays inside the tenant's bounding box.
"""
from __future__ import annotations

# Centroids stored as (lon, lat). Lookups via LGA_CENTROIDS[tenant][lga].

KEBBI: dict[str, tuple[float, float]] = {
    "Argungu":      (4.52, 12.74),
    "Birnin Kebbi": (4.20, 12.45),
    "Dandi":        (3.86, 12.64),   # HQ: Kamba
    "Gwandu":       (4.65, 12.50),
    "Jega":         (4.38, 12.22),
    "Yauri":        (4.78, 10.79),
    "Zuru":         (5.23, 11.43),
    "Bunza":        (4.02, 12.10),
}

BENUE: dict[str, tuple[float, float]] = {
    "Agatu":     (7.79, 7.55),   # HQ: Obagaji
    "Logo":      (8.94, 7.50),   # HQ: Ugba
    "Tarka":     (8.83, 7.51),   # HQ: Wannune
    "Guma":      (8.62, 7.86),   # HQ: Gbajimba
    "Vandeikya": (9.07, 6.79),
    "Otukpo":    (8.13, 7.19),
    "Apa":       (8.30, 7.51),   # HQ: Ugbokpo
    "Buruku":    (8.93, 7.43),
}

PLATEAU: dict[str, tuple[float, float]] = {
    "Bassa":     (8.74, 10.04),
    "Riyom":     (8.74,  9.62),
    "Bokkos":    (9.00,  9.30),
    "Jos North": (8.89,  9.93),
    "Pankshin":  (9.43,  9.32),
    "Wase":      (9.95,  9.10),
    "Shendam":   (9.53,  8.88),
    "Mangu":     (9.10,  9.51),
}

KADUNA: dict[str, tuple[float, float]] = {
    "Birnin Gwari": (6.78, 11.02),
    "Zangon Kataf": (8.13,  9.79),   # HQ: Zonkwa
    "Kafanchan":    (8.30,  9.59),   # Jema'a LGA HQ
    "Jaba":         (8.05,  9.55),   # HQ: Kwoi
    "Kaura":        (8.42,  9.62),
    "Chikun":       (7.40, 10.42),
    "Igabi":        (7.44, 10.74),
    "Sabon Gari":   (7.72, 11.10),   # near Zaria
}

NIGER: dict[str, tuple[float, float]] = {
    "Shiroro":   (6.84,  9.95),  # HQ: Kuta
    "Kontagora": (5.47, 10.41),
    "Mariga":    (6.27, 10.39),
    "Borgu":     (4.43, 10.41),  # HQ: New Bussa
    "Lapai":     (6.57,  9.04),
    "Agaie":     (6.32,  9.01),
    "Suleja":    (7.18,  9.18),
    "Bida":      (6.01,  9.08),
}

ZAMFARA: dict[str, tuple[float, float]] = {
    "Maru":           (6.41, 12.34),
    "Maradun":        (6.18, 12.41),
    "Anka":           (5.93, 12.11),
    "Bukkuyum":       (5.92, 12.10),
    "Gusau":          (6.66, 12.16),
    "Kaura Namoda":   (6.59, 12.59),
    "Tsafe":          (6.92, 11.95),
    "Talata Mafara":  (6.07, 12.57),
}

NASARAWA: dict[str, tuple[float, float]] = {
    "Akwanga": (8.41, 8.92),
    "Wamba":   (8.59, 8.94),
    "Doma":    (8.40, 8.39),
    "Karu":    (7.53, 9.00),
    "Keffi":   (7.87, 8.85),
    "Lafia":   (8.52, 8.49),
    "Awe":     (9.21, 8.13),
    "Kokona":  (7.84, 8.69),
}

FCT: dict[str, tuple[float, float]] = {
    # All six FCT Area Councils — coords kept inside FCT bounds
    # (FCT extends ~6.7–7.6°E, 8.4–9.4°N).
    "Abaji":       (6.94, 8.47),
    "Bwari":       (7.39, 9.27),
    "Gwagwalada":  (7.08, 8.94),
    "Kuje":        (7.23, 8.88),
    "Kwali":       (7.00, 8.86),
    "AMAC":        (7.48, 9.07),   # Abuja Municipal Area Council
}

GHANA: dict[str, tuple[float, float]] = {
    "Pusiga":         (-0.07, 11.07),  # Upper East
    "Garu-Tempane":   (-0.18, 10.78),  # Upper East
    "Bawku":          (-0.24, 11.06),  # Upper East
    "Tamale":         (-0.84,  9.40),  # Northern
    "Bolgatanga":     (-0.85, 10.79),  # Upper East capital
    "Wa":             (-2.51, 10.06),  # Upper West capital
    "Sunyani":        (-2.33,  7.34),  # Bono capital
    "Kumasi":         (-1.62,  6.69),  # Ashanti capital
}

SENEGAL: dict[str, tuple[float, float]] = {
    "Sédhiou":      (-15.56, 12.71),
    "Kolda":        (-14.95, 12.91),
    "Tambacounda":  (-13.67, 13.77),
    "Kédougou":     (-12.18, 12.55),
    "Matam":        (-13.26, 15.66),
    "Saint-Louis":  (-16.49, 16.03),
    "Diourbel":     (-16.23, 14.66),
    "Kaffrine":     (-15.55, 14.11),
}


# The 8-per-state hand-curated set, kept as an offline fallback only.
_CURATED_CENTROIDS: dict[str, dict[str, tuple[float, float]]] = {
    "kebbi":    KEBBI,
    "benue":    BENUE,
    "plateau":  PLATEAU,
    "kaduna":   KADUNA,
    "niger":    NIGER,
    "zamfara":  ZAMFARA,
    "nasarawa": NASARAWA,
    "fct":      FCT,
    "ghana":    GHANA,
    "senegal":  SENEGAL,
}


def _load_full_dataset() -> dict[str, dict[str, tuple[float, float]]]:
    """Load the FULL real admin-2 centroid set built by
    `apps/ingestion/scripts/build_lga_centroids.py` (geoBoundaries open data:
    every Nigerian LGA assigned to its pilot state by point-in-polygon, plus
    all Ghana/Senegal districts). Falls back to the 8-per-state curated set if
    the dataset file is absent so seeds never hard-fail offline.
    """
    import json
    from pathlib import Path

    # apps/api/services/lga_geo.py → repo .../apps/ → ingestion/data/...
    path = Path(__file__).resolve().parents[2] / "ingestion" / "data" / "lga_centroids.json"
    if not path.exists():
        return _CURATED_CENTROIDS
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, tuple[float, float]]] = {}
    for tenant, units in raw.items():
        out[tenant] = {u["lga"]: (u["lon"], u["lat"]) for u in units}
    # Keep any curated tenant the dataset somehow lacks.
    for tenant, fan in _CURATED_CENTROIDS.items():
        out.setdefault(tenant, fan)
    return out


# Primary lookup table — every real LGA/district per tenant.
LGA_CENTROIDS: dict[str, dict[str, tuple[float, float]]] = _load_full_dataset()


def all_lgas(tenant_id: str) -> list[str]:
    """Every LGA/district name for a tenant (sorted), from the full dataset."""
    return sorted(LGA_CENTROIDS.get(tenant_id, {}).keys())


def centroid_for(tenant_id: str, lga: str) -> tuple[float, float]:
    """Return `(lon, lat)` for the given LGA.

    Raises `KeyError` with a descriptive message if the tenant or LGA
    is unknown — better to fail loudly at seed time than to silently
    drop a row into the wrong state.
    """
    try:
        return LGA_CENTROIDS[tenant_id][lga]
    except KeyError as e:
        raise KeyError(
            f"No centroid for ({tenant_id}, {lga}) in lga_centroids dataset."
        ) from e
