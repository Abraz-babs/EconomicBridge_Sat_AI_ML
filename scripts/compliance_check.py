#!/usr/bin/env python3
"""
Compliance Checker — EconomicBridge
=====================================
Checks NDPA 2023 compliance by verifying required tables, audit mechanisms,
and data protection controls are in place.

Usage:
    python scripts/compliance_check.py --framework ndpa2023
    make compliance-check
"""

import argparse
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent


def check_ndpa2023() -> tuple[list[str], list[str]]:
    """Check NDPA 2023 compliance requirements.

    Returns:
        Tuple of (passed checks list, failed checks list).
    """
    passed: list[str] = []
    failed: list[str] = []

    # 1. Audit log model exists
    audit_model_path = PROJECT_ROOT / "apps" / "api" / "models" / "audit_log.py"
    if audit_model_path.exists():
        passed.append("Audit log model exists (apps/api/models/audit_log.py)")
    else:
        failed.append(
            "Audit log model missing — create apps/api/models/audit_log.py "
            "per CLAUDE.md Section 6"
        )

    # 2. DPA model exists
    dpa_model_path = PROJECT_ROOT / "apps" / "api" / "models" / "dpa.py"
    if dpa_model_path.exists():
        passed.append("DPA model exists (apps/api/models/dpa.py)")
    else:
        failed.append(
            "DPA processing records model missing — create apps/api/models/dpa.py "
            "for NDPA Article 24 compliance"
        )

    # 3. Tenant isolation middleware exists
    tenant_middleware = PROJECT_ROOT / "apps" / "api" / "middleware" / "tenant.py"
    if tenant_middleware.exists():
        passed.append("Tenant isolation middleware exists")
    else:
        failed.append(
            "Tenant isolation middleware missing — create apps/api/middleware/tenant.py "
            "per ADR-001"
        )

    # 4. Audit middleware exists
    audit_middleware = PROJECT_ROOT / "apps" / "api" / "middleware" / "audit.py"
    if audit_middleware.exists():
        passed.append("Audit middleware exists")
    else:
        failed.append(
            "Audit middleware missing — create apps/api/middleware/audit.py "
            "for Article 24 processing records"
        )

    # 5. Security middleware exists
    security_middleware = PROJECT_ROOT / "apps" / "api" / "middleware" / "security.py"
    if security_middleware.exists():
        passed.append("Security headers middleware exists")
    else:
        failed.append(
            "Security headers middleware missing — create apps/api/middleware/security.py"
        )

    # 6. .env.example exists (no hardcoded secrets)
    env_example = PROJECT_ROOT / ".env.example"
    if env_example.exists():
        passed.append(".env.example exists (secrets template)")
    else:
        failed.append(".env.example missing — required for secret management documentation")

    # 7. .gitignore blocks .env
    gitignore_path = PROJECT_ROOT / ".gitignore"
    if gitignore_path.exists():
        gitignore_content = gitignore_path.read_text()
        if ".env" in gitignore_content:
            passed.append(".gitignore blocks .env files")
        else:
            failed.append(".gitignore does not block .env — risk of secret leakage")
    else:
        failed.append(".gitignore missing — risk of committing secrets")

    # 8. Pre-commit hooks configured
    precommit = PROJECT_ROOT / ".pre-commit-config.yaml"
    if precommit.exists():
        passed.append("Pre-commit hooks configured")
    else:
        failed.append("Pre-commit hooks missing — required for automated security checks")

    # 9. Detect-secrets baseline exists
    secrets_baseline = PROJECT_ROOT / ".secrets.baseline"
    if secrets_baseline.exists():
        passed.append("Detect-secrets baseline exists")
    else:
        failed.append(
            "Detect-secrets baseline missing — run: detect-secrets scan > .secrets.baseline"
        )

    # 10. Tenant configuration exists
    tenants_yaml = PROJECT_ROOT / "tenants.yaml"
    if tenants_yaml.exists():
        passed.append("Tenant configuration exists (tenants.yaml)")
    else:
        failed.append("tenants.yaml missing — required for multi-tenant isolation")

    # 11. Migration directory exists
    migrations_dir = PROJECT_ROOT / "migrations"
    if migrations_dir.exists():
        passed.append("Database migrations directory exists")
    else:
        failed.append(
            "Migrations directory missing — required for auditable schema changes"
        )

    # 12. NDPA compliance documentation
    compliance_doc = PROJECT_ROOT / "docs" / "decisions"
    if compliance_doc.exists():
        passed.append("Architecture Decision Records directory exists")
    else:
        failed.append("ADR directory missing — required for compliance documentation")

    # 13. AWS region check in Terraform
    terraform_dir = PROJECT_ROOT / "infrastructure" / "terraform"
    if terraform_dir.exists():
        for tf_file in terraform_dir.glob("*.tf"):
            content = tf_file.read_text()
            if "af-south-1" in content:
                passed.append(
                    "Terraform uses af-south-1 (Cape Town) — data sovereignty compliant"
                )
                break
        else:
            failed.append(
                "Terraform does not reference af-south-1 — "
                "NDPA requires Nigerian data in approved region"
            )
    else:
        failed.append("Terraform infrastructure directory missing")

    return passed, failed


def main() -> None:
    """Entry point for compliance checker."""
    parser = argparse.ArgumentParser(
        description="Run compliance checks for EconomicBridge"
    )
    parser.add_argument(
        "--framework",
        required=True,
        choices=["ndpa2023"],
        help="Compliance framework to check against",
    )
    args = parser.parse_args()

    if args.framework == "ndpa2023":
        print("\n═══════════════════════════════════════════════════════")
        print("  EconomicBridge — NDPA 2023 Compliance Check")
        print("═══════════════════════════════════════════════════════\n")

        passed, failed = check_ndpa2023()

        if passed:
            print("PASSED:")
            for item in passed:
                print(f"  ✓ {item}")

        if failed:
            print(f"\nFAILED ({len(failed)}):")
            for item in failed:
                print(f"  ✗ {item}")

        total = len(passed) + len(failed)
        score = (len(passed) / total * 100) if total > 0 else 0

        print(f"\n{'─' * 55}")
        print(f"  Score: {len(passed)}/{total} ({score:.0f}%)")
        print(f"  Status: {'PASS' if not failed else 'FAIL — fix items above'}")
        print()

        if failed:
            sys.exit(1)


if __name__ == "__main__":
    main()
