#!/usr/bin/env bash
# deploy.sh — EconomicBridge Deployment Script
# ==============================================
# Builds Docker images, pushes to ECR, and updates ECS services.
#
# Usage:
#   ./scripts/deploy.sh staging
#   ./scripts/deploy.sh production
#   make deploy-staging
#   make deploy-production

set -euo pipefail

ENVIRONMENT="${1:-}"
AWS_REGION="${AWS_REGION:-af-south-1}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-}"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
PROJECT_NAME="economicbridge"
VERSION=$(cat apps/api/VERSION 2>/dev/null || echo "0.1.0")

# ─────────────────────────────────────────
# Validation
# ─────────────────────────────────────────

if [ -z "$ENVIRONMENT" ]; then
    echo "✗ Usage: ./scripts/deploy.sh <staging|production>"
    exit 1
fi

if [ "$ENVIRONMENT" != "staging" ] && [ "$ENVIRONMENT" != "production" ]; then
    echo "✗ Environment must be 'staging' or 'production', got: '${ENVIRONMENT}'"
    exit 1
fi

if [ -z "$AWS_ACCOUNT_ID" ]; then
    echo "✗ AWS_ACCOUNT_ID environment variable not set."
    echo "  Set it in .env or export before running."
    exit 1
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  EconomicBridge — Deploying to ${ENVIRONMENT^^}"
echo "  Version: ${VERSION}"
echo "  Region:  ${AWS_REGION}"
echo "  Time:    $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "═══════════════════════════════════════════════════════"
echo ""

# ─────────────────────────────────────────
# Production safety check
# ─────────────────────────────────────────

if [ "$ENVIRONMENT" = "production" ]; then
    echo "⚠️  PRODUCTION DEPLOYMENT"
    echo "   This will affect live tenants and real users."
    read -p "   Type 'deploy-production' to confirm: " confirm
    if [ "$confirm" != "deploy-production" ]; then
        echo "✗ Deployment cancelled."
        exit 1
    fi
fi

# ─────────────────────────────────────────
# Step 1: Authenticate with ECR
# ─────────────────────────────────────────
echo "→ [1/5] Authenticating with ECR..."
aws ecr get-login-password --region "${AWS_REGION}" | \
    docker login --username AWS --password-stdin "${ECR_REGISTRY}"
echo "  ✓ ECR authentication successful"

# ─────────────────────────────────────────
# Step 2: Build Docker images
# ─────────────────────────────────────────
SERVICES=("api" "ingestion" "ml" "frontend")
TAG="${VERSION}-${ENVIRONMENT}"

echo "→ [2/5] Building Docker images (tag: ${TAG})..."
for service in "${SERVICES[@]}"; do
    echo "  → Building ${service}..."
    docker build \
        -t "${ECR_REGISTRY}/${PROJECT_NAME}-${service}:${TAG}" \
        -t "${ECR_REGISTRY}/${PROJECT_NAME}-${service}:latest-${ENVIRONMENT}" \
        -f "apps/${service}/Dockerfile" \
        --target production \
        --build-arg VERSION="${VERSION}" \
        --build-arg ENVIRONMENT="${ENVIRONMENT}" \
        "apps/${service}"
done
echo "  ✓ All images built"

# ─────────────────────────────────────────
# Step 3: Push to ECR
# ─────────────────────────────────────────
echo "→ [3/5] Pushing images to ECR..."
for service in "${SERVICES[@]}"; do
    echo "  → Pushing ${service}..."
    docker push "${ECR_REGISTRY}/${PROJECT_NAME}-${service}:${TAG}"
    docker push "${ECR_REGISTRY}/${PROJECT_NAME}-${service}:latest-${ENVIRONMENT}"
done
echo "  ✓ All images pushed"

# ─────────────────────────────────────────
# Step 4: Update ECS services
# ─────────────────────────────────────────
ECS_CLUSTER="${PROJECT_NAME}-${ENVIRONMENT}"

echo "→ [4/5] Updating ECS services..."
for service in "${SERVICES[@]}"; do
    ecs_service="${PROJECT_NAME}-${service}-${ENVIRONMENT}"
    echo "  → Updating ${ecs_service}..."
    aws ecs update-service \
        --cluster "${ECS_CLUSTER}" \
        --service "${ecs_service}" \
        --force-new-deployment \
        --region "${AWS_REGION}" \
        --output text --query 'service.serviceName' || {
        echo "  ⚠ Failed to update ${ecs_service} — service may not exist yet."
    }
done
echo "  ✓ ECS services updated"

# ─────────────────────────────────────────
# Step 5: Wait for stability
# ─────────────────────────────────────────
echo "→ [5/5] Waiting for services to stabilise..."
for service in "${SERVICES[@]}"; do
    ecs_service="${PROJECT_NAME}-${service}-${ENVIRONMENT}"
    echo "  → Waiting for ${ecs_service}..."
    aws ecs wait services-stable \
        --cluster "${ECS_CLUSTER}" \
        --services "${ecs_service}" \
        --region "${AWS_REGION}" 2>/dev/null || {
        echo "  ⚠ Timeout waiting for ${ecs_service} — check AWS console."
    }
done

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ✓ Deployment to ${ENVIRONMENT^^} complete"
echo "  Version: ${TAG}"
echo "  Time:    $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "═══════════════════════════════════════════════════════"
echo ""
