#!/usr/bin/env bash
# Rotate the NASA Earthdata Login token: test the new one, store it, restart
# the services that carry it, and (optionally) rerun the morning jobs that a
# lapsed token has already failed.
#
# Why this is a script and not a checklist: the token expires every ~60 days,
# and on 2026-11-16 the manual rotation took ten steps and still missed two of
# them at first. That morning the 08:00 rainfall advisory and 08:30 storm scan
# had already failed with "ImergAuthError 401", and a service restart does NOT
# re-run them (the scheduler's job store is in memory).
#
# The token NEVER goes on the command line (it would land in shell history and
# the process list). Give it on stdin, or type it at the hidden prompt:
#
#   scripts/rotate_earthdata_token.sh                      # prompts (hidden)
#   scripts/rotate_earthdata_token.sh < new_token.txt
#   scripts/rotate_earthdata_token.sh --dry-run < new_token.txt   # test only
#   scripts/rotate_earthdata_token.sh --rerun-missed < new_token.txt
#
# Steps, in order. Any failure stops the script BEFORE the next step:
#   1. Decode the token (uid + expiry). Refuse one that expires within a day.
#   2. Prove it works: ranged download of a real VIIRS VNP46A2 tile from LAADS.
#      A valid token returns HDF5 bytes; without one LAADS serves an HTML login
#      page. (Do not "test" against urs.earthdata.nasa.gov/api/users/<uid>: it
#      answers 401 even for a valid user token.)
#   3. Store it in Secrets Manager and read it back to compare (never printed).
#   4. Force a new deployment of EVERY service whose task definition carries
#      the secret (found by inspection, not a hard-coded list: today that is
#      api + ingestion) and wait until they are stable.
#   5. Update EARTHDATA_TOKEN in the local .env, if the file has that line.
#   6. --rerun-missed: launch a one-shot ingestion task that reruns today's
#      rainfall advisory (which also runs the farmer SMS dispatch: each advisory
#      is sent at most once, so this cannot double-message) and storm scan.
#      Only use it when those jobs already failed today. Takes 1-2 hours; the
#      script prints the log stream and does not wait.
#
# Scheduled one-shot tasks (e.g. the 09:30 feed-health check) read the secret
# when they start, so they need no action.
#
# Requires: aws CLI (profile with Secrets Manager + ECS rights), curl, python.
set -euo pipefail

# Git Bash on Windows rewrites leading-slash args (the /economicbridge/... id
# and the /ecs/... log group) into Windows paths; this disables that.
export MSYS_NO_PATHCONV=1

DRY_RUN=0
RERUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --rerun-missed) RERUN=1 ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg (the token goes on stdin, not the command line)" >&2; exit 2 ;;
  esac
done

ENVIRONMENT="${ENVIRONMENT:-staging}"
PROJECT="economicbridge"
export AWS_PROFILE="${AWS_PROFILE:-economicbridge}"
export AWS_REGION="${AWS_REGION:-eu-west-1}"
CLUSTER="${PROJECT}-${ENVIRONMENT}-cluster"
SECRET_ID="/${PROJECT}/${ENVIRONMENT}/earthdata/token"
LOG_GROUP="/ecs/${PROJECT}-${ENVIRONMENT}/ingestion"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"

PY=""
for c in python3 python; do
  if "$c" -c 'import sys' >/dev/null 2>&1; then PY="$c"; break; fi
done
[ -n "$PY" ] || { echo "python not found" >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
chmod 700 "$WORK"

# Paths handed to python and curl. On Git Bash both are Windows programs and cannot
# open /tmp/... (MSYS_NO_PATHCONV above stops the automatic rewrite), so give
# it the Windows form; elsewhere this is the path unchanged.
native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }

# --- read the token (stdin or hidden prompt) -------------------------------
if [ -t 0 ]; then
  read -rsp "Paste the new Earthdata token (input hidden): " TOKEN; echo
else
  TOKEN="$(cat)"
fi
TOKEN="$(printf '%s' "$TOKEN" | tr -d '[:space:]')"
[ -n "$TOKEN" ] || { echo "no token given" >&2; exit 1; }
printf '%s' "$TOKEN" > "$WORK/token"
chmod 600 "$WORK/token"

# --- 1. decode ---------------------------------------------------------------
echo "1/6 decoding token"
"$PY" - "$(native "$WORK/token")" <<'EOF'
import base64, datetime as dt, json, sys
tok = open(sys.argv[1]).read().strip()
try:
    body = tok.split(".")[1]; body += "=" * (-len(body) % 4)
    claims = json.loads(base64.urlsafe_b64decode(body))
except Exception:
    sys.exit("    not a readable Earthdata JWT")
exp = dt.datetime.fromtimestamp(int(claims["exp"]), dt.timezone.utc)
days = (exp - dt.datetime.now(dt.timezone.utc)).total_seconds() / 86400
print(f"    user {claims.get('uid')}, expires {exp:%Y-%m-%d %H:%M} UTC ({days:.0f} days)")
if days < 1:
    sys.exit("    refusing: this token expires within a day")
EOF

# --- 2. live test against LAADS ---------------------------------------------
echo "2/6 testing it against NASA LAADS (real VIIRS tile)"
# VNP46A2 days appear on LAADS ~10+ days late (a day 12 days back was still a
# 404 on 2026-11-16), so walk back until a published day is found.
LAADS=""
for back in 14 21 30; do
  DAY_YEAR="$(date -u -d "${back} days ago" +%Y)"
  DAY_DOY="$(date -u -d "${back} days ago" +%j)"
  try="https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/5200/VNP46A2/${DAY_YEAR}/${DAY_DOY}"
  if curl -sf "${try}.json" -o "$(native "$WORK/listing.json")"; then LAADS="$try"; break; fi
done
[ -n "$LAADS" ] || { echo "    could not list any recent VNP46A2 day on LAADS (LAADS down?). Nothing was changed." >&2; exit 1; }
FILE="$("$PY" -c "
import json, sys
d = json.load(open(sys.argv[1]))
d = d.get('content', d) if isinstance(d, dict) else d
names = [x['name'] for x in d if str(x.get('name', '')).endswith('.h5')]
print(names[0] if names else '')
" "$(native "$WORK/listing.json")")"
[ -n "$FILE" ] || { echo "    no .h5 file in the LAADS listing for ${DAY_YEAR}/${DAY_DOY}" >&2; exit 1; }
curl -s -L -r 0-4095 -o "$(native "$WORK/probe.bin")" -H "Authorization: Bearer $(cat "$WORK/token")" "${LAADS}/${FILE}"
if "$PY" -c "import sys; sys.exit(0 if open(sys.argv[1],'rb').read(8) == b'\x89HDF\r\n\x1a\n' else 1)" "$(native "$WORK/probe.bin")"; then
  echo "    OK: NASA returned HDF5 data for ${FILE}"
else
  echo "    FAILED: NASA did not accept this token (got a non-HDF5 response). Nothing was changed." >&2
  exit 1
fi

if [ "$DRY_RUN" = 1 ]; then
  echo "dry run: token is valid; nothing stored, nothing restarted"
  exit 0
fi

# --- 3. store + read back ----------------------------------------------------
echo "3/6 storing in Secrets Manager ${SECRET_ID}"
# Relative file:// path from inside the work dir: works for both Linux aws and
# the Windows aws.exe that Git Bash calls (which cannot read /tmp/... paths).
( cd "$WORK" && aws secretsmanager put-secret-value --secret-id "$SECRET_ID" \
    --secret-string file://token --query VersionId --output text >/dev/null )
STORED="$(aws secretsmanager get-secret-value --secret-id "$SECRET_ID" --query SecretString --output text | tr -d '\r\n')"
[ "$STORED" = "$TOKEN" ] || { echo "    read-back does not match: stop and check the secret" >&2; exit 1; }
unset STORED
echo "    stored and verified"

# --- 4. restart every service that carries the secret ------------------------
echo "4/6 restarting the services that carry the secret"
SERVICES=()
for arn in $(aws ecs list-services --cluster "$CLUSTER" --query 'serviceArns' --output text | tr -d '\r'); do
  svc="${arn##*/}"
  td="$(aws ecs describe-services --cluster "$CLUSTER" --services "$svc" --query 'services[0].taskDefinition' --output text | tr -d '\r')"
  if aws ecs describe-task-definition --task-definition "$td" \
       --query 'taskDefinition.containerDefinitions[].secrets[].valueFrom' --output text | grep -q 'earthdata'; then
    SERVICES+=("$svc")
  fi
done
[ "${#SERVICES[@]}" -gt 0 ] || { echo "    no service carries the secret: check the task definitions" >&2; exit 1; }
for svc in "${SERVICES[@]}"; do
  aws ecs update-service --cluster "$CLUSTER" --service "$svc" --force-new-deployment \
    --query 'service.serviceName' --output text >/dev/null
  echo "    redeploying ${svc}"
done
aws ecs wait services-stable --cluster "$CLUSTER" --services "${SERVICES[@]}"
echo "    all stable"

# --- 5. local .env -------------------------------------------------------------
echo "5/6 local .env"
if [ -f "$ENV_FILE" ] && grep -q '^[[:space:]]*EARTHDATA_TOKEN[[:space:]]*=' "$ENV_FILE"; then
  "$PY" - "$(native "$ENV_FILE")" "$(native "$WORK/token")" <<'EOF'
import re, sys
path, tok = sys.argv[1], open(sys.argv[2]).read().strip()
text = open(path, encoding="utf-8").read()
text = re.sub(r"(?m)^(\s*EARTHDATA_TOKEN\s*=\s*).*$", lambda m: m.group(1) + tok, text)
open(path, "w", encoding="utf-8", newline="").write(text)
EOF
  echo "    updated ${ENV_FILE}"
else
  echo "    no EARTHDATA_TOKEN line in ${ENV_FILE}: skipped"
fi

# --- 6. rerun today's failed jobs (opt-in) ------------------------------------
if [ "$RERUN" = 1 ]; then
  echo "6/6 rerunning today's rainfall advisory and storm scan (one-shot task)"
  NET="$(aws ecs describe-services --cluster "$CLUSTER" --services "${PROJECT}-${ENVIRONMENT}-ingestion" \
         --query 'services[0].networkConfiguration.awsvpcConfiguration' --output json)"
  NETCFG="$("$PY" -c "
import json, sys
n = json.loads(sys.argv[1])
print('awsvpcConfiguration={subnets=[%s],securityGroups=[%s],assignPublicIp=%s}' % (
    ','.join(n['subnets']), ','.join(n['securityGroups']), n.get('assignPublicIp', 'ENABLED')))
" "$NET")"
  # trigger must be one of manual|scheduled|backfill (chk_ingestion_runs_trigger)
  OVERRIDES="$("$PY" -c "
import json
code = '''import asyncio, logging
logging.basicConfig(level=logging.INFO)
for n in (\"httpx\", \"httpcore\"):
    logging.getLogger(n).setLevel(logging.WARNING)
from tasks.rainstorm_scan import run_rainfall_scan
from tasks.storm_scan import run_storm_scan
async def main():
    await run_rainfall_scan()
    print(\"storm scan:\", await run_storm_scan(trigger=\"manual\"), flush=True)
asyncio.run(main())'''
print(json.dumps({'containerOverrides': [{'name': 'ingestion',
    'command': ['python', '-c', code],
    'environment': [{'name': 'PYTHONPATH', 'value': '/app'}]}]}))
")"
  TASK="$(aws ecs run-task --cluster "$CLUSTER" --launch-type FARGATE \
          --task-definition "${PROJECT}-${ENVIRONMENT}-ingestion" \
          --network-configuration "$NETCFG" --overrides "$OVERRIDES" \
          --started-by earthdata-rotation --query 'tasks[0].taskArn' --output text | tr -d '\r')"
  TASK_ID="${TASK##*/}"
  echo "    task ${TASK_ID} started (1-2 hours). Follow it with:"
  echo "    aws logs get-log-events --log-group-name ${LOG_GROUP} --log-stream-name ingestion/ingestion/${TASK_ID} --query 'events[].message' --output text"
else
  echo "6/6 no rerun requested (use --rerun-missed if today's 08:00/08:30 jobs already failed)"
fi

echo "done: next expiry is printed in step 1; renew a few days before it"
