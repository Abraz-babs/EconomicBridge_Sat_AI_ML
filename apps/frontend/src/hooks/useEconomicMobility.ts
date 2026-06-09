'use client';

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';
import { fmtUsdCompact, formatLocalAndUsd } from '@/lib/currency';


export type CompareBand = 'below_avg' | 'near_avg' | 'above_avg' | 'premium';


/** Compact USD: $1.20K above ten-thousand, else $940. Re-exported for callers. */
export const fmtUsd = fmtUsdCompact;

/**
 * Dual-currency income display, anchored on the real USD figure. Each country
 * shows its LOCAL currency derived from USD at the market rate (see
 * lib/currency) — `<local> ($USD)` — or `$USD` alone for an unknown country.
 * The stored World Bank local-currency figure is intentionally NOT used: its
 * official/Atlas rate understates the Naira badly.
 */
export function formatIncome(
  usd: number | null | undefined,
  country?: string | null,
): string {
  return formatLocalAndUsd(usd, country);
}


export interface MobilityIndicatorRow {
  id: string;
  tenant_id: string;
  lga: string;
  location: { lon: number; lat: number };
  cost_of_living_index: number;
  cost_of_living_band: CompareBand;
  // Dual currency: USD present for every tenant; NGN for Nigeria only.
  avg_household_income_ngn: number | null;
  avg_household_income_usd: number | null;
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
  median_household_income_ngn: number | null;
  median_household_income_usd: number | null;
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
