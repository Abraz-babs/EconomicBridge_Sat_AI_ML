#!/usr/bin/env python3
"""
Migration Runner — EconomicBridge
===================================
Runs Alembic migrations against one or all active tenants.
Sets the PostgreSQL search_path per tenant before migrating.

Usage:
    python scripts/run_migrations.py --all-tenants
    python scripts/run_migrations.py --tenant-id kebbi
    python scripts/run_migrations.py --all-tenants --downgrade -1
    make migrate
    make migrate-tenant TENANT=kebbi
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

import yaml


TENANTS_FILE = Path(__file__).parent.parent / "tenants.yaml"
ALEMBIC_DIR = Path(__file__).parent.parent / "migrations"
ALEMBIC_INI = Path(__file__).parent.parent / "alembic.ini"


def load_tenants() -> dict:
    """Load and parse the tenants.yaml configuration file."""
    if not TENANTS_FILE.exists():
        print(f"✗ tenants.yaml not found at {TENANTS_FILE}")
        sys.exit(1)
    with open(TENANTS_FILE) as f:
        return yaml.safe_load(f)


def get_active_tenants() -> list[dict]:
    """Return all tenants with active=true."""
    config = load_tenants()
    return [t for t in config.get("tenants", []) if t.get("active", False)]


def get_tenant(tenant_id: str) -> dict | None:
    """Find a specific tenant by ID."""
    config = load_tenants()
    for tenant in config.get("tenants", []):
        if tenant.get("id") == tenant_id:
            return tenant
    return None


def run_alembic_for_tenant(
    tenant_id: str,
    direction: str = "upgrade",
    revision: str = "head",
) -> bool:
    """Run Alembic migration for a specific tenant schema.

    Args:
        tenant_id: The tenant identifier.
        direction: 'upgrade' or 'downgrade'.
        revision: Target revision (default: 'head' for upgrade).

    Returns:
        True if migration succeeded, False otherwise.
    """
    schema_name = f"tenant_{tenant_id}"
    database_url = os.environ.get("DATABASE_URL", "")

    if not database_url:
        print("✗ DATABASE_URL environment variable not set")
        return False

    # Set the schema via env var for Alembic env.py to pick up
    env = os.environ.copy()
    env["TENANT_SCHEMA"] = schema_name
    env["DATABASE_URL"] = database_url

    cmd = [
        "alembic",
        "-c", str(ALEMBIC_INI),
        direction,
        revision,
    ]

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            cwd=str(ALEMBIC_DIR.parent),
        )
        if result.returncode == 0:
            print(f"  ✓ {direction} {revision} — {schema_name}")
            return True
        else:
            print(f"  ✗ {direction} failed for {schema_name}:")
            print(f"    {result.stderr.strip()}")
            return False
    except FileNotFoundError:
        print("✗ Alembic not found. Install with: pip install alembic")
        return False


def main() -> None:
    """Entry point for migration runner."""
    parser = argparse.ArgumentParser(
        description="Run Alembic migrations for EconomicBridge tenants"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all-tenants", action="store_true", help="Migrate all active tenants")
    group.add_argument("--tenant-id", help="Migrate a specific tenant")

    parser.add_argument(
        "--downgrade",
        metavar="REVISION",
        help="Downgrade to revision (e.g., '-1' for one step back)",
    )
    args = parser.parse_args()

    direction = "downgrade" if args.downgrade else "upgrade"
    revision = args.downgrade if args.downgrade else "head"

    if args.all_tenants:
        tenants = get_active_tenants()
        if not tenants:
            print("⚠ No active tenants found in tenants.yaml")
            sys.exit(0)

        print(f"→ Running {direction} ({revision}) for {len(tenants)} active tenant(s)...\n")
        success_count = 0
        fail_count = 0

        for tenant in tenants:
            ok = run_alembic_for_tenant(tenant["id"], direction, revision)
            if ok:
                success_count += 1
            else:
                fail_count += 1

        print(f"\n{'✓' if fail_count == 0 else '✗'} "
              f"Complete: {success_count} succeeded, {fail_count} failed.")
        if fail_count > 0:
            sys.exit(1)
    else:
        tenant = get_tenant(args.tenant_id)
        if tenant is None:
            print(f"✗ Tenant '{args.tenant_id}' not found in tenants.yaml")
            sys.exit(1)

        print(f"→ Running {direction} ({revision}) for tenant '{args.tenant_id}'...")
        ok = run_alembic_for_tenant(args.tenant_id, direction, revision)
        if not ok:
            sys.exit(1)


if __name__ == "__main__":
    main()
