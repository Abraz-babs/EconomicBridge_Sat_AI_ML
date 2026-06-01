# WFP Innovation Challenge — EconomicBridge application

**Applicant:** Bizra Farms Integrated Nigeria Ltd.
**Product:** EconomicBridge — multi-tenant satellite intelligence for West African administrative units.
**Apply via:** startup form (bit.ly/WFP_ApplicationForm) — rolling basis. Contact: global.innovation@wfp.org

> Fill every **[bracket]** with real numbers / bios before submitting. Keep claims honest — WFP does technical due diligence.

---

## Positioning (one line)

> "Sub-national targeting + anticipatory action for West Africa from open satellite data — so WFP knows **where** the food-insecure are, gets **early warning** before floods/droughts hit them, and reaches affected smallholders **directly by SMS**."

**Lead theme:** Resilience & Sustainable Livelihoods.
**Cross-tag:** Food Systems & Smallholder Farmers; Emergency Preparedness & Response.
**Cross-cuts:** climate adaptation, cash transfers, targeting/gender.

(2024 challenge themes: Emergency Preparedness & Response; Supply Chain & Delivery; Nutrition & School Meals; Food Systems & Smallholder Farmers; Resilience & Sustainable Livelihoods; Social Protection.)

---

## Eligibility self-check

- ✅ **Legal entity** — Bizra Farms Integrated Nigeria Ltd.
- ✅ **MVP / proof-of-concept** — live multi-tenant dashboard; real feeds (Copernicus Sentinel-1/2, NASA FIRMS, GIGA, World Bank, VIIRS/WorldPop); a trained CropGuard crop-disease model. Past MVP on several modules.
- ✅ **WFP country presence** — Nigeria (major WFP operation), Ghana, Senegal.
- ⚠️ **Be transparent**: pre-production (Terraform-ready for AWS, not yet applied); ShockGuard drought is modelled; ML needs field validation.

What they fund: **up to US$100,000 equity-free**, 6-month Sprint, mentors (incl. John Deere, Google, Netlight), innovation consultant, WFP field/HQ access, visibility.

---

## Selection-criteria answers (draft)

### Impact (scale to millions of beneficiaries)
EconomicBridge covers 10 pilot administrative units (8 Nigerian states + Ghana + Senegal) at full LGA resolution — ~447 sub-national units, ~[population] people. Schema-per-tenant architecture means a new state/country is a configuration step, not a rebuild. A West-Africa-wide deployment would put VAM-grade vulnerability + shock targeting over ~[X]M people, so WFP food/cash reaches the right LGAs *before* a crisis.

### Feasibility (build / deploy / maintain)
Runs on open, free, no-licence data (Copernicus Sentinel-1/2, NASA FIRMS, VIIRS Black Marble, WorldPop, World Bank, GIGA) — no per-query satellite cost, so unit economics scale. Containerised; Terraform for AWS (multi-AZ, Secrets Manager, autoscaling). A 6-month Sprint deploys to production and validates two modules with a WFP country office.

### Innovation level
Novel combination per administrative tenant: (1) sub-national **VAM** from night-lights + population; (2) **anticipatory-action** flood/drought from Sentinel-1 SAR; (3) a **trained crop-disease classifier** for smallholder loss; (4) **last-mile SMS** to farmers with no smartphone. The farmland **encroachment / farmer-herder conflict** layer is rare in EO products and directly relevant to WFP's conflict-affected operations (Benue/Plateau).

### Financial sustainability (revenue beyond WFP)
Open-access base dashboard; **paid tiers** — government (state/ministry subscriptions), agency (analyst seats / API), premium modules. Free farmer SMS funded via partner agencies. [Insert LOIs, pilot revenue, pricing.]

### Team
[Founder bio — Bizra Farms, domain + build track record. Key technical + agronomy team. West Africa presence. Advisors.]

---

## 6-month Sprint plan

- **M1–2** — Co-design with one WFP country office (Nigeria VAM team). Pick 1–2 modules tied to their KPI (recommend **Poverty/VAM targeting + ShockGuard anticipatory action**). Deploy to AWS production.
- **M3–4** — Validate against WFP ground data; integrate WFP datasets; field-test SMS alerts in one state.
- **M5–6** — Pilot report with WFP; scale-pathway costing; MoU for next country.

---

## Before submitting

1. **Get one LOI** — a Nigerian state or WFP country-office contact who would pilot this. Their stated priority is *"designed alongside core users with traction"* — a user letter beats any feature.
2. **Record the 5-minute demo** (see WFP_DEMO_SCRIPT.md) and link it. A working live demo at application stage is rare and differentiating.

---

## Real-vs-modelled disclosure (keep handy for Q&A)

| Module | Status |
|---|---|
| Economic Visibility / Poverty | **Real** — VIIRS Black Marble + WorldPop, all LGAs |
| Economic Mobility / SkillsBridge | **Real anchors** — World Bank, GIGA (schools/connectivity) |
| ShockGuard flood | **Real** — Sentinel-1 SAR, on-demand live scan |
| ShockGuard drought | **Modelled** — synthetic until MODIS/LST ingest (Phase B) |
| CropGuard | **Real** — ResNet-50 trained on PlantVillage + Kaggle (val ~0.87); field validation pending |
| Aid Coordination | **Seed/demo** coverage; needs WFP/agency data to go live |
| Farmland | **Live (FIRMS fire)**; encroachment/conflict layer needs ACLED (planned) |
