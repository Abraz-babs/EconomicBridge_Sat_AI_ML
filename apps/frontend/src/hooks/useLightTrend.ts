'use client';

/**
 * GET /api/v1/economic_mobility/light-trend — Mobility Compass. Mirrors
 * apps/api/schemas/economic_mobility.py LightTrendData; keep in sync.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';

export type LightCategory = 'dimmer' | 'brighter' | 'new_light' | 'steady' | 'still_dark' | 'mixed';

export interface LightTrendLga {
  lga: string;
  location: { lon: number; lat: number } | null;
  years: number[];
  /** Summed radiance per year on NASA's near-nadir composite. */
  near_nadir: (number | null)[];
  all_angle: (number | null)[];
  /** Near-nadir: latest three years against the first three. Null where the start was only faint light. */
  change_pct: number | null;
  category: LightCategory;
  lit_km2_start: number | null;
  lit_km2_now: number | null;
  people: number;
  villages: number;
  gone_dark: number;
  newly_lit: number;
}

export interface TrendVillage {
  name: string;
  ward: string | null;
  lga: string | null;
  location: { lon: number; lat: number };
  people: number;
  since_year: number | null;
  near_nadir: (number | null)[];
}

export interface StapleSeries {
  crop: string;
  source: string;
  points: { month: string; price_ngn_per_kg: number }[];
}

export interface LightTrend {
  available: boolean;
  reason: string | null;
  first_year: number | null;
  last_year: number | null;
  window: number;
  lgas: LightTrendLga[];
  dimmer: number;
  brighter: number;
  steady: number;
  still_dark: number;
  mixed: number;
  people_in_dimmer: number;
  gone_dark: number;
  gone_dark_people: number;
  newly_lit: number;
  newly_lit_people: number;
  villages_gone_dark: TrendVillage[];
  villages_newly_lit: TrendVillage[];
  prices: StapleSeries[];
}

export function useLightTrend(tenantId: string): UseQueryResult<LightTrend, ApiException> {
  return useQuery<LightTrend, ApiException>({
    queryKey: ['light-trend', tenantId],
    enabled: Boolean(tenantId),
    // A yearly measurement: no need to refetch on every focus.
    staleTime: 60 * 60 * 1000,
    queryFn: async ({ signal }) => {
      const envelope: SuccessEnvelope<LightTrend> = await apiFetch<LightTrend>(
        '/economic_mobility/light-trend', { tenantId, signal },
      );
      return envelope.data;
    },
  });
}
