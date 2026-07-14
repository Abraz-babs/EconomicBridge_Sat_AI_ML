# SMAP Soil Moisture — Feasibility Spike (verified 14 July 2026)

Tier-A spike for the Sep–Oct ShockGuard quality sprint. **Verdict: FEASIBLE**
— auth, product, and subsetting all proven with live requests. No product
code was written (spike only).

## Why soil moisture

Drought early warning for governments/aid runs on soil moisture, not
vegetation greenness: NDVI browns *weeks after* the moisture deficit starts
(lagging), soil moisture leads. A per-LGA "root-zone moisture percentile vs
its own multi-year climatology for this week of the year" is
seasonality-correct **by construction** — it can never call the dry season a
drought, because it compares against other dry seasons.

## Verified facts (live requests, 2026-07-14)

| Question | Answer |
|---|---|
| Product | **SPL4SMGP v008** — SMAP L4 Global 9 km EASE-Grid 2.0, surface + root-zone, 3-hourly, gap-free (model-assimilated), NSIDC DAAC |
| Record | 2015-03 → present (v008 current; granule for yesterday existed) |
| Granule size | ~143 MB, 8 granules/day → **full downloads are a non-starter; subsetting is mandatory** |
| Discovery | CMR keyless: `cmr.earthdata.nasa.gov/search/granules.json?short_name=SPL4SMGP&version=008` (collection `C3480440870-NSIDC_CPRD`) |
| Auth | **Our existing `EARTHDATA_TOKEN` works** on NSIDC cloud endpoints (same URS token the VIIRS/LAADS pipeline uses) — verified DMR 200 |
| Subsetting | **Cloud OPeNDAP DAP4 verified**: `opendap.earthdata.nasa.gov/collections/C3480440870-NSIDC_CPRD/granules/<GranuleUR>` + `.dap.nc4?dap4.ce=/Geophysical_Data/sm_rootzone[rows][cols]` → 11×21-cell slice returned as **16 KB netCDF** (HTTP 200) |
| Variables | `sm_rootzone` (m³/m³), `sm_surface`, **`sm_rootzone_wetness` (0–1, % of saturation — ideal for percentile messaging)**, `cell_lat`/`cell_lon` (exact EASE-2 geolocation) |

Gotcha: the OPeNDAP granule URL uses the CMR **GranuleUR verbatim**, which
carries an odd suffix (e.g. `SMAP_L4_SM_gph_...__001.h5_u9loH5HD`) — build
the URL from the CMR `links[rel~opendap].href`, never by reconstructing the
filename (a hand-built URL 404s).

## Design options for Tier B (decide in September)

1. **OPeNDAP daily sampling** — one 12:00 granule/day subset over all pilots'
   bbox: ~3.6 k one-time requests for a 10-year climatology (16 KB each,
   ≈60 MB total), then 1 request/day ongoing. Simple, matches our ingestion
   idioms (httpx + token), no new dependencies (parse netCDF4/HDF5 with h5py
   or netCDF4 — check what the ingestion image already ships).
2. **AppEEARS area extracts** — async job API (`appeears.earthdatacloud.nasa.gov`),
   same URS token; one job can return a multi-year area series. Fewer
   requests, but adds an async job-polling integration. Evaluate first — it
   may beat option 1 outright.
3. Weekly climatology sampling (52 × 10 subsets) if daily proves heavy.

Output shape (Tier B): per-LGA weekly `sm_rootzone_wetness` percentile vs
2015–2025 same-week climatology → ShockGuard drought becomes a leading
indicator; antecedent saturation feeds flood context; agency digests gain
"soil moisture in the Nth percentile for this week of the year".

## What was deliberately NOT done (Tier-A discipline)

No product code, no schema, no detector change, no new secrets. The live
platform is untouched by this spike.
