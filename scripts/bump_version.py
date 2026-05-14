#!/usr/bin/env python3
"""
Version Bumper — EconomicBridge
=================================
Bumps the semantic version in apps/api/VERSION.

Usage:
    python scripts/bump_version.py --type patch   # 0.1.0 → 0.1.1
    python scripts/bump_version.py --type minor   # 0.1.0 → 0.2.0
    python scripts/bump_version.py --type major   # 0.1.0 → 1.0.0
    make bump-version TYPE=patch
"""

import argparse
import sys
from pathlib import Path


VERSION_FILE = Path(__file__).parent.parent / "apps" / "api" / "VERSION"


def read_version() -> str:
    """Read the current version from VERSION file.

    Returns:
        Current version string (e.g., '0.1.0').
    """
    if not VERSION_FILE.exists():
        print(f"✗ VERSION file not found at {VERSION_FILE}")
        sys.exit(1)
    return VERSION_FILE.read_text().strip()


def parse_version(version_str: str) -> tuple[int, int, int]:
    """Parse a semver string into (major, minor, patch).

    Args:
        version_str: Version string like '0.1.0'.

    Returns:
        Tuple of (major, minor, patch) integers.
    """
    parts = version_str.split(".")
    if len(parts) != 3:
        print(f"✗ Invalid version format: '{version_str}'. Expected: MAJOR.MINOR.PATCH")
        sys.exit(1)

    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        print(f"✗ Version parts must be integers: '{version_str}'")
        sys.exit(1)


def bump_version(current: str, bump_type: str) -> str:
    """Bump the version according to the specified type.

    Args:
        current: Current version string.
        bump_type: One of 'major', 'minor', 'patch'.

    Returns:
        New version string.
    """
    major, minor, patch = parse_version(current)

    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    elif bump_type == "patch":
        return f"{major}.{minor}.{patch + 1}"
    else:
        print(f"✗ Unknown bump type: '{bump_type}'")
        sys.exit(1)


def main() -> None:
    """Entry point for version bumper."""
    parser = argparse.ArgumentParser(description="Bump EconomicBridge version")
    parser.add_argument(
        "--type",
        required=True,
        choices=["major", "minor", "patch"],
        help="Version component to bump",
    )
    args = parser.parse_args()

    current = read_version()
    new_version = bump_version(current, args.type)

    VERSION_FILE.write_text(new_version + "\n")

    print(f"✓ Version bumped: {current} → {new_version}")
    print(f"  File: {VERSION_FILE}")


if __name__ == "__main__":
    main()
