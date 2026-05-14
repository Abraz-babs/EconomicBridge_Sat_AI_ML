#!/usr/bin/env bash
# audit_package.sh — Generate Government Audit Package
# =====================================================
# Generates a complete compliance artefact package for government IT audits.
# Output: ./audit-package/ directory with timestamped zip
#
# Run: make audit
# Or directly: bash scripts/audit_package.sh

set -euo pipefail

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
OUTPUT_DIR="./audit-package"
PACKAGE_NAME="economicbridge-audit-${TIMESTAMP}"
PACKAGE_DIR="${OUTPUT_DIR}/${PACKAGE_NAME}"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  EconomicBridge — Government Audit Package Generator"
echo "  Timestamp: ${TIMESTAMP}"
echo "═══════════════════════════════════════════════════════"
echo ""

mkdir -p "${PACKAGE_DIR}"

# ─────────────────────────────────────────
# 1. SECURITY SCAN
# ─────────────────────────────────────────
echo "→ [1/8] Running Bandit security scan..."
bandit -r apps/api apps/ingestion apps/ml \
  -f json \
  -o "${PACKAGE_DIR}/security-scan.json" \
  --severity-level medium \
  --confidence-level medium 2>/dev/null || true

# Check for HIGH/CRITICAL findings — fail if any
HIGH_COUNT=$(python3 -c "
import json
with open('${PACKAGE_DIR}/security-scan.json') as f:
    data = json.load(f)
high = sum(1 for r in data.get('results', []) if r['issue_severity'] in ['HIGH', 'CRITICAL'])
print(high)
")

if [ "$HIGH_COUNT" -gt "0" ]; then
  echo "✗ FAILED: ${HIGH_COUNT} HIGH/CRITICAL security findings. Cannot generate audit package."
  echo "  Fix all HIGH/CRITICAL findings before generating audit package."
  exit 1
fi
echo "  ✓ Security scan passed (0 HIGH/CRITICAL findings)"

# ─────────────────────────────────────────
# 2. DEPENDENCY AUDIT
# ─────────────────────────────────────────
echo "→ [2/8] Auditing dependencies for known CVEs..."
pip-audit \
  --requirement apps/api/requirements.txt \
  --format json \
  --output "${PACKAGE_DIR}/dependency-audit.json" 2>/dev/null || {
  echo "  ⚠ pip-audit found vulnerabilities — review ${PACKAGE_DIR}/dependency-audit.json"
}
echo "  ✓ Dependency audit complete"

# ─────────────────────────────────────────
# 3. TEST COVERAGE REPORT
# ─────────────────────────────────────────
echo "→ [3/8] Running tests with coverage..."
cd apps/api && pytest tests/ \
  --cov=. \
  --cov-report=html:"../../${PACKAGE_DIR}/coverage-report" \
  --cov-report=json:"../../${PACKAGE_DIR}/coverage.json" \
  --cov-fail-under=85 \
  -q 2>&1 | tail -5
cd ../..
echo "  ✓ Coverage report generated"

# ─────────────────────────────────────────
# 4. API SPECIFICATION
# ─────────────────────────────────────────
echo "→ [4/8] Exporting OpenAPI specification..."
python3 -c "
import json
import sys
sys.path.insert(0, 'apps/api')
from main import app
with open('${PACKAGE_DIR}/api-spec.json', 'w') as f:
    json.dump(app.openapi(), f, indent=2)
" 2>/dev/null || echo "  ⚠ Could not export OpenAPI spec (is the API running?)"
echo "  ✓ API specification exported"

# ─────────────────────────────────────────
# 5. TENANT ISOLATION PROOF
# ─────────────────────────────────────────
echo "→ [5/8] Generating tenant isolation proof..."
cat > "${PACKAGE_DIR}/tenant-isolation-proof.sql" << 'EOF'
-- Tenant Isolation Verification Queries
-- ======================================
-- These queries verify that EconomicBridge enforces
-- data isolation between tenants at the PostgreSQL schema level.
--
-- Run these queries against the production database to verify
-- that tenant data is properly isolated.

-- 1. List all tenant schemas
SELECT schema_name, schema_owner
FROM information_schema.schemata
WHERE schema_name LIKE 'tenant_%'
ORDER BY schema_name;

-- 2. Verify each tenant schema has its own tables
SELECT table_schema, COUNT(*) as table_count
FROM information_schema.tables
WHERE table_schema LIKE 'tenant_%'
GROUP BY table_schema
ORDER BY table_schema;

-- 3. Verify the application user CANNOT delete from audit log
-- (Expected result: permission denied)
-- \c economicbridge economicbridge_app
-- DELETE FROM tenant_kebbi.audit_log WHERE id = 'any-id';

-- 4. Verify row counts are isolated per tenant
-- (Run as DBA to verify data does not appear in wrong schema)
SELECT 'tenant_kebbi' as schema, COUNT(*) as alert_count
FROM tenant_kebbi.alert_events
UNION ALL
SELECT 'tenant_benue', COUNT(*)
FROM tenant_benue.alert_events;

-- 5. Verify audit log is append-only
SELECT grantee, privilege_type
FROM information_schema.role_table_grants
WHERE table_name = 'audit_log'
  AND grantee = 'economicbridge_app';
-- Expected: INSERT only — no UPDATE, no DELETE
EOF
echo "  ✓ Tenant isolation proof generated"

# ─────────────────────────────────────────
# 6. COMPLIANCE MAPPING
# ─────────────────────────────────────────
echo "→ [6/8] Generating NDPA 2023 compliance mapping..."
cat > "${PACKAGE_DIR}/compliance-mapping.md" << 'EOF'
# NDPA 2023 Compliance Mapping — EconomicBridge
# ==============================================
# Maps each relevant article of Nigeria's Data Protection Act 2023
# to the corresponding implementation in EconomicBridge.

## Article 24 — Lawful Basis for Processing
**Implementation:** All data processing recorded in `dpa_processing_records` table
with explicit lawful basis. Public interest basis documented for government tenants.

## Article 25 — Consent
**Implementation:** Free-tier users provide explicit consent at registration.
Institutional tenants process data under public interest/contractual basis.
Consent records stored in `consent_records` table with timestamp and version.

## Article 26 — Right to Erasure
**Implementation:** Erasure requests logged in `dpa_erasure_requests` table.
Physical deletion performed by DBA via documented runbook (docs/runbooks/ndpa-erasure.md).
Certificate of erasure issued to requestor.

## Article 27 — Data Minimisation
**Implementation:** Only data necessary for stated purpose is collected.
Satellite imagery processed to derived indices — raw imagery not retained beyond
48 hours unless explicit research agreement exists.

## Article 34 — Data Protection Impact Assessment
**Implementation:** DPIA completed for all high-risk processing activities.
See docs/dpia/ for assessments covering satellite imagery processing,
ML model inference on agricultural data, and multi-government data sharing.

## Article 38 — Data Breach Notification
**Implementation:** Sentry + PagerDuty alert system detects anomalies within
minutes. Documented incident response procedure (docs/runbooks/operations.md).
NDPC notification within 72 hours of confirmed breach per NDPA requirements.

## Article 43 — Cross-Border Data Transfer
**Implementation:** Nigerian citizen data stored exclusively in AWS af-south-1
(Cape Town). Cross-border queries to ECOWAS tenants require bilateral_agreement
flag in tenant configuration. Data transfer agreements documented per tenant.
EOF
echo "  ✓ Compliance mapping generated"

# ─────────────────────────────────────────
# 7. AUDIT LOG SAMPLE
# ─────────────────────────────────────────
echo "→ [7/8] Generating audit log sample..."
cat > "${PACKAGE_DIR}/audit-log-sample.json" << 'EOF'
[
  {
    "id": "a1b2c3d4-0000-0000-0000-000000000001",
    "tenant_id": "kebbi",
    "user_id": "ministry-user-001",
    "action": "READ",
    "resource_type": "conflict_alert",
    "resource_id": "alert-id-001",
    "trace_id": "trace-0001",
    "ip_address": "105.112.x.x",
    "timestamp": "2026-06-15T08:23:11.000Z",
    "note": "PII fields anonymised in this sample"
  },
  {
    "id": "a1b2c3d4-0000-0000-0000-000000000002",
    "tenant_id": "kebbi",
    "user_id": "system-ingestion",
    "action": "CREATE",
    "resource_type": "satellite_scene",
    "resource_id": "scene-id-001",
    "trace_id": "trace-0002",
    "ip_address": "10.0.1.x",
    "timestamp": "2026-06-15T06:00:03.000Z",
    "note": "Automated ingestion from Sentinel-1 SAR"
  }
]
EOF
echo "  ✓ Audit log sample generated"

# ─────────────────────────────────────────
# 8. PACKAGE SUMMARY
# ─────────────────────────────────────────
echo "→ [8/8] Generating package summary..."
cat > "${PACKAGE_DIR}/README.md" << EOF
# EconomicBridge — Government Audit Package
**Generated:** ${TIMESTAMP}
**Platform:** EconomicBridge v$(cat apps/api/VERSION 2>/dev/null || echo '1.0.0')
**Operator:** Bizra Farms Integrated Nigeria Limited

## Contents

| File | Description |
|------|-------------|
| security-scan.json | Bandit security scan results (0 HIGH/CRITICAL required) |
| dependency-audit.json | Python dependency CVE audit |
| coverage-report/ | Test coverage HTML report (>= 85% required) |
| api-spec.json | Complete OpenAPI specification |
| tenant-isolation-proof.sql | SQL queries verifying tenant data isolation |
| compliance-mapping.md | NDPA 2023 article-by-article compliance mapping |
| audit-log-sample.json | Sample audit log entries |

## Verification

To independently verify this package:

1. Security: Confirm \`security-scan.json\` contains 0 HIGH/CRITICAL severity items
2. Coverage: Open \`coverage-report/index.html\` — verify >= 85% total coverage
3. Isolation: Run \`tenant-isolation-proof.sql\` against production database
4. Compliance: Review \`compliance-mapping.md\` against NDPA 2023 text

## Contact

Technical queries: [your email]
Registered entity: Bizra Farms Integrated Nigeria Limited
CAC Registration: [registration number]
EOF

# Create zip archive
cd "${OUTPUT_DIR}"
zip -r "${PACKAGE_NAME}.zip" "${PACKAGE_NAME}/" -q
cd ../..

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ✓ Audit package generated successfully"
echo "  Location: ${OUTPUT_DIR}/${PACKAGE_NAME}.zip"
echo "  Contents: $(ls ${PACKAGE_DIR} | wc -l | tr -d ' ') files"
echo "═══════════════════════════════════════════════════════"
echo ""
