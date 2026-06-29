#!/usr/bin/env bash
# One-shot ECS migration runner — applies Alembic migrations to the deployed
# (private) RDS without a bastion or a public DB endpoint.
#
# How it works: RDS lives in private subnets, reachable only from inside the
# VPC. Rather than tunnel in, we launch a throwaway Fargate task that reuses the
# *api* task definition (same image, same DATABASE_URL secret, same subnets +
# security group as the running api) but overrides the container command to run
# `alembic upgrade head`. The task starts, migrates, prints its output to the
# api log group, and exits. The deploy pipeline does NOT run migrations, so this
# is the supported way to apply a new migration to staging/production.
#
# The image used is whatever the api service's task definition points at
# (:latest), so run this AFTER the Deploy workflow has built + pushed the image
# containing the new migration.
#
# Usage:
#   scripts/ecs_migrate.sh [staging|production]      # default: staging
#   AWS_PROFILE=economicbridge scripts/ecs_migrate.sh staging
#
# Requires AWS credentials with ecs:RunTask / DescribeTasks / DescribeServices,
# iam:PassRole on the api task roles, and logs:GetLogEvents. The
# economicbridge-deployer user has these.
set -euo pipefail

# Git Bash on Windows rewrites leading-slash args (e.g. the /ecs/... log group)
# into Windows paths; this disables that so the log fetch works everywhere.
export MSYS_NO_PATHCONV=1

ENVIRONMENT="${1:-staging}"
PROJECT="economicbridge"
REGION="${AWS_REGION:-eu-west-1}"
if [ "$ENVIRONMENT" = "production" ]; then
  REGION="${AWS_REGION:-af-south-1}"
fi

CLUSTER="${PROJECT}-${ENVIRONMENT}-cluster"
SERVICE="${PROJECT}-${ENVIRONMENT}-api"   # also the task-definition family
CONTAINER="api"
LOG_GROUP="/ecs/${PROJECT}-${ENVIRONMENT}/api"

q() { aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" \
        --region "$REGION" --query "$1" --output text ; }

echo "→ [$ENVIRONMENT] resolving network config from $SERVICE ..."
NETQ='services[0].networkConfiguration.awsvpcConfiguration'
SUBNETS=$(q "$NETQ.subnets" | tr '\t' ',')
SGS=$(q "$NETQ.securityGroups" | tr '\t' ',')
PUBIP=$(q "$NETQ.assignPublicIp")
if [ -z "$SUBNETS" ] || [ "$SUBNETS" = "None" ]; then
  echo "✗ Could not resolve subnets for $SERVICE in $CLUSTER ($REGION)." >&2
  exit 1
fi
echo "  subnets=$SUBNETS  sg=$SGS  publicIp=$PUBIP"

echo "→ launching migrate task (alembic upgrade head) ..."
ARN=$(aws ecs run-task --cluster "$CLUSTER" --region "$REGION" \
  --task-definition "$SERVICE" \
  --launch-type FARGATE --platform-version LATEST \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SGS],assignPublicIp=$PUBIP}" \
  --overrides '{"containerOverrides":[{"name":"'"$CONTAINER"'","command":["sh","-c","cd /app && alembic -c alembic.ini current && alembic -c alembic.ini upgrade head"]}]}' \
  --started-by "ecs-migrate-$(date +%s)" \
  --query 'tasks[0].taskArn' --output text)
echo "  task: $ARN"
TASKID="${ARN##*/}"

echo "→ waiting for completion ..."
aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$ARN" --region "$REGION"

EXIT=$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$ARN" --region "$REGION" \
  --query 'tasks[0].containers[0].exitCode' --output text)

echo "→ alembic output:"
aws logs get-log-events --region "$REGION" \
  --log-group-name "$LOG_GROUP" --log-stream-name "${CONTAINER}/${CONTAINER}/${TASKID}" \
  --limit 60 --query 'events[].message' --output text 2>/dev/null \
  | tr '\t' '\n' | sed 's/^/    /' || echo "    (logs not available yet)"

if [ "$EXIT" != "0" ]; then
  echo "✗ migration task exited $EXIT" >&2
  exit 1
fi
echo "✓ [$ENVIRONMENT] migrations applied (alembic upgrade head, exit 0)"
