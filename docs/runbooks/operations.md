# Runbook: Production Incident Response
# =====================================
# Version: 1.0 | Owner: Abdullahi Zuru Ibrahim
# Use this runbook for any P1/P2 production incident.

## SEVERITY DEFINITIONS

| Level | Description | Response Time | Examples |
|-------|-------------|---------------|---------|
| P1 | Complete outage | Immediate | API down, database unreachable |
| P2 | Partial outage | < 15 minutes | Single module failing, high error rate |
| P3 | Degraded | < 1 hour | Slow responses, satellite data delayed |
| P4 | Minor | < 24 hours | UI glitch, non-critical feature broken |

---

## STEP 1: ASSESS (first 5 minutes)

```bash
# Check service health
curl https://api.economicbridge.app/health
curl https://api.economicbridge.app/api/v1/system/status

# Check ECS service status
aws ecs describe-services \
  --cluster economicbridge-production \
  --services economicbridge-api economicbridge-ingestion \
  --region af-south-1

# Check RDS status
aws rds describe-db-instances \
  --db-instance-identifier economicbridge-production \
  --region af-south-1

# Check recent application logs (last 100 lines)
aws logs tail /economicbridge/application \
  --since 30m \
  --region af-south-1

# Check Redis
redis-cli -h $REDIS_HOST ping
redis-cli -h $REDIS_HOST info memory
```

---

## STEP 2: COMMUNICATE (within 10 minutes for P1/P2)

For P1: Notify affected tenants via WhatsApp/email immediately.
Template:
> "EconomicBridge is experiencing a technical issue affecting [service].
> Our team is investigating. We will update you every 30 minutes.
> Current status: [investigating/identified/fixing]"

---

## STEP 3: COMMON INCIDENTS AND FIXES

### 3.1 API returns 500 errors

```bash
# Check recent error logs
aws logs filter-log-events \
  --log-group-name /economicbridge/application \
  --filter-pattern "ERROR" \
  --start-time $(date -d '30 minutes ago' +%s000) \
  --region af-south-1

# Restart API service (zero-downtime rolling restart)
aws ecs update-service \
  --cluster economicbridge-production \
  --service economicbridge-api \
  --force-new-deployment \
  --region af-south-1
```

### 3.2 Database connection exhausted

```bash
# Check active connections
psql $DATABASE_ADMIN_URL -c "
  SELECT count(*), state, wait_event_type, wait_event
  FROM pg_stat_activity
  WHERE datname = 'economicbridge'
  GROUP BY state, wait_event_type, wait_event;
"

# If > 80% connections used, terminate idle connections older than 5 minutes
psql $DATABASE_ADMIN_URL -c "
  SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
  WHERE datname = 'economicbridge'
  AND state = 'idle'
  AND query_start < NOW() - INTERVAL '5 minutes';
"
```

### 3.3 Tenant data leakage suspected

STOP. This is a security incident.

1. Immediately notify Abdullahi Zuru Ibrahim
2. Do NOT attempt to fix without senior review
3. Preserve all logs — do not restart services
4. Document exactly what was observed and when
5. Follow security incident procedure (separate document)

### 3.4 Satellite ingestion stopped

```bash
# Check Celery workers
celery -A apps.ingestion.tasks inspect active
celery -A apps.ingestion.tasks inspect scheduled

# Check queue lengths
redis-cli -h $REDIS_HOST llen celery

# Restart workers
aws ecs update-service \
  --cluster economicbridge-production \
  --service economicbridge-ingestion-worker \
  --force-new-deployment \
  --region af-south-1

# Manually trigger backfill if data gap > 24 hours
python scripts/backfill_ingestion.py \
  --tenant-id kebbi \
  --source nasa_firms \
  --from-date 2026-01-01
```

---

## STEP 4: POST-INCIDENT

Within 24 hours of resolution, write a post-incident report:
- Timeline of events
- Root cause
- Impact (tenants affected, duration, data affected)
- Fix applied
- Prevention measures

Store in: docs/incidents/YYYY-MM-DD-{short-description}.md

---

---

# Runbook: Satellite Data Source Outage
# =======================================
# Use when a satellite API is unavailable or returning bad data.

## Copernicus / Sentinel Hub Outage

**Check status:** https://status.dataspace.copernicus.eu

```bash
# Test Copernicus authentication
curl -X POST \
  "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token" \
  -d "client_id=$COPERNICUS_CLIENT_ID" \
  -d "client_secret=$COPERNICUS_CLIENT_SECRET" \
  -d "grant_type=client_credentials"

# If Copernicus is down:
# 1. Ingestion scheduler will auto-retry with exponential backoff
# 2. Dashboard continues to serve last-known good data
# 3. Alert banner shown to affected tenants: "Satellite imagery delayed"
# 4. Set FEATURE flag to show data staleness timestamp
```

**Acceptable data gaps (per module):**
- Farmland Protection (SAR): Up to 6 days (Sentinel-1 revisit cycle)
- Flood Detection (SAR): Up to 6 days — escalate if active flood event
- Crop monitoring (MSI): Up to 10 days if cloud cover high
- Heat/fire (NASA FIRMS): Alert if gap > 24 hours — switch to VIIRS backup

## NASA FIRMS Outage

```bash
# Check status: https://firms.modaps.eosdis.nasa.gov/
# Automatic failover to VIIRS_NOAA20_NRT product
# If both down, check MODIS NRT

# Manually switch product
export NASA_FIRMS_PRODUCT=MODIS_NRT
python scripts/trigger_ingestion.py --source nasa_firms --all-tenants
```

---

---

# Runbook: New Tenant Onboarding
# ================================
# Step-by-step checklist for onboarding a new state government or ECOWAS country.

## Prerequisites
- [ ] Signed service agreement received
- [ ] Ministry IT contact details confirmed
- [ ] Satellite ROI bounding box verified on map
- [ ] Primary language confirmed (en/fr/pt/ha/yo/ig)
- [ ] SMS gateway tested for country (Termii for Nigeria, Twilio for others)

## Provisioning Steps

```bash
# 1. Add tenant to tenants.yaml
# (follow the format in existing tenant entries)
vim tenants.yaml

# 2. Validate configuration
python scripts/validate_tenant.py --tenant-id {new_id}

# 3. Generate tenant infrastructure
python scripts/generate_tenant.py --tenant-id {new_id}
# This creates:
# - PostgreSQL schema: tenant_{new_id}
# - S3 prefix: s3://economicbridge-satellite/{new_id}/
# - Redis namespace: economicbridge:{new_id}:
# - Default admin user (password emailed to ministry contact)

# 4. Run migrations for new tenant
python scripts/run_migrations.py --tenant-id {new_id}

# 5. Seed reference data (poverty indices, administrative boundaries)
python scripts/seed_tenant.py --tenant-id {new_id}

# 6. Configure satellite ingestion schedule
python scripts/configure_ingestion.py --tenant-id {new_id}

# 7. Run smoke tests
python scripts/test_tenant.py --tenant-id {new_id}

# 8. Verify in database
psql $DATABASE_ADMIN_URL -c "
  SELECT schema_name FROM information_schema.schemata
  WHERE schema_name = 'tenant_{new_id}';
"
```

## Post-Provisioning

- [ ] Send welcome email to ministry contact with login credentials
- [ ] Schedule capacity training workshop (₦2–3M per cohort)
- [ ] Set up monitoring dashboard for new tenant in Grafana
- [ ] Add tenant to PagerDuty escalation policy
- [ ] Document onboarding in: docs/tenants/{new_id}-onboarding.md
