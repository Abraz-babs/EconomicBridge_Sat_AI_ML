# Build Roadmap — June 2026 to May 2027

Structured around two product milestones (August 2026 and May 2027). Every quarter delivers something that can be demonstrated live — not progress reports, but working systems with real satellite data and verifiable impact numbers.

---

## Pre-Production — Now to June 2026 ← **WE ARE HERE (March 2026)**

**Foundation**

- [x] System design document finalised (architecture v2)
- [x] GitHub repository with CI/CD, branch protection, and audit pipeline
- [ ] AWS account configured — IAM, Secrets Manager, Cape Town region
- [ ] Copernicus, NASA EARTHDATA, N2YO API credentials secured
- [x] EconomicBridge prototype v0.3 deployed to GitHub Pages
- [x] **EconomicBridge Next.js production app built** (dashboard, farmland module, role-based access)
- [ ] Bizra Farms CAC amendment — add satellite intelligence services to business objects

> **✓ Gate:** Repository live, credentials secured, prototype accessible via public URL

---

## Q1 — June to August 2026

**Core Infrastructure & 6-State Pilot**

- [ ] FastAPI backend — JWT auth, PostGIS, schema-per-tenant isolation
- [ ] Satellite Ingestion Engine — Copernicus + NASA FIRMS + N2YO live pass
- [ ] Farmland Protection module — SAR heat detection and conflict predictor live
- [ ] 6-state pilot: Kebbi, Benue, Plateau, Kaduna, Niger, Zamfara
- [ ] 3,000 previously invisible villages mapped in pilot states
- [ ] Immutable audit log and DPA tracking system operational
- [ ] Free-tier SMS alerts via Termii live for farmers in pilot states

> **★ Milestone 1 (August 2026)** — Live demo: real satellite data, 6 states, conflict prediction running, villages mapped

---

## Q2 — September to November 2026

**AI Models, Scale & First Revenue**

- [ ] CropGuard — ResNet-50 crop disease classifier live
- [ ] ShockGuard — U-Net flood detection with SAR pipeline
- [ ] Economic Mobility Compass — NBS API integration
- [ ] 10,000 farmers reached via free-tier SMS alerts
- [ ] 500,000 people covered under ShockGuard early warning
- [ ] First paid institutional contract signed (NGO or state government)

> **✓ Gate:** Satellite detection to field worker SMS in under 30 minutes, end-to-end

---

## Q3 — December 2026 to February 2027

**ECOWAS Entry & Partner Integration**

- [ ] SkillsBridge module — remote education access mapping
- [ ] Ghana pilot — Ministry of Food and Agriculture partnership via FAO
- [ ] Senegal pilot — Francophone configuration, French SMS alerts live
- [ ] WFP SCOPE and UNHCR proGres API integration complete
- [ ] ECOWAS Commission presentation — Abuja headquarters
- [ ] Open API for NGO app developers launched publicly

> **✓ Gate:** 2 ECOWAS countries live, at least 1 international body data agreement signed

---

## Q4 — March to May 2027

**Full Coverage & Public Launch**

- [ ] All 36 Nigerian states + FCT live
- [ ] Remaining 13 ECOWAS countries onboarded
- [ ] Free tier operational — 100,000+ users across West Africa
- [ ] Impact report: conflicts prevented, livelihoods protected, villages mapped
- [ ] Conflict prediction model open-sourced on GitHub
- [ ] USAID Feed the Future grant application submitted
- [ ] Seed investment conversations initiated ($1.5–3M target)

> **★ Milestone 2 (May 2027)** — Public launch: full West Africa coverage, credible roadmap of what was built, who is involved, barriers overcome, and near-term replication path

---

## Module → Roadmap Mapping

| Module | Architecture Name | Roadmap Quarter |
|--------|------------------|-----------------|
| 01 | Poverty Mapping (Economic Visibility) | Pre-Production / Q1 |
| 02 | Aid Coordination Bridge | Q1 |
| 03 | Farmland Protection | **Q1 — Priority** |
| 04 | Agriculture (CropGuard) | Q2 |
| 05 | Disaster Relief (ShockGuard) | Q2 |
| 06 | Economic Mobility Compass | Q2 |
| 07 | SkillsBridge | Q3 |
