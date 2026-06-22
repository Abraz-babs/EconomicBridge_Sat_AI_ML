# EconomicBridge — Technical Operator's Handbook

*A plain-English guide to how every component works, so you can explain any part
of the platform with confidence. Read Part 1 for the big picture, Part 2 for the
data inputs (satellites + APIs), Part 3 for the seven modules, Part 4 for how it
all runs, and Part 5 for quick answers to likely questions.*

---

## PART 1 — THE BIG PICTURE

**One sentence:** EconomicBridge collects live data from satellites and global
data providers, processes it with AI and statistics, stores it per-tenant, and
serves it as maps, alerts and reports — then pushes warnings to communities by SMS.

**The data journey (left to right):**

```
SATELLITES & APIs   ->   INGESTION   ->   DATABASE   ->   API   ->   DASHBOARD
(Copernicus, NASA,      (downloads,      (PostgreSQL   (serves    (maps, charts,
 World Bank, UNICEF,     processes,       schema-per-   clean      alerts) + SMS
 WorldPop, HDX, N2YO)    scores, tags)    tenant)       JSON)      to communities
```

**The five services (each a separate program, all on AWS):**

| Service | Job |
|---|---|
| **frontend** | The dashboard people see (Next.js web app + Mapbox maps) |
| **api** | Serves data to the dashboard, handles login, tenants, reports |
| **ingestion** | Pulls satellite/economic data on a schedule, processes it |
| **ml** | Runs the AI models (crop disease, conflict, anomalies) |
| **notifications** | Sends SMS alerts (multilingual), gated by data-protection rules |

**The golden rule — honest provenance:** every figure is tagged with where it
came from. Live satellite/measured data is labelled distinctly from *modelled*
baseline estimates. The dashboard never dresses up an estimate as a measurement.
This is a core trust feature, and a strong thing to emphasise to any technical
reviewer.

---

## PART 2 — THE INPUTS: HOW EACH SATELLITE / API WORKS

For each source: **what it is**, **what it measures**, **how we use it**, **freshness**.

### Copernicus Sentinel-1 — radar (SAR)
- **What:** A European Space Agency radar satellite. SAR = Synthetic Aperture Radar.
- **How radar works (the key point):** It sends its own microwave pulses down and
  measures what bounces back. Because it makes its own "light," it works **day or
  night and sees straight through cloud** — unlike a normal camera. Smooth water
  reflects the pulse away (looks dark/low return); rough ground and vegetation
  scatter it back (bright). That contrast is how we detect **standing flood water**
  and land-surface change.
- **We use it for:** ShockGuard flood detection, and Farmland Protection
  (land-surface change / encroachment signal).
- **Freshness:** ~weekly per area (revisit cycle); we pull it via Copernicus's
  Statistical API, which returns numbers (averages over an area) rather than raw
  image files — fast and light.

### Copernicus Sentinel-2 — optical / vegetation (NDVI)
- **What:** ESA optical satellite (a very sophisticated camera across many colour
  bands, including near-infrared).
- **What it measures — NDVI:** Healthy plants reflect a lot of near-infrared light
  and absorb red light. NDVI (Normalised Difference Vegetation Index) =
  (NIR − Red) / (NIR + Red). High NDVI = lush, healthy vegetation; falling NDVI =
  stress, disease, drought, or harvest.
- **We use it for:** CropGuard's satellite vegetation monitoring (crop health
  week by week, no photo needed) and ShockGuard drought signal.
- **Freshness:** ~weekly; also via the Statistical API (we get the NDVI value over
  each area, not raw pixels).

### NASA FIRMS — active fire (thermal)
- **What:** NASA's Fire Information for Resource Management System.
- **What it measures:** Satellites (MODIS, VIIRS) detect **thermal anomalies** —
  spots much hotter than their surroundings = active fires/bush burning.
- **We use it for:** Farmland Protection (fire near farmland is a conflict/loss
  signal) and as a hazard layer.
- **Freshness:** **Daily**, near-real-time (within hours of the satellite pass).

### VIIRS Black Marble — night-lights (poverty proxy)
- **What:** NASA's night-time lights product (collection VNP46A2), accessed with a
  NASA Earthdata token.
- **What it measures:** How brightly the Earth glows at night. **Lit areas =
  economic activity and electrification; dark-but-populated areas = poverty.**
- **We use it for:** Economic Visibility — scoring which settlements are poor and
  underserved (people present, little light).
- **Freshness:** Weekly in our scheduler (night-lights move slowly for this purpose).

### WorldPop — population grids
- **What:** Open gridded population estimates (~100 m squares), from the University
  of Southampton.
- **What it measures:** How many people live in each square of land.
- **We use it for:** Economic Visibility — turning "this settlement is dark" into
  "and ~X thousand people live there," so relief can be targeted by real need.
- **Freshness:** Weekly sampling. (We serve the raster from our own secure S3 copy
  because WorldPop's public server stopped supporting partial reads — a good
  example of engineering around an upstream problem.)

### N2YO — satellite pass tracking
- **What:** A live satellite-tracking service.
- **What it does for us:** Tells us **when a satellite will next fly over a given
  area**, so the ingestion service can request fresh imagery around that pass
  ("pass-driven refresh") instead of guessing.
- **Freshness:** Checked every 15 minutes.

### World Bank Indicators API — economics
- **What:** The World Bank's open data API (free, CC BY 4.0 — commercial use OK).
- **What it measures:** National economic indicators — GNI per capita, employment.
- **We use it for:** Mobility Compass — income and cost-of-living, anchored in USD
  and converted to each country's local currency.
- **Freshness:** Monthly.

### UNICEF GIGA — schools & connectivity
- **What:** UNICEF's global school-mapping initiative.
- **What it measures:** Locations of schools and their internet connectivity.
- **We use it for:** SkillsBridge — education access and connectivity targeting.
- **Freshness:** Monthly. (Real per-area school counts are live; fine-grained
  connectivity is partly modelled — labelled honestly.)

### HDX HAPI — humanitarian / aid presence
- **What:** The UN OCHA Humanitarian Data Exchange API (keyless, open).
- **What it measures:** "Who does what where" — which aid agencies operate in
  which areas (operational presence).
- **We use it for:** Aid Coordination — showing coverage and gaps.
- **Freshness:** Monthly. (Honest note: its operational-presence data covers
  north-east Nigeria; elsewhere our coverage view leans on operator CSV uploads.)

### The AI models (run by the ml service)
- **CropGuard ResNet-50:** A 50-layer convolutional neural network trained to
  recognise **12 crop-disease classes** from a leaf photo. We trained it to
  **87.2% validation accuracy**. It returns the top likely diseases with a
  confidence score, and a **Grad-CAM heatmap** showing *where on the leaf* it
  looked — so a human can sanity-check it. Low-confidence results are flagged for
  human review rather than asserted.
- **Conflict predictor (Random Forest):** Combines signals (fire, land change,
  proximity, history) to estimate the probability of farmer-herder / encroachment
  conflict in the next **24–72 hours**. Above a confidence threshold it raises an
  alert; below it, it logs for review.
- **Anomaly detectors (statistics):** For floods and drought we compare the recent
  satellite reading to a baseline and compute a **z-score** (how many standard
  deviations from normal). A big jump = an anomaly worth flagging. Simple, robust,
  and explainable.

---

## PART 3 — THE OUTPUTS: HOW EACH MODULE WORKS

For each module: **purpose · inputs · how it works · what you see · provenance.**

### 1. Economic Visibility (Poverty Mapping)
- **Purpose:** Find poor, underserved settlements that traditional census misses.
- **Inputs:** VIIRS night-lights + WorldPop population (+ DHS-style validation).
- **How:** Dark-but-populated settlements score as higher-poverty; population gives
  the scale of need.
- **You see:** A map of settlements coloured by poverty intensity, a vulnerability
  ranking, and counts (villages identified, population, households unreached).
- **Provenance:** Settlement layer is a modelled baseline (`seed`); population and
  night-lights enrich it live (`worldpop_cog_v1`, `viirs_v2`) → badge shows the blend.

### 2. Aid Coordination
- **Purpose:** Stop aid agencies duplicating effort and leaving gaps.
- **Inputs:** HDX HAPI operational presence + operator CSV uploads (WFP/UNHCR).
- **How:** Maps which agencies work where, against need, to surface gaps.
- **You see:** Coverage by area, agency lists, gap highlights.
- **Provenance:** `hapi_v1` where HDX covers; CSV-sourced elsewhere.

### 3. Farmland Protection
- **Purpose:** Warn of herder/cattle encroachment and farmer-herder conflict
  **before** it happens.
- **Inputs:** two live engines — (a) a **fire-cluster conflict pipeline** (NASA
  FIRMS heat clusters → Random-Forest conflict model), and (b) the **encroachment
  detector** that fuses **Sentinel-2 NDVI loss** (grazing/clearing) + **Sentinel-1
  SAR change** (land-surface disturbance, tracks, trampling) + **FIRMS fire**.
- **How — encroachment detector:** we cannot see individual cattle at 10 m, so we
  detect their *signatures*. Per tenant ROI we compare recent satellite readings
  to a baseline; a single notable signal raises a **medium watch**, and
  corroborating signals (loss + radar + fire) escalate to **high/critical**.
  Confidence is corroboration-weighted, so a lone wet-season radar change (often
  just soil moisture) never reads as critical. Runs daily for every tenant,
  year-round — independent of fire season.
- **You see:** pulsing alert halos, a conflict-risk timeline, each alert labelled
  with an LGA + the real trigger ("vegetation loss", "radar land-surface change",
  "N fires"), flagged for human review.
- **Provenance:** live encroachment alerts (model_name=`encroachment_detector_v1`)
  vs seed baseline are labelled — LIVE when present, MONITORING when the watch is
  on but nothing's active. These are ROI-level *risk indicators*, not confirmed
  incidents; higher-resolution / per-LGA data (NASRDA NCRS) would localize them
  from ROI to field scale.

### 4. CropGuard
- **Purpose:** Protect harvests from disease, and watch crop health from space.
- **Inputs:** (a) a leaf photo → ResNet-50; (b) Sentinel-2 NDVI; (c) market prices;
  (d) yield signals.
- **How:** Two complementary capabilities — **point diagnosis** (photograph one
  sick leaf, AI names the disease in seconds with a heatmap) and **continuous
  satellite vegetation monitoring** (NDVI over the whole area, no photo needed,
  flagging stress/anomalies early).
- **You see:** The TRAINED model badge, a diagnosis with confidence + Grad-CAM, an
  NDVI vegetation panel, crop prices, and a yield outlook.
- **Provenance:** Model badge reads TRAINED (real model serving everywhere); NDVI
  panel defaults to live Sentinel-2.

### 5. ShockGuard
- **Purpose:** Detect floods and drought early.
- **Inputs:** Sentinel-1 SAR (flood) + Sentinel-2 NDVI (drought) + z-score detectors.
- **How:** Flood = sudden rise in smooth-water radar signature; drought = NDVI
  falling well below the seasonal baseline. Both expressed as anomalies with
  confidence.
- **You see:** Flood/drought events on the map with severity (critical / watch).
- **Provenance:** Runs on live Copernicus data; modelled fallback labelled if a
  tenant lacks acquisitions.

### 6. Mobility Compass
- **Purpose:** Economic picture — income, cost of living, displacement capacity.
- **Inputs:** World Bank GNI/employment, USD-anchored, converted per local currency.
- **How:** National indicators disaggregated to per-LGA estimates; dual-currency
  (e.g. USD + Naira) so figures are locally legible.
- **You see:** Income and cost-of-living indicators across LGAs.
- **Provenance:** `worldbank_v1` (real) over the `seed` baseline.

### 7. SkillsBridge
- **Purpose:** Target education and connectivity investment.
- **Inputs:** UNICEF GIGA school locations + World Bank ICT.
- **How:** Per-area school density and access mapped to find under-served areas.
- **You see:** School access / connectivity indicators per LGA.
- **Provenance:** `giga_v1` (real school counts) over baseline.

---

## PART 4 — HOW IT ALL RUNS (OPERATIONS)

### The ingestion scheduler (9 self-running jobs)
The ingestion service runs jobs automatically on a clock (no one has to press a
button), and each can also be fired on demand from the Admin panel:

| Job | Cadence |
|---|---|
| Pass-driven imagery refresh (N2YO + Sentinel) | every 15 min |
| NASA FIRMS fire ingest | daily 06:00 UTC |
| Conflict prediction sweep | daily 06:30 UTC |
| Sentinel-1 SAR + Sentinel-2 NDVI observations | weekly (Sat) |
| WorldPop population sweep | weekly (Sun) |
| VIIRS night-lights + poverty ingest | weekly (Mon) |
| World Bank income (Mobility) | monthly (1st) |
| HDX aid coordination | monthly (1st) |
| UNICEF GIGA schools (Skills) | monthly (1st) |

### The database — schema-per-tenant isolation
Each tenant (state/agency) has its **own schema** inside PostgreSQL. A request for
Kebbi data physically cannot read Benue's. Regional partners (e.g. NEMA, ECOWAS)
get cross-tenant read access by role. This is the core of the security story.

### The cloud — AWS
Five containers run on **AWS ECS Fargate** behind one **load balancer** that routes
by path (`/api`, `/ingestion`, `/ml`, `/notifications`, and the dashboard at `/`).
Data in **RDS PostgreSQL**, caching in **ElastiCache Redis**, model weights and the
WorldPop raster in **S3**, all secrets in **AWS Secrets Manager** (never in code).
Everything is defined in **Terraform** and deployed via **GitHub Actions CI/CD**.

### Security & compliance
- Secrets only in Secrets Manager; nothing sensitive in the code repo.
- JWT login (short-lived access + refresh tokens), per-IP rate limiting.
- An **INSERT-only audit log** records data changes.
- PII (e.g. subscriber phone numbers) sits behind a signed Data-Processing-Agreement
  gate; aligned with the Nigeria Data Protection Act.

### The last mile — SMS
Warnings reach communities as plain **SMS in local languages** (English, French,
Portuguese live; Hausa/Yoruba/Igbo in preparation) through partner agencies —
**no smartphone, no app, no literacy barrier**. Farmers don't register; numbers
come via partner agencies acting as data controllers.

---

## PART 5 — QUICK ANSWERS (likely questions)

- **"Is this really live or a mock-up?"** → Live in production on AWS; 700+ LGAs;
  here's the URL. Live data is labelled distinctly from modelled baselines.
- **"Where does your satellite data come from?"** → Copernicus Sentinel-1 (radar)
  and Sentinel-2 (NDVI), NASA FIRMS and VIIRS, plus WorldPop, World Bank, UNICEF
  GIGA, HDX. We'd love to add **NigeriaSat**.
- **"How accurate is the AI?"** → The crop model is a ResNet-50 at 87.2%
  validation, with a heatmap and human-review gating; conflict uses a Random Forest
  with confidence thresholds; floods/drought use statistical anomaly detection.
- **"How does radar see through clouds?"** → It's active microwave — it makes its
  own signal and reads the echo, so cloud and darkness don't block it. Water looks
  dark to radar, which is how we map floods.
- **"How is each state's data protected?"** → Schema-per-tenant isolation in the
  database; a state can never read another's; regional bodies get cross-state view
  by role.
- **"What do you want from us (NASRDA)?"** → Integrate NigeriaSat data, run a joint
  demonstration, and explore a data-sharing MOU — your satellites, visibly
  protecting Nigerian farmers.
- **"What's the business model?"** → Government/agency subscriptions (free pilot →
  annual licence); farmer SMS stays free, funded by institutional subscriptions.

---

## PART 6 — DEEP DIVE FOR A GIS / REMOTE-SENSING AUDIENCE

*Read this before meeting a GIS professional. These are the details they will
probe, in their own language.*

### Coordinate systems
All data is handled in **WGS84 geographic coordinates (EPSG:4326, lat/lon)**.
The web map renders in **Web Mercator (EPSG:3857)** via Mapbox GL, with deck.gl
drawing the data layers on top. Tenant areas are defined by a **region-of-interest
(ROI) bounding box**: `[min_lon, min_lat, max_lon, max_lat]`.

### Administrative boundaries & spatial joins
- Admin-2 units (LGAs / districts) come from **geoBoundaries** (open data).
- Each settlement / event point is assigned to its LGA by a **point-in-polygon
  spatial join**; per-LGA **centroids** drive map placement and the per-tenant
  lists (Kebbi 21, Benue 23, Kaduna 23, Niger 25, Plateau 17, Zamfara 14,
  Nasarawa 13, FCT 6 area councils, Ghana 260, Senegal 45).

### Raster handling (WorldPop)
- WorldPop population is a **GeoTIFF / Cloud-Optimized GeoTIFF (COG)**, ~100 m.
- We **point-sample** it at each settlement's coordinates with **rasterio**,
  handling **nodata** cells.
- We serve the raster from **our own S3 mirror** because the upstream server
  stopped honouring HTTP range requests — which breaks COG windowed reads. A GIS
  pro will appreciate that detail: we restored proper range-read behaviour rather
  than downloading whole 100–500 MB rasters per query.

### Zonal statistics (Sentinel via Copernicus Statistical API)
Instead of downloading raw scenes, we call Copernicus's **Statistical API**, which
computes **server-side zonal statistics** (mean / min / max / percentiles) over
each tenant's ROI per time bucket. So Sentinel-1 returns backscatter stats and
Sentinel-2 returns NDVI stats, as **time series** ready for anomaly detection —
efficient, and no gigabytes of imagery moved.

### Sensor specifics
| Sensor | Type | Resolution | Measure / bands | Revisit |
|---|---|---|---|---|
| Sentinel-1 | C-band SAR | ~10 m | VV/VH backscatter | ~6–12 days |
| Sentinel-2 | Optical | 10–20 m | NDVI = (B8 − B4)/(B8 + B4) | ~5 days |
| VIIRS Black Marble | Night optical | ~500 m | radiance (VNP46A2) | daily (we use weekly) |
| WorldPop | Modelled raster | ~100 m | persons / pixel | annual |
| NASA FIRMS | Thermal | 375 m–1 km | active-fire detections | daily (NRT) |

### NDVI math
**NDVI = (NIR − Red) / (NIR + Red)**; on Sentinel-2 that is **(B8 − B4)/(B8 + B4)**.
Range −1 to +1; dense healthy crops sit ~0.6–0.9. We compare a recent mean against
a baseline mean and flag the **z-score** deviation.

### SAR for flood
Open water is a **specular reflector** — it bounces the radar pulse away from the
sensor, so it returns **very low backscatter (dark)**. A sudden drop in VV/VH
backscatter over normally-bright land indicates **standing water** → mapped flood
extent, cloud-independent and day or night.

### Anomaly detection (the maths, plainly)
Per ROI we hold a baseline distribution; each new acquisition is scored
**z = (recent_mean − baseline_mean) / baseline_std**. Beyond a threshold → anomaly,
with a confidence band. Deliberately transparent — no black box for hazard calls.

### Visualization stack
Mapbox GL JS basemap (satellite / dark) + **deck.gl** GPU layers for points and
heatmaps. Pulse animations are decoupled from the data layers so re-rendering
stays smooth.

### Honest GIS caveats (knowing these earns credibility)
- We currently place per-LGA data at **centroids** for display; full-polygon
  **choropleth** is on the roadmap.
- The Statistical API gives **ROI-aggregate** values, not per-pixel rasters —
  excellent for trends, not for sub-LGA pixel mapping.
- Some layers (fine connectivity, the settlement baseline) are **modelled** and
  labelled as such.

### Where NASRDA / NigeriaSat fits (the GIS framing for the meeting)
**NigeriaSat-2** (~2.5 m panchromatic, ~5 m multispectral) and the **NCRS**
archives would give us **higher-resolution, locally-owned scenes** to: map at
**sub-LGA / field scale**, **validate** our 10 m Sentinel-derived indicators
against finer imagery, and move from ROI-aggregates toward **full-polygon
analysis**. In GIS terms: NigeriaSat complements our medium-resolution,
high-revisit Sentinel pipeline with high-resolution detail — a genuine
capability gain, not a duplication. *Lead with this when the director asks what
you'd do with their data.*

---

*Bizra Farms Integrated Nigeria Limited · bizrafarms@gmail.com · +234 703 791 9465*
