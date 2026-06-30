# EconomicBridge — Platform Briefing for the Director-General, NASRDA

**AI & Satellite Intelligence for Agriculture, Food Security & Aid Delivery**
Operated by **Bizra Farms Integrated Nigeria Ltd**

---

## 1. What it is — in one line

A multi-tenant satellite-intelligence platform covering **52 West African administrative units** (36 Nigerian states + FCT + 15 ECOWAS countries; 10 live pilots today), turning **live NASA + Copernicus satellite feeds** into actionable, **per-LGA** intelligence across seven modules — with a full **provenance trail** on every layer.

**Pilots live now:** Kebbi · Benue · Plateau · Kaduna · Niger · Zamfara · Nasarawa · FCT · Ghana · Senegal.

---

## 2. The core differentiator — multi-sensor satellite fusion

No single satellite tells the whole story. EconomicBridge **fuses four complementary sensors**, each covering the others' blind spots:

| Sensor | What it sees | Covers the gap of |
|---|---|---|
| **Sentinel-2 (optical, NDVI)** | vegetation health / loss | (blind at night + under cloud) |
| **Sentinel-1 (radar, SAR)** | land-surface change, all-weather, day & night | optical's cloud/night blindness |
| **NASA FIRMS (thermal)** | active fires / burning | slow-onset change |
| **VIIRS Black Marble (night-lights)** | new human activity, every night, year-round | seasonal blind spots of the above |

### Satellite constellation — revisit, resolution & role

| Satellite / product | Sensor | Resolution | Revisit | Swath | Data latency | Provider |
|---|---|---|---|---|---|---|
| **Sentinel-2 (MSI)** | Optical, 13 bands | **10 m** (NDVI bands) | **~5 days** | 290 km | hours – 2 days | ESA / Copernicus |
| **Sentinel-1 (SAR)** | C-band radar | **~10 m** (IW GRD) | **~6 days** | 250 km | hours – 1 day | ESA / Copernicus |
| **NASA FIRMS** | VIIRS / MODIS thermal | 375 m (VIIRS) | **multiple / day** | — | **~3 h** (near-real-time) | NASA LANCE/EOSDIS |
| **VIIRS Black Marble** (VNP46A2) | Day/Night Band | ~500 m | **nightly (daily)** | — | ~1 day – 1 week | NASA / LAADS DAAC |
| **WorldPop** | Modelled population grid | ~100 m | annual | — | — | WorldPop (CC-BY) |

*Notes:* Sentinel revisit reflects the two-satellite constellation (S2A/S2B; S1A/S1C). SAR is all-weather, day & night (cloud-penetrating); the optical NDVI is masked per-pixel for cloud. FIRMS and Black Marble are the high-cadence layers that keep the platform alert between Sentinel passes. Higher-resolution imagery (e.g. NASRDA **NigeriaSat / NCRS**) would sharpen the per-LGA indicators to sub-field scale on top of this open base.

**How the fusion works (per location, not per state):**

1. **Per-LGA evaluation** — every Local Government Area is assessed from *its own* satellite time-series, not a single state-wide average that washes out local events.
2. **Revisit-matched refresh** — each LGA is re-scanned on the satellite's natural ~6-day revisit, so coverage is always fresh without wasting compute.
3. **Corroboration scoring** — a *single* signal raises a cautious watch; *corroborating* signals (e.g. vegetation loss **and** radar disturbance **and** a new night-light) escalate confidence to high/critical. This is what separates a real event from sensor noise.
4. **Honest provenance** — every output is tagged with its sensors, acquisition source, and a *model-derived vs measured* flag. Nothing is fabricated.

> The result: a system that stays alert **year-round** — radar works through the wet season, night-lights flag new activity in any season, and fire/optical add corroboration when present.

---

## 3. The seven modules — how each works

### Module 03 — Farmland Protection (flagship)
- **Detects:** encroachment & land-surface disturbance (grazing incursion, clearing, new camps/mining) as a 24–72h conflict-risk indicator.
- **Fuses:** Sentinel-1 SAR + Sentinel-2 NDVI + NASA FIRMS + **VIIRS new-light**.
- **New amendment:** rebuilt from one state-wide alert to **full per-LGA coverage across all 10 states**, refreshing daily; a **year-round "new light in dark farmland"** signal now flags fresh human activity even when vegetation and radar are quiet.

### Module 04 — CropGuard
- **Detects:** crop/vegetation health (satellite) + crop disease (AI).
- **Fuses:** Sentinel-2 NDVI + Sentinel-1 SAR **+ a trained ResNet-50** that diagnoses disease from a single leaf photo (87% validation accuracy).
- **New amendment:** **statewide per-LGA crop health** — *every LGA* now carries a live Sentinel-2 NDVI health reading (healthy → moderate → stressed → poor), so CropGuard covers the whole state, not only photo-sampled points. Plus field-record keeping (every Farm Check + leaf diagnosis saved and recallable by state/LGA/crop).
- **The honest split:** satellite tells you **where** crops are stressed (per-LGA); a leaf photo tells you **which** disease (point-level) — a physical limit of remote sensing, and a credible one.

### Module 05 — ShockGuard
- **Detects:** floods (sharp radar drop = standing water) and droughts (sharp NDVI drop).
- **Fuses:** Sentinel-1 SAR + Sentinel-2 NDVI, **per-LGA**.
- **New amendment:** rebuilt to **per-LGA scanning of every LGA**; correctly shows **"all-clear, monitoring live"** when there are no shocks (it is early wet season — vegetation greening, no flood signatures), and lights up the affected LGAs the moment a real shock appears. Historical examples are clearly labelled.
- **Coverage:** all three satellite modules now reach every LGA — Farmland (per-LGA encroachment), CropGuard (per-LGA health), ShockGuard (per-LGA monitoring).

### Module 01 — Economic Visibility (Poverty mapping)
- **Detects:** under-electrified / under-served settlements.
- **Fuses:** **VIIRS Black Marble** night-light radiance + WorldPop population.
- **New amendment:** now reads **true per-pixel night-light radiance** from NASA granules (validated live — capitals bright, rural dark), replacing an earlier modelled proxy.

### Module 06 — Economic Mobility · Module 07 — SkillsBridge · Module 02 — Aid Coordination
- **Mobility:** World Bank income/employment indicators + Nigeria NLSS calibration.
- **Skills:** UNICEF GIGA real school access & connectivity.
- **Aid:** OCHA HDX humanitarian operational-presence coverage.

---

## 4. Provenance & licensing — "is it real, and can we commercialise it?"

**Yes on both.** The platform carries an open, in-product **Data Sources & Provenance** screen showing, per layer: the satellite + product, provider, licence, the exact attribution, live-vs-modelled status, and refresh cadence.

| Source | Commercial use | Obligation |
|---|---|---|
| **Copernicus / Sentinel-1 & 2 (ESA/EU)** | **Allowed** (free, full & open policy) | Attribution: *"Contains modified Copernicus Sentinel data [year]"* |
| **NASA — FIRMS, VIIRS Black Marble, MODIS** | **Allowed** (US public domain) | Cite source (e.g. *NASA Black Marble VNP46A2, LAADS DAAC*) |
| **WorldPop / World Bank** | **Allowed** (CC-BY 4.0) | Attribution |

> **Compute:** live Sentinel feeds draw on the Copernicus free "General" allowance (30,000 Processing Units/month); per-LGA coverage is revisit-matched to stay well inside it.

---

## 5. Why it is credible to a satellite agency

- **Genuine data only** — every satellite layer is read live from public NASA + Copernicus sources. No simulated or placeholder values on the map.
- **Per-LGA, not per-state** — local resolution, real coordinates, real place names.
- **Honest when quiet** — a disaster module that shows "all-clear" when there are no disasters is *more* credible than one that always shows alerts.
- **Auditable** — the provenance screen is the single place that answers "where is this from?"
- **Production-hardened** — automatic rate-limit handling, daily self-refreshing feeds, and a deploy + migration pipeline already proven on AWS.

---

## 6. Where NASRDA fits

- **Higher-resolution imagery (NigeriaSat / NCRS):** would sharpen our ROI/LGA indicators to **sub-field** resolution — the natural next layer on top of the open Sentinel/VIIRS base.
- **ASEICC demonstration platform:** ready to showcase the live system.
- **Joint validation:** ground-truth campaigns to calibrate the encroachment + crop-stress models against field reality.

---

*EconomicBridge · Bizra Farms Integrated Nigeria Ltd · 2026*
