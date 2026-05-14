#!/usr/bin/env python3
"""
Prompt Lister — EconomicBridge
================================
Lists all saved AI prompt versions from the prompt index.

Usage:
    python scripts/list_prompts.py
    make prompt-list
"""

import json
import sys
from pathlib import Path


INDEX_FILE = Path(__file__).parent.parent / "prompts" / "index.json"


def main() -> None:
    """Entry point for prompt listing."""
    if not INDEX_FILE.exists():
        print("No prompts saved yet.")
        print("Save your first prompt with: make prompt-save DESC=\"description\"")
        return

    with open(INDEX_FILE) as f:
        index = json.load(f)

    if not index:
        print("No prompts saved yet.")
        return

    print(f"\n{'ID':>6}  {'Date':>19}  {'Model':<20}  {'Description'}")
    print("─" * 80)

    for entry in index:
        version = entry.get("version", "?")
        timestamp = entry.get("timestamp", "?")[:19]
        model = entry.get("model", "?")
        description = entry.get("description", "?")
        files = entry.get("files_generated", [])

        print(f"{version:>6}  {timestamp:>19}  {model:<20}  {description}")
        if files:
            print(f"        Files: {', '.join(files)}")

    print(f"\nTotal: {len(index)} prompt(s)")
    print()


if __name__ == "__main__":
    main()
