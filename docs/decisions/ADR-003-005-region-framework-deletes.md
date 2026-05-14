# ADR-003: AWS af-south-1 (Cape Town) as Primary Region

**Status:** Accepted  
**Date:** March 2026  
**Deciders:** Abdullahi Zuru Ibrahim (Platform Architect)

---

## Context

EconomicBridge processes and stores sensitive agricultural, economic, and security
data for Nigerian state governments and ECOWAS member countries. Data residency
and sovereignty requirements under Nigeria's Data Protection Act 2023 (NDPA) and
ECOWAS Supplementary Act on Personal Data Protection require that data about
Nigerian citizens remain within Africa where technically feasible.

AWS regions evaluated: eu-west-1 (Ireland), us-east-1 (Virginia),
af-south-1 (Cape Town), me-south-1 (Bahrain).

---

## Decision

**AWS af-south-1 (Cape Town) as the primary production region.**

---

## Consequences

### Positive
- Data residency on African continent — satisfies NDPA 2023 and ECOWAS directives
- Lower latency to Lagos, Abuja, Accra, Dakar compared to European or US regions
- Demonstrates commitment to African data sovereignty — a selling point for
  government procurement conversations
- Eligible for AWS Africa-specific grants and credits

### Negative
- Fewer AWS services available in af-south-1 than eu-west-1 or us-east-1
  (verified all required services are available: ECS Fargate, RDS, S3, ElastiCache,
  Secrets Manager, CloudWatch — all confirmed available in af-south-1)
- Slightly higher bandwidth costs for international NGO users connecting from Europe
  (acceptable — primary users are in-region)

### Disaster Recovery
- Secondary region: eu-west-1 (Ireland) — S3 cross-region replication for satellite
  imagery archives. RDS automated backups replicated to eu-west-1 encrypted S3.
- RTO: 4 hours | RPO: 1 hour

---

---

# ADR-004: FastAPI Over Django REST Framework

**Status:** Accepted  
**Date:** March 2026  
**Deciders:** Abdullahi Zuru Ibrahim (Platform Architect)

---

## Context

Python web framework selection for the EconomicBridge API backend.
Candidates: Django REST Framework (DRF), FastAPI, Flask + extensions.

---

## Decision

**FastAPI with async SQLAlchemy.**

---

## Rationale

| Criterion | DRF | FastAPI |
|-----------|-----|---------|
| Async support | Limited | Native (ASGI) |
| Type safety | Optional | Required by design |
| Auto OpenAPI docs | Manual | Automatic from types |
| Performance | Moderate | High (Starlette base) |
| Pydantic integration | Addon | Native |
| Satellite workload fit | Poor | Excellent |

The satellite ingestion pipeline produces high-throughput async I/O — reading
large files from S3, writing to TimescaleDB, publishing to Redis. Django's
ORM is synchronous at its core. FastAPI with async SQLAlchemy 2.0 handles
this workload without thread pool overhead.

The automatic OpenAPI documentation generation from Pydantic types is also
significant — government API audits require complete, accurate API documentation.
FastAPI generates this from the code itself, eliminating documentation drift.

---

## Consequences

- All developers must be comfortable with async Python (async/await)
- No Django admin interface — build lightweight admin views in React instead
- No Django signals — use explicit service layer calls and SQLAlchemy events
- Migration tooling is Alembic (not Django migrations) — more explicit but
  equally powerful

---

---

# ADR-005: Soft Deletes Only — No Hard Deletes in Production

**Status:** Accepted  
**Date:** March 2026  
**Deciders:** Abdullahi Zuru Ibrahim (Platform Architect)

---

## Context

EconomicBridge data — poverty maps, conflict alerts, crop disease events,
flood warnings — is used by government agencies, NGOs, and international
bodies for decision-making. The platform is subject to government audit.
NDPA 2023 requires a complete data processing record. Development banks
and research institutions pay for historical data licensing.

The question: when a user or admin "deletes" a record, should it be
physically removed from the database?

---

## Decision

**Soft deletes only in production.** Physical deletes are prohibited at the
application layer. Every table has an `is_deleted BOOLEAN DEFAULT FALSE`
column. "Delete" operations set `is_deleted = TRUE` and write to the audit log.

The application user (the PostgreSQL role used by the API) has no `DELETE`
privilege on any production table. DELETE is reserved for the DBA role only,
used exclusively for NDPA data erasure requests processed through a documented
compliance workflow.

---

## Consequences

### Positive
- Complete audit trail — nothing disappears without a record
- Government auditors can verify data integrity back to day one
- Historical data available for research licensing revenue stream
- NDPA compliance: erasure requests are documented procedures, not silent deletes
- Accidental "delete" operations are recoverable

### Negative
- Queries must filter `WHERE is_deleted = FALSE` — handled by SQLAlchemy
  base model with a default query filter
- Database grows larger over time — acceptable given TimescaleDB compression
  and the value of historical satellite data

### NDPA Erasure Requests
When a legitimate data erasure request is received under NDPA Article 26:
1. Log erasure request in `dpa_erasure_requests` table
2. DBA executes physical delete via documented runbook (docs/runbooks/ndpa-erasure.md)
3. Erasure confirmation logged in audit table
4. Certificate of erasure issued to requestor
