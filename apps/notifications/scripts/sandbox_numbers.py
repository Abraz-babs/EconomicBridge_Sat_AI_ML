"""Add cooperative phone numbers to the SNS SMS sandbox, and check who is verified.

While the AWS account is in the SMS sandbox, SNS will only deliver to numbers
that have been verified with a one-time code. That cap is 10 destination
numbers, which is enough for a cooperative-leader pilot and has one real
advantage over the production path: every recipient has explicitly consented by
entering a code, which is cleaner under NDPR than a bulk list.

    python apps/notifications/scripts/sandbox_numbers.py --list
    python apps/notifications/scripts/sandbox_numbers.py --add +2348012345678
    python apps/notifications/scripts/sandbox_numbers.py --verify +2348012345678 123456

Numbers must be E.164: +234 then the number WITHOUT its leading zero.
0801 234 5678  ->  +2348012345678

The recipient receives the code by SMS and reads it back to you; --verify then
completes the pairing. Codes expire, so add and verify in the same sitting.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def aws(*args: str) -> tuple[int, str]:
    """Run an AWS CLI command in the project's usual profile/region."""
    cmd = ["aws", *args, "--profile", "economicbridge", "--region", "eu-west-1"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def normalise(raw: str) -> str:
    """Accept 08012345678 / 234801... / +234801... and return E.164.

    Nigerian numbers are habitually written with a leading 0, which is a
    national-format artefact: +2340801... is not a valid number and SNS
    rejects it in a way that reads like a service fault rather than a typo.
    """
    s = re.sub(r"[^\d+]", "", raw)
    if s.startswith("+"):
        return s
    if s.startswith("0"):
        return "+234" + s[1:]
    if s.startswith("234"):
        return "+" + s
    return "+234" + s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--add", metavar="NUMBER")
    ap.add_argument("--verify", nargs=2, metavar=("NUMBER", "CODE"))
    args = ap.parse_args()

    if args.list:
        rc, out = aws("sns", "list-sms-sandbox-phone-numbers", "--output", "table")
        print(out)
        rc2, st = aws("sns", "get-sms-sandbox-account-status", "--output", "text")
        print(f"sandbox: {st.strip()}   (False = production, no verification needed)")
        return rc or rc2

    if args.add:
        num = normalise(args.add)
        if not E164.match(num):
            print(f"'{args.add}' -> '{num}' is not valid E.164"); return 1
        print(f"adding {num} ...")
        rc, out = aws("sns", "create-sms-sandbox-phone-number",
                      "--phone-number", num, "--language-code", "en-US")
        print(out or "  requested")
        if rc == 0:
            print(f"  {num} will receive a code by SMS.")
            print(f"  Then: --verify {num} <code>")
        return rc

    if args.verify:
        num, code = normalise(args.verify[0]), args.verify[1].strip()
        rc, out = aws("sns", "verify-sms-sandbox-phone-number",
                      "--phone-number", num, "--one-time-password", code)
        print(out or f"  {num} verified")
        return rc

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
