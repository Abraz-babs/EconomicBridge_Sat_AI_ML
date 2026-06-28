# EconomicBridge Frontend — Next.js 16 (Turbopack-built) production image.
# Three-stage multi-arch build:
#   deps    — install node_modules
#   builder — run `next build` with NEXT_PUBLIC_* baked in
#   runner  — minimal node:22 + the standalone server output
#
# NEXT_PUBLIC_MAPBOX_TOKEN and NEXT_PUBLIC_API_BASE_URL are *build-time* args
# because Next.js inlines them into the client bundle. Pass via:
#   docker build \
#     --build-arg NEXT_PUBLIC_MAPBOX_TOKEN=$NEXT_PUBLIC_MAPBOX_TOKEN \
#     --build-arg NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
#     -t economicbridge/frontend:dev apps/frontend

# ─── deps ────────────────────────────────────────────────────────────────
FROM public.ecr.aws/docker/library/node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

# ─── builder ─────────────────────────────────────────────────────────────
FROM public.ecr.aws/docker/library/node:22-alpine AS builder
WORKDIR /app

# Mapbox token + service base URLs are baked into the client bundle at build
# time. The production defaults are RELATIVE paths: the ALB serves frontend and
# backends from one origin (/api/v1 → api, /ingestion → ingestion, /ml → ml,
# /notifications → notifications), so relative URLs work on any domain —
# including the bare ALB DNS — with zero CORS surface. The prefixed services
# strip their prefix via UrlPrefixStripMiddleware (URL_PREFIX env).
ARG NEXT_PUBLIC_MAPBOX_TOKEN
ARG NEXT_PUBLIC_API_BASE_URL=/api/v1
ARG NEXT_PUBLIC_INGESTION_BASE_URL=/ingestion/api/v1
ARG NEXT_PUBLIC_ML_BASE_URL=/ml/api/v1
ARG NEXT_PUBLIC_NOTIFY_BASE_URL=/notifications/api/v1
ENV NEXT_PUBLIC_MAPBOX_TOKEN=$NEXT_PUBLIC_MAPBOX_TOKEN \
    NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_INGESTION_BASE_URL=$NEXT_PUBLIC_INGESTION_BASE_URL \
    NEXT_PUBLIC_ML_BASE_URL=$NEXT_PUBLIC_ML_BASE_URL \
    NEXT_PUBLIC_NOTIFY_BASE_URL=$NEXT_PUBLIC_NOTIFY_BASE_URL \
    NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ─── runner ──────────────────────────────────────────────────────────────
FROM public.ecr.aws/docker/library/node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Non-root user for the runtime.
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

# Next.js standalone output (requires `output: 'standalone'` in next.config.ts).
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD wget -qO- http://127.0.0.1:3000 >/dev/null 2>&1 || exit 1

CMD ["node", "server.js"]
