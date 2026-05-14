# ADR-002: Satellite Data Ingestion as a Separate Microservice

**Status:** Accepted  
**Date:** March 2026  
**Deciders:** Abdullahi Zuru Ibrahim (Platform Architect)

---

## Context

EconomicBridge depends on six satellite data sources: Copernicus Sentinel-1 SAR,
Sentinel-2 MSI, NASA FIRMS, VIIRS, MODIS, and N2YO pass tracking. Each source
has distinct authentication, rate limits, data formats, and ingestion schedules.
Sentinel-1 delivers GeoTIFF files up to 1GB per scene. NASA FIRMS delivers CSV
hotspot data every 3 hours. N2YO provides live TLE pass predictions via polling.

The question was whether to integrate these sources directly into the main FastAPI
application or to isolate them in a dedicated ingestion microservice.

---

## Decision

**Dedicated Ingestion Microservice** (`apps/ingestion/`), deployed independently
from the main API, communicating via internal message queue (Redis pub/sub).

The main API **never** calls satellite APIs directly. It only reads from the
processed data tables that the ingestion service writes to. The ingestion service
**never** serves HTTP requests from the frontend — it is an internal worker only.

---

## Consequences

### Positive
- Satellite API failures do not degrade the main API or dashboard
- Ingestion can be scaled independently (more workers during active satellite passes)
- Rate limit logic, retry logic, and API authentication is isolated in one place
- Large file processing (1GB GeoTIFFs) does not block API request handling
- Ingestion workers can be restarted without any user-facing downtime
- Each satellite source can have its own Celery queue with independent concurrency
- Simpler testing: main API tests mock the processed data tables, not raw APIs

### Negative
- Two codebases to maintain instead of one
- Additional infrastructure: separate ECS service, separate Celery workers
- Slightly more complex local development (docker-compose handles this)
- Data latency: satellite data is available to the dashboard after ingestion
  completes, not in real-time (acceptable — Sentinel-1 has 6-day revisit anyway)

---

## Data Flow

```
Copernicus API ──┐
NASA FIRMS ──────┤
N2YO ───────────┼──► Ingestion Service ──► S3 (raw) ──► Processor ──► PostgreSQL ──► API
Earth Engine ───┤
VIIRS ───────────┤
MODIS ───────────┘
```

---

## Ingestion Schedule

| Source       | Schedule         | Trigger          |
|--------------|------------------|------------------|
| Sentinel-1   | Every 6 days     | N2YO pass event  |
| Sentinel-2   | Every 5 days     | N2YO pass event  |
| NASA FIRMS   | Daily 06:00 UTC  | Cron             |
| VIIRS        | Daily 06:30 UTC  | Cron             |
| MODIS        | Daily 07:00 UTC  | Cron             |
| N2YO         | Every 30 minutes | Cron             |

---

## Rejected Alternative

**Direct integration in main API:** Tested in Citadel Kebbi prototype. A single
Sentinel-1 file download blocking an async event loop caused a 45-second API
timeout. Unacceptable for a multi-tenant production system. Isolation was the
correct lesson from that experience.
