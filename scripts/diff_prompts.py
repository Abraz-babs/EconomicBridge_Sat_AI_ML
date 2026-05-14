#!/usr/bin/env python3
"""
Prompt Diff — EconomicBridge
==============================
Shows the diff between two saved prompt versions.

Usage:
    python scripts/diff_prompts.py --v1 001 --v2 002
    make prompt-diff V1=001 V2=002
"""

import argparse
import difflib
import json
import sys
from pathlib import Path


PROMPTS_DIR = Path(__file__).parent.parent / "prompts" / "versions"
INDEX_FILE = Path(__file__).parent.parent / "prompts" / "index.json"


def find_prompt_file(version_id: str) -> Path | None:
    """Find the prompt file for a given version ID.

    Args:
        version_id: Version identifier (e.g., '001' or '0001').

    Returns:
        Path to the prompt file, or None if not found.
    """
    # Normalize to 4-digit format
    normalized = version_id.zfill(4)

    if not INDEX_FILE.exists():
        return None

    with open(INDEX_FILE) as f:
        index = json.load(f)

    for entry in index:
        if entry.get("version") == normalized:
            filepath = PROMPTS_DIR / entry["filename"]
            if filepath.exists():
                return filepath

    # Fallback: search by glob
    for filepath in PROMPTS_DIR.glob(f"prompt-{normalized}-*"):
        return filepath

    return None


def main() -> None:
    """Entry point for prompt diff tool."""
    parser = argparse.ArgumentParser(
        description="Show diff between two prompt versions"
    )
    parser.add_argument("--v1", required=True, help="First version ID (e.g., 001)")
    parser.add_argument("--v2", required=True, help="Second version ID (e.g., 002)")
    args = parser.parse_args()

    file1 = find_prompt_file(args.v1)
    file2 = find_prompt_file(args.v2)

    if file1 is None:
        print(f"✗ Prompt version '{args.v1}' not found")
        sys.exit(1)
    if file2 is None:
        print(f"✗ Prompt version '{args.v2}' not found")
        sys.exit(1)

    lines1 = file1.read_text().splitlines(keepends=True)
    lines2 = file2.read_text().splitlines(keepends=True)

    diff = difflib.unified_diff(
        lines1, lines2,
        fromfile=f"v{args.v1} ({file1.name})",
        tofile=f"v{args.v2} ({file2.name})",
    )

    output = "".join(diff)
    if output:
        print(output)
    else:
        print(f"No differences between v{args.v1} and v{args.v2}")


if __name__ == "__main__":
    main()
