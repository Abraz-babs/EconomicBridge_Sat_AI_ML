'use client';

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';


export type CompareBand = 'below_avg' | 'near_avg' | 'above_avg' | 'premium';


export interface MobilityIndicatorRow {
  id: string;
  tenant_id: string;
  lga: string;
  location: { lon: number; lat: number };
  cost_of_living_index: number;
  cost_of_living_band: CompareBand;
  avg_household_income_ngn: number;
  income_opportunity_score: number;
  displacement_capacity_index: number;
  population: number;
  observed_at: string;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface MobilityStatsData {
  tenant_id: string;
  total_lgas: number;
  median_cost_of_living: number;
  median_household_income_ngn: number;
  cheapest_lga: string | null;
  most_expensive_lga: string | null;
  best_opportunity_lga: string | null;
  best_capacity_lga: string | null;
  indicators: MobilityIndicatorRow[];
  sources: string[];
}


export interface UseEconomicMobilityParams {
  tenantId: string;
  enabled?: boolean;
}


export function useEconomicMobility(
  params: UseEconomicMobilityParams,
): UseQueryResult<MobilityStatsData, ApiException> {
  return useQuery<MobilityStatsData, ApiException>({
    queryKey: ['economic-mobility', params.tenantId],
    enabled: params.enabled !== false && Boolean(params.tenantId),
    queryFn: async ({ signal }) => {
      const envelope: SuccessEnvelope<MobilityStatsData> =
        await apiFetch<MobilityStatsData>(
          '/economic_mobility/indicators',
          { tenantId: params.tenantId, signal },
        );
      return envelope.data;
    },
  });
}
