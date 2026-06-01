'use client';

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';

/** Mirrors apps/api/schemas/overview.py. */
export interface OverviewStatCard {
  label: string;
  value: string;
  subtitle: string;
  tone: string; // 'ok' | 'warn' | 'neg' | ''
}

export interface OverviewStatsData {
  tenants_live: number;
  lgas_mapped: number;
  settlements_scored: number;
  crop_detections: number;
  satellite_observations: number;
  live_sources: string[];
  cards: OverviewStatCard[];
  generated_at: string;
}

/**
 * Live, cross-tenant platform KPIs for the dashboard overview. No tenant
 * header — this is the platform-wide roll-up. 60s stale time keeps the
 * overview snappy without hammering the aggregate endpoint.
 */
export function useOverviewStats(): UseQueryResult<OverviewStatsData, ApiException> {
  return useQuery<OverviewStatsData, ApiException>({
    queryKey: ['overview-stats'],
    staleTime: 60 * 1000,
    queryFn: async ({ signal }) => {
      const envelope: SuccessEnvelope<OverviewStatsData> =
        await apiFetch<OverviewStatsData>('/overview/stats', { signal });
      return envelope.data;
    },
  });
}

// ─── Crop-health index (live, cross-tenant, mixed regions) ──────────────────

export interface CropHealthRow {
  label: string;
  pct: number;
  tone: string; // 'ok' | 'warn' | 'neg'
}

export function useCropHealth(): UseQueryResult<CropHealthRow[], ApiException> {
  return useQuery<CropHealthRow[], ApiException>({
    queryKey: ['overview-crop-health'],
    staleTime: 60 * 1000,
    queryFn: async ({ signal }) => {
      const envelope: SuccessEnvelope<{ rows: CropHealthRow[] }> =
        await apiFetch<{ rows: CropHealthRow[] }>('/overview/crop_health', { signal });
      return envelope.data.rows;
    },
  });
}

// ─── Active-response events (live, cross-tenant, mixed regions) ─────────────

export interface ActiveResponseRow {
  region: string;
  sub: string;
  status: string;
  tone: string; // css status suffix, e.g. 's-active'
}

export function useActiveResponse(): UseQueryResult<ActiveResponseRow[], ApiException> {
  return useQuery<ActiveResponseRow[], ApiException>({
    queryKey: ['overview-active-response'],
    staleTime: 60 * 1000,
    queryFn: async ({ signal }) => {
      const envelope: SuccessEnvelope<{ rows: ActiveResponseRow[] }> =
        await apiFetch<{ rows: ActiveResponseRow[] }>('/overview/active_response', { signal });
      return envelope.data.rows;
    },
  });
}
