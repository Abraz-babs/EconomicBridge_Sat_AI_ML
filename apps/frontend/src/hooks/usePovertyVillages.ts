'use client';

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';


/** Mirrors apps/api/schemas/poverty.py — keep in sync. */

export interface PovertyVillage {
  id: string;
  tenant_id: string;
  settlement_name: string;
  lga: string;
  location: { lon: number; lat: number };
  poverty_score: number;
  population: number;
  households_unreached: number;
  nightlight_dimness: number;
  has_dhs_data: boolean;
  viirs_pixel_radiance: number | null;
  worldpop_estimate: number | null;
  source: string;
  created_at: string;
  updated_at: string;
}


export interface PovertyStatsData {
  tenant_id: string;
  villages_identified: number;
  population_estimated: number;
  households_unreached: number;
  coverage_pct: number;
  verification_pct: number;
  villages: PovertyVillage[];
  sources: string[];
}


export interface UsePovertyVillagesParams {
  tenantId: string;
  limit?: number;
  enabled?: boolean;
}


export function usePovertyVillages(
  params: UsePovertyVillagesParams,
): UseQueryResult<PovertyStatsData, ApiException> {
  const limit = params.limit ?? 200;
  return useQuery<PovertyStatsData, ApiException>({
    queryKey: ['poverty-villages', params.tenantId, limit],
    enabled: params.enabled !== false && Boolean(params.tenantId),
    queryFn: async ({ signal }) => {
      const envelope: SuccessEnvelope<PovertyStatsData> =
        await apiFetch<PovertyStatsData>(
          `/economic_visibility/villages?limit=${limit}`,
          { tenantId: params.tenantId, signal },
        );
      return envelope.data;
    },
  });
}
