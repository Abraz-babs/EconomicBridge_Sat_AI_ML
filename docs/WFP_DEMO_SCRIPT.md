# EconomicBridge — 5-minute live demo script (WFP program officer)

**Goal:** make them feel WFP's targeting/anticipatory-action pain in the first 30 seconds, then show the platform answering it.
**Setup:** open the dashboard at `localhost:3001` (or the deployed URL) before you start. Use **one tenant throughout — Benue** (food-basket, conflict-affected) — so the story is coherent. **Lead with real data only.**

---

### [0:00–0:30] The pain — no screen yet (or logo slide)
> "WFP's hardest question in West Africa is targeting: *which* communities are most food-insecure, *before* the next flood or drought hits them — at village level, not the national average, and without waiting weeks for a survey. Today that's slow and coarse. EconomicBridge answers it from satellites and open data, refreshed continuously, down to every local government area."

### [0:30–1:30] WHERE — sub-national vulnerability (Economic Visibility / Poverty)
*Click into **Benue**. Open the Poverty / Economic-Visibility map.*
> "Every LGA in the state — not 8 samples, all of them — scored for vulnerability from VIIRS night-lights and WorldPop population. The dark, dense settlements are where need concentrates. This is VAM at village resolution, generated automatically."
*Hover a high-score halo — show real population, poverty score, source.*

### [1:30–2:30] WHEN — anticipatory action (ShockGuard — the wow)
*Open ShockGuard, same tenant. Click **LIVE**.*
> "This is live Sentinel-1 radar — the actual satellite. It compares recent backscatter against this area's baseline to flag flooding before it's visible on the ground. Right now it honestly shows no active flood — that's the early-warning signal WFP needs for anticipatory cash, days ahead. When the radar shifts, this fires."
*Point to the real series points + z-score.*

### [2:30–3:30] WHAT'S AT RISK — smallholder crops (CropGuard)
*Open CropGuard. Hover a disease halo.*
> "For smallholders, a crop-disease outbreak is a food-security event. This is a ResNet model trained on real leaf imagery — it names the crop *and* the disease, and pins the **target area: the LGA and exact coordinates**, so an extension officer or WFP partner knows where to go. Cassava mosaic, maize blight, rice blast — geolocated."

### [3:30–4:15] COORDINATION — no duplication, no gaps (Aid Coordination)
*Open Aid Coordination.*
> "WFP never works alone. This maps which agencies cover which LGAs — green where multiple agencies overlap, **red where there's a coverage gap and no one's there.** That's where WFP should direct resources, and it stops two agencies double-serving the same village."

### [4:15–5:00] REACH + the ask (close)
> "And the last mile: farmers without smartphones get alerts by **SMS**, sourced through partner agencies — no app, no literacy barrier. Everything you've seen runs on free, open satellite and World Bank data, multi-tenant, so a new country is a config change.
> Our ask for the WFP Sprint: deploy two modules — vulnerability targeting and anticipatory action — with one country office, validate against your ground data, and pilot SMS in one state in six months. We bring the platform; WFP brings the operational reality that makes it count."

---

## Honesty guardrails (do / don't)

- ✅ Show **LIVE Sentinel-1**, **CropGuard real predictions**, **all-LGA poverty** — these are real.
- ⛔ Don't present ShockGuard's seeded **Recent Events** as live detections — they're demo seed. If asked, say so; the transparency builds trust.
- Keep **one tenant (Benue)** throughout. Mention scale (10 tenants, ~447 LGAs) only at the close — don't tab through all ten.
- If the live SAR scan shows the amber "modelled estimate" note for a tenant, that's the honest sparse-coverage fallback — explain it rather than hiding it.

## Pre-demo checklist
- [ ] All 5 services up (frontend 3001; api 8000; ingestion 8001; ml 8002; notifications 8003).
- [ ] Benue loads with all LGAs on the Poverty map.
- [ ] ShockGuard LIVE returns a real scan for Benue (19 real Sentinel-1 passes).
- [ ] CropGuard shows real `0.1.0-trained` predictions with LGA + coordinates on hover.
- [ ] Recording tool ready (link the recording in the WFP application).
