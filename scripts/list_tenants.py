#!/usr/bin/env python3
"""
Tenant Lister — EconomicBridge
================================
Reads tenants.yaml and displays a formatted table of all configured tenants.

Usage:
    python scripts/list_tenants.py
    make tenant-list
"""

import sys
from pathlib import Path

import yaml


TENANTS_FILE = Path(__file__).parent.parent / "tenants.yaml"


def load_tenants() -> dict:
    """Load and parse the tenants.yaml configuration file."""
    if not TENANTS_FILE.exists():
        print(f"✗ tenants.yaml not found at {TENANTS_FILE}")
        sys.exit(1)
    with open(TENANTS_FILE) as f:
        return yaml.safe_load(f)


def format_status(active: bool) -> str:
    """Format the active status with icon.

    Args:
        active: Whether the tenant is active.

    Returns:
        Formatted status string.
    """
    return "● ACTIVE" if active else "○ inactive"


def format_risk(risk: str) -> str:
    """Format conflict risk level with icon.

    Args:
        risk: Risk level string.

    Returns:
        Formatted risk string.
    """
    icons = {
        "low": "🟢",
        "medium": "🟡",
        "high": "🟠",
        "critical": "🔴",
    }
    return f"{icons.get(risk, '?')} {risk}"


def main() -> None:
    """Entry point for tenant listing script."""
    config = load_tenants()
    tenants = config.get("tenants", [])

    if not tenants:
        print("No tenants configured in tenants.yaml")
        return

    # Header
    print()
    print("EconomicBridge — Tenant Registry")
    print("=" * 95)
    print(
        f"{'ID':<20} {'Name':<25} {'Type':<16} {'Phase':<6} "
        f"{'Risk':<14} {'Status':<12}"
    )
    print("-" * 95)

    # Track counts
    active_count = 0
    total_count = 0
    by_phase: dict[int, int] = {}

    for tenant in tenants:
        tenant_id = tenant.get("id", "?")
        name = tenant.get("name", "?")
        tenant_type = tenant.get("type", "?")
        phase = tenant.get("deployment_phase", "?")
        risk = tenant.get("conflict_risk", "?")
        active = tenant.get("active", False)

        # Skip placeholder entries
        if "already_above" in str(tenant_id):
            continue

        total_count += 1
        if active:
            active_count += 1

        phase_int = phase if isinstance(phase, int) else 0
        by_phase[phase_int] = by_phase.get(phase_int, 0) + 1

        print(
            f"{tenant_id:<20} {name:<25} {tenant_type:<16} {str(phase):<6} "
            f"{format_risk(str(risk)):<14} {format_status(active):<12}"
        )

    # Summary
    print("-" * 95)
    print(f"\nTotal: {total_count} tenants ({active_count} active)")
    for phase_num in sorted(by_phase.keys()):
        if phase_num > 0:
            print(f"  Phase {phase_num}: {by_phase[phase_num]} tenants")
    print()


if __name__ == "__main__":
    main()
