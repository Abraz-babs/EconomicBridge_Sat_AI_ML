#!/usr/bin/env python3
"""Populate AWS Secrets Manager from the repo-root .env.

Run this AFTER `terraform apply` (which creates the empty secret resources).
It reads each provider key from .env and pushes it to the matching secret
under /<project>/<env>/<path>, so the ECS tasks get real credentials at
task-start. Empty / placeholder values are skipped (left as PLACEHOLDER_NOT_SET).

Secrets never touch tfvars or Terraform state — Terraform owns the secret's
existence + access policy; this script owns the value (CLAUDE.md §4.1).

Usage (from infrastructure/terraform/):
    python populate_secrets.py                 # staging, profile economicbridge
    python populate_secrets.py --env production --profile economicbridge

Values are masked in output; the real strings only pass to the AWS CLI.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

PROJECT = "economicbridge"

# Secret path (must match locals.tf secret_paths) → the .env var holding its value.
PATH_TO_ENV_VAR: dict[str, str] = {
    "copernicus/client_id": "COPERNICUS_CLIENT_ID",
    "copernicus/client_secret": "COPERNICUS_CLIENT_SECRET",
    "nasa_firms/api_key": "NASA_FIRMS_MAP_KEY",
    "n2yo/api_key": "N2YO_API_KEY",
    "earth_engine/service_account": "GEE_SERVICE_ACCOUNT",
    "mapbox/public_token": "NEXT_PUBLIC_MAPBOX_TOKEN",
    "claude/api_key": "ANTHROPIC_API_KEY",
    "termii/api_key": "TERMII_API_KEY",
    "twilio/account_sid": "TWILIO_ACCOUNT_SID",
    "twilio/auth_token": "TWILIO_AUTH_TOKEN",
    "giga/api_key": "GIGA_API_KEY",
    "earthdata/token": "EARTHDATA_TOKEN",
}

# SNS (Nigerian SMS) uses the ECS task role, not a stored secret — nothing here.


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="staging")
    ap.add_argument("--profile", default="economicbridge")
    ap.add_argument("--region", default="eu-west-1")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        print(f"ERROR: {env_path} not found", file=sys.stderr)
        return 1
    values = dotenv_values(env_path)

    pushed = skipped = failed = 0
    for path, var in PATH_TO_ENV_VAR.items():
        secret_id = f"/{PROJECT}/{args.env}/{path}"
        val = (values.get(var) or "").strip()
        if not val or val == "PLACEHOLDER_NOT_SET":
            print(f"  skip  {secret_id:50} ({var} empty)")
            skipped += 1
            continue
        masked = f"set, len={len(val)}"
        if args.dry_run:
            print(f"  DRY   {secret_id:50} <- {var} [{masked}]")
            pushed += 1
            continue
        cmd = [
            "aws", "secretsmanager", "put-secret-value",
            "--secret-id", secret_id,
            "--secret-string", val,
            "--profile", args.profile,
            "--region", args.region,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  ok    {secret_id:50} <- {var} [{masked}]")
            pushed += 1
        else:
            print(f"  FAIL  {secret_id:50} :: {result.stderr.strip()[:120]}")
            failed += 1

    print(f"\nsummary: pushed={pushed} skipped={skipped} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
