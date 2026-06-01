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
