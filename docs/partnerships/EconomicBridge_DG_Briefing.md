# EconomicBridge — Platform Briefing for the Director-General, NASRDA

**AI & Satellite Intelligence for Agriculture, Food Security & Aid Delivery**
Operated by **Bizra Farms Integrated Nigeria Limited (RC 1929412)**

---

## 1. What it is — in one line

A multi-tenant satellite-intelligence platform that turns **open NASA and Copernicus satellite data** into farmland and early-warning intelligence for Nigerian states — reading **every pixel of every pilot Local Government Area**, reporting each change **at its own coordinates**, and stating a **measured accuracy** rather than an asserted one.

**Where it runs today:** eight Nigerian pilot territories — **Kebbi · Zamfara · Kaduna · Niger · Plateau · Nasarawa · Benue · FCT** — **142 LGAs** scanned pixel by pixel. Boundary data for **447 LGAs** is held across Nigeria, Ghana and Senegal; the Ghana and Senegal tenants are configured and held, ready to enable.

---

## 2. What changed this season — and why it matters to a satellite agency

We audited our own "per-LGA" monitoring against the real LGA boundaries and found it was measuring **one 3 × 3 km box at each LGA's centre** — **4,023 km² of the 715,731 km²** the pilot LGAs cover, **0.56% of the land**. Every alert landed on the same centre point, so the same place surfaced pass after pass while the rest of the LGA was never looked at.

Enlarging the box could not fix it: the metered Statistical API returns one average per box, so a 50-hectare clearing disappears into a 1,200 km² mean, and whole-LGA coverage by that route would have cost roughly **178 times** the processing budget.

So we rebuilt it on the **open Sentinel archive** (STAC catalogue, cloud-optimised GeoTIFFs). The platform now reads every pixel of all 142 pilot LGAs at 30 m, on a fixed UTM grid per LGA, with no processing-unit metering.

| This season, 2026 | |
|---|---|
| LGAs scanned, every pixel | **142** across 8 territories |
| Farmland (cropland + rangeland) measured as greening in the rains | **18.3 million hectares** |
| All land greening, including tree canopy and built-up land | 23.9 million hectares |
| Individual land changes located, on farmland only | **62**, at **62 distinct coordinates** |
| Measured precision, high-confidence class | **64%**, 95% interval 45–80% |
| Processing units consumed by the whole-LGA scan | **none** |

---

## 3. The satellite base

| Satellite / product | Sensor | Resolution | Revisit | Role in the platform | Provider |
|---|---|---|---|---|---|
| **Sentinel-2 (MSI)** | Optical, 13 bands | **10 m** | **~5 days** | Peak-season greenness, land change, crop health | ESA / Copernicus |
| **Sentinel-1 (SAR)** | C-band radar | **~10 m** | **~6 days** | All-weather land-surface signal | ESA / Copernicus |
| **GPM IMERG** | Multi-satellite rainfall | ~10 km | **half-hourly** | Rainfall advisories, storm reconstruction | NASA |
| **NASA FIRMS** | VIIRS / MODIS thermal | 375 m | multiple per day | Active fire | NASA LANCE |
| **VIIRS Black Marble** (VNP46A2) | Day/Night Band | ~500 m | nightly | Settlement activity, electrification | NASA LAADS |
| **Esri / Impact Observatory** | Annual land cover, 9 classes | 10 m | annual | What kind of land changed | Esri / IO |

*Honest limit:* optical imagery cannot see through cloud. In the 2025 rains the southern pilots were so persistently clouded that a year-on-year change figure cannot be established for Benue — **all 23 of its LGAs** — even though **97% of Benue's land** was seen at least once for this season's area measure. The platform reports that gap rather than filling it. Radar, and NASRDA's own data, are how it closes (section 6).

---

## 4. The modules — what each does, and what it has been measured to do

### Farmland Protection (flagship)
- **What it does:** compares **peak rainy-season greenness across three consecutive seasons** for every pixel of every pilot LGA. Ground that greened in 2024 and 2025 and stayed bare through the 2026 rains is flagged — crops green again, burn scars regrow, floods recede, but a cleared or built surface does not.
- **Farmland only:** each detection is classified against annual land cover, so **tree canopy, built-up land and water are excluded**. Of the 62 detections now live, **55 sit on rangeland, 7 on cropland, and none on trees or buildings**.
- **Measured, not asserted:** 65 detections were drawn at random, stratified by class, and checked by eye against before-and-after Sentinel-2 imagery. The high-confidence class scored **64%**; a looser class scored **2 real detections in 55 random points** across two samples and is therefore **not shipped**.
- **Farmland measure:** every LGA also reports the hectares that reached full greenness this season, split by land-cover class. This season that is **18.3 million hectares of cropland and rangeland** across the eight territories, out of 23.9 million hectares greening in all; tree canopy (2.5 million) and built-up land (0.3 million) are counted separately and excluded. **Abuja**, which previously could not be assessed at all, reports **433,000 hectares of farmland**. The land-cover map is Esri's 2023 edition, the latest published. It under-maps smallholder farming as rangeland, so cropland alone is a floor on farmland and the two together a ceiling.
- **Known and unresolved:** sand-bed river channels whose bars shift each year, and one reservoir drawdown in Plateau, still generate false detections. Both are recorded.

### ShockGuard — storms and extreme rainfall
- **What it does:** rebuilds storms from **half-hourly NASA GPM IMERG** rainfall across all 447 LGAs, filed by the day the rain actually fell, with severity expressed relative to each LGA's own rainfall history.
- **Honest scope:** it reports **storms and extreme rainfall, not floods**. Flood detection from radar was backtested against the 2024 Kebbi floods and did not detect them; we do not claim it.

### Rainfall advisories to farmers (live)
- Daily per-LGA rainfall thresholds from each LGA's own history; where exceeded, an advisory is **dispatched automatically by SMS to farmer cooperative leaders in Kebbi**, with no human in the loop, through a registered sender ID. Operating since August 2026.

### CropGuard
- **Satellite:** per-LGA vegetation health from Sentinel-2.
- **Leaf diagnosis:** a trained 12-class ResNet-50 reaches **87% on held-out laboratory images**. It has **not yet been validated on field photographs** and should be treated as a field-officer aid, not a diagnosis. Field-condition ground truth is one of the things a NASRDA partnership would provide.

### Economic Visibility, Aid Coordination, Economic Mobility, SkillsBridge
- **Economic Visibility:** night light (NASA VIIRS Black Marble) and population (Meta & CIESIN HRSL) measured at all **76,995 named villages** in the eight pilots: **84% show no light at night — about 25.6 million people, 5 million of them under five.** It measures light visible from space, not income; it tells a state where to look first.
- **Aid Coordination:** connected to OCHA HDX operational-presence data, which today covers only north-east Nigeria (Borno, Yobe, Adamawa), so it holds no records for the pilot states yet.
- **Mobility:** World Bank income and employment indicators, Nigeria NLSS calibration.
- **SkillsBridge:** UNICEF GIGA school access and connectivity.

---

## 5. Provenance and licensing — "is it real, and can it be commercialised?"

Every layer carries its satellite and product, provider, licence, attribution, and whether it is measured or modelled.

| Source | Commercial use | Obligation |
|---|---|---|
| **Copernicus Sentinel-1 & 2 (ESA/EU)** | Allowed — free, full and open | *"Contains modified Copernicus Sentinel data [year]"* |
| **NASA — FIRMS, VIIRS Black Marble, GPM IMERG** | Allowed — US public domain | Cite the product |
| **GRID3 LGA boundaries & settlement names, Meta & CIESIN HRSL population, WorldPop, World Bank** | Allowed — CC BY 4.0 | Attribution |
| **Esri / Impact Observatory land cover** | Allowed — CC BY 4.0 | Attribution |

**Audit trail:** every ingestion run is recorded, success or failure — **4,425 runs** to date across eight feeds — and a watchdog checks staleness daily.

---

## 6. Where NASRDA fits — a specific gap, not a general wish

Our own measurement shows exactly where the open data runs out:

- **The cloudy south.** Optical imagery cannot establish a change baseline for Benue, and is thin across Nasarawa, Plateau and parts of Niger, during the rains. **Radar and NASRDA's own archives** are the direct remedy.
- **Field-level validation.** Our precision figures are measured by eye against satellite imagery. **NASRDA ground-truth** would turn that into validation against the ground itself — for the land-change detector and for crop-disease diagnosis under field conditions.
- **Higher resolution.** **NigeriaSat / NCRS** imagery would sharpen whole-LGA change detection from 30 m to sub-field scale on the same pipeline, which ingests any standard STAC / COG source.

**The proposed first step:** a single-state data pilot, measured against the same random-sample standard used in this briefing.

---

*EconomicBridge · Bizra Farms Integrated Nigeria Limited · RC 1929412 · economicbridge.org · bizra@economicbridge.org · figures as of 23 September 2026*
