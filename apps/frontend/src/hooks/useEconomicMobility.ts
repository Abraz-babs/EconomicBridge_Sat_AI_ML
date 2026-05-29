'use client';

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';


export type CompareBand = 'below_avg' | 'near_avg' | 'above_avg' | 'premium';


/** Compact Naira: ₦1.20M / ₦270K / ₦950. */
export function fmtNgn(n: number): string {
  if (n >= 1_000_000) return `₦${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `₦${Math.round(n / 1_000)}K`;
  return `₦${n.toLocaleString()}`;
}

/** Compact USD: $1.20K above a thousand, else $940. */
export function fmtUsd(n: number): string {
  if (n >= 10_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toLocaleString()}`;
}

/**
 * Dual-currency income display. Nigerian tenants carry both currencies and
 * render `₦X ($Y)`; ECOWAS tenants are USD-only and render `$Y`. Falls back
 * to a dash when neither value is present.
 */
export function formatIncome(
  ngn: number | null | undefined,
  usd: number | null | undefined,
): string {
  if (ngn != null && usd != null) return `${fmtNgn(ngn)} (${fmtUsd(usd)})`;
  if (ngn != null) return fmtNgn(ngn);
  if (usd != null) return fmtUsd(usd);
  return '—';
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
