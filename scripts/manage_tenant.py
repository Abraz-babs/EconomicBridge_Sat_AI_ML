#!/usr/bin/env python3
"""
Tenant Manager — EconomicBridge
=================================
Manages tenant lifecycle: activate, deactivate, show status.

Usage:
    python scripts/manage_tenant.py --tenant-id kebbi --action deactivate
    python scripts/manage_tenant.py --tenant-id kebbi --action activate
    python scripts/manage_tenant.py --tenant-id kebbi --action status
    make tenant-deactivate TENANT=kebbi
"""

import argparse
import sys
from pathlib import Path

import yaml


TENANTS_FILE = Path(__file__).parent.parent / "tenants.yaml"

VALID_ACTIONS = {"activate", "deactivate", "status"}


def load_tenants_raw() -> tuple[dict, str]:
    """Load tenants.yaml and return both parsed data and raw text.

    Returns:
        Tuple of (parsed config dict, raw file content string).
    """
    if not TENANTS_FILE.exists():
        print(f"✗ tenants.yaml not found at {TENANTS_FILE}")
        sys.exit(1)
    raw = TENANTS_FILE.read_text()
    return yaml.safe_load(raw), raw


def save_tenants(raw_content: str, tenant_id: str, new_active: bool) -> None:
    """Update the active flag for a tenant in tenants.yaml.

    Uses simple text replacement to preserve YAML formatting and comments.

    Args:
        raw_content: The original file content.
        tenant_id: The tenant to update.
        new_active: The new active state.
    """
    # Find the tenant block and update active field
    lines = raw_content.split("\n")
    in_tenant = False
    updated = False

    for i, line in enumerate(lines):
        if f"id: {tenant_id}" in line and "already_above" not in line:
            in_tenant = True
            continue

        if in_tenant:
            # Check if we've moved to the next tenant
            if line.strip().startswith("- id:"):
                break

            if "active:" in line:
                old_val = "true" if not new_active else "false"
                new_val = "true" if new_active else "false"
                lines[i] = line.replace(f"active: {old_val}", f"active: {new_val}")
                updated = True
                break

    if updated:
        TENANTS_FILE.write_text("\n".join(lines))
    else:
        print(f"✗ Could not find 'active' field for tenant '{tenant_id}'")
        sys.exit(1)


def show_status(tenant: dict) -> None:
    """Display current status of a tenant.

    Args:
        tenant: Tenant configuration dictionary.
    """
    print(f"\n  Tenant: {tenant['name']}")
    print(f"  ID: {tenant['id']}")
    print(f"  Type: {tenant.get('type', '?')}")
    print(f"  Active: {'Yes' if tenant.get('active') else 'No'}")
    print(f"  Phase: {tenant.get('deployment_phase', '?')}")
    print(f"  Risk: {tenant.get('conflict_risk', '?')}")
    print(f"  ROI: {tenant.get('satellite_roi', '?')}")
    if tenant.get("notes"):
        print(f"  Notes: {tenant['notes']}")
    print()


def main() -> None:
    """Entry point for tenant management script."""
    parser = argparse.ArgumentParser(
        description="Manage EconomicBridge tenant lifecycle"
    )
    parser.add_argument(
        "--tenant-id", required=True,
        help="Tenant ID from tenants.yaml",
    )
    parser.add_argument(
        "--action", required=True,
        choices=sorted(VALID_ACTIONS),
        help="Action to perform",
    )
    args = parser.parse_args()

    config, raw = load_tenants_raw()
    tenants = config.get("tenants", [])
    tenant = next((t for t in tenants if t.get("id") == args.tenant_id), None)

    if tenant is None:
        print(f"✗ Tenant '{args.tenant_id}' not found in tenants.yaml")
        sys.exit(1)

    if args.action == "status":
        show_status(tenant)

    elif args.action == "activate":
        if tenant.get("active"):
            print(f"ℹ Tenant '{args.tenant_id}' is already active.")
        else:
            save_tenants(raw, args.tenant_id, new_active=True)
            print(f"✓ Tenant '{args.tenant_id}' ({tenant['name']}) activated.")

    elif args.action == "deactivate":
        if not tenant.get("active"):
            print(f"ℹ Tenant '{args.tenant_id}' is already inactive.")
        else:
            save_tenants(raw, args.tenant_id, new_active=False)
            print(f"✓ Tenant '{args.tenant_id}' ({tenant['name']}) deactivated.")
            print("  ⚠ Note: Deactivation stops new data ingestion.")
            print("  Existing data and schema are preserved.")


if __name__ == "__main__":
    main()
