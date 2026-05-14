#!/usr/bin/env python3
"""
Tenant Validator — EconomicBridge
==================================
Validates tenant configuration from tenants.yaml.
Checks required fields, satellite ROI bounds, and configuration consistency.

Usage:
    python scripts/validate_tenant.py --tenant-id kebbi
    python scripts/validate_tenant.py --all
    make tenant-validate TENANT=kebbi
"""

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml


TENANTS_FILE = Path(__file__).parent.parent / "tenants.yaml"

REQUIRED_FIELDS = [
    "id", "name", "type", "country", "capital",
    "language", "sms_gateway", "satellite_roi",
    "conflict_risk", "priority", "deployment_phase",
]

VALID_TYPES = {"ng_state", "ng_fct", "ecowas_country"}
VALID_LANGUAGES = {"en", "fr", "pt", "yo", "ig", "ha"}
VALID_SMS_GATEWAYS = {"termii", "twilio"}
VALID_CONFLICT_RISKS = {"low", "medium", "high", "critical"}


def load_tenants() -> dict:
    """Load and parse the tenants.yaml configuration file."""
    if not TENANTS_FILE.exists():
        print(f"✗ tenants.yaml not found at {TENANTS_FILE}")
        sys.exit(1)
    with open(TENANTS_FILE) as f:
        return yaml.safe_load(f)


def validate_roi(roi: list[float], tenant_id: str) -> list[str]:
    """Validate satellite region of interest bounding box.

    Args:
        roi: List of [min_lon, min_lat, max_lon, max_lat].
        tenant_id: Tenant identifier for error messages.

    Returns:
        List of validation error messages (empty if valid).
    """
    errors: list[str] = []

    if not isinstance(roi, list) or len(roi) != 4:
        errors.append(f"  [{tenant_id}] satellite_roi must be [min_lon, min_lat, max_lon, max_lat]")
        return errors

    min_lon, min_lat, max_lon, max_lat = roi

    if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
        errors.append(f"  [{tenant_id}] longitude out of range [-180, 180]: {min_lon}, {max_lon}")
    if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
        errors.append(f"  [{tenant_id}] latitude out of range [-90, 90]: {min_lat}, {max_lat}")
    if min_lon >= max_lon:
        errors.append(f"  [{tenant_id}] min_lon ({min_lon}) must be < max_lon ({max_lon})")
    if min_lat >= max_lat:
        errors.append(f"  [{tenant_id}] min_lat ({min_lat}) must be < max_lat ({max_lat})")

    return errors


def validate_tenant(tenant: dict[str, Any]) -> list[str]:
    """Validate a single tenant configuration.

    Args:
        tenant: Tenant config dictionary from tenants.yaml.

    Returns:
        List of validation error messages (empty if valid).
    """
    errors: list[str] = []
    tenant_id = tenant.get("id", "(unknown)")

    # Check required fields
    for field in REQUIRED_FIELDS:
        if field not in tenant:
            errors.append(f"  [{tenant_id}] Missing required field: {field}")

    # Skip further validation if essential fields missing
    if "id" not in tenant:
        return errors

    # Validate type
    if tenant.get("type") not in VALID_TYPES:
        errors.append(
            f"  [{tenant_id}] Invalid type '{tenant.get('type')}'. "
            f"Must be one of: {', '.join(sorted(VALID_TYPES))}"
        )

    # Validate language
    if tenant.get("language") not in VALID_LANGUAGES:
        errors.append(
            f"  [{tenant_id}] Invalid language '{tenant.get('language')}'. "
            f"Must be one of: {', '.join(sorted(VALID_LANGUAGES))}"
        )

    # Validate SMS gateway
    if tenant.get("sms_gateway") not in VALID_SMS_GATEWAYS:
        errors.append(
            f"  [{tenant_id}] Invalid sms_gateway '{tenant.get('sms_gateway')}'. "
            f"Must be one of: {', '.join(sorted(VALID_SMS_GATEWAYS))}"
        )

    # Validate conflict risk
    if tenant.get("conflict_risk") not in VALID_CONFLICT_RISKS:
        errors.append(
            f"  [{tenant_id}] Invalid conflict_risk '{tenant.get('conflict_risk')}'. "
            f"Must be one of: {', '.join(sorted(VALID_CONFLICT_RISKS))}"
        )

    # Validate satellite ROI
    if "satellite_roi" in tenant:
        errors.extend(validate_roi(tenant["satellite_roi"], tenant_id))

    # Validate priority is positive integer
    priority = tenant.get("priority")
    if priority is not None and (not isinstance(priority, int) or priority < 1):
        errors.append(f"  [{tenant_id}] priority must be a positive integer, got: {priority}")

    # Validate deployment_phase
    phase = tenant.get("deployment_phase")
    if phase is not None and (not isinstance(phase, int) or phase < 1):
        errors.append(f"  [{tenant_id}] deployment_phase must be a positive integer, got: {phase}")

    # ECOWAS tenants should use twilio (international)
    if tenant.get("type") == "ecowas_country" and tenant.get("sms_gateway") != "twilio":
        errors.append(
            f"  [{tenant_id}] ECOWAS country should use 'twilio' SMS gateway, "
            f"got: '{tenant.get('sms_gateway')}'"
        )

    return errors


def main() -> None:
    """Entry point for tenant validation script."""
    parser = argparse.ArgumentParser(
        description="Validate EconomicBridge tenant configuration"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tenant-id", help="Validate a specific tenant")
    group.add_argument("--all", action="store_true", help="Validate all tenants")
    args = parser.parse_args()

    config = load_tenants()
    tenants = config.get("tenants", [])

    if args.tenant_id:
        tenant = next((t for t in tenants if t.get("id") == args.tenant_id), None)
        if tenant is None:
            print(f"✗ Tenant '{args.tenant_id}' not found in tenants.yaml")
            sys.exit(1)
        tenants_to_validate = [tenant]
    else:
        tenants_to_validate = tenants

    all_errors: list[str] = []
    validated_count = 0

    for tenant in tenants_to_validate:
        errors = validate_tenant(tenant)
        if errors:
            all_errors.extend(errors)
        else:
            validated_count += 1

    if all_errors:
        print(f"\n✗ Validation failed with {len(all_errors)} error(s):\n")
        for error in all_errors:
            print(error)
        print(f"\n  {validated_count} tenant(s) passed, {len(all_errors)} error(s) found.")
        sys.exit(1)
    else:
        print(f"✓ All {validated_count} tenant(s) passed validation.")


if __name__ == "__main__":
    main()
