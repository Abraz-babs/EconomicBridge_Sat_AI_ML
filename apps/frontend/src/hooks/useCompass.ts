'use client';

/**
 * GET /api/v1/economic_mobility/compass — every LGA against five measured
 * factors. Mirrors apps/api/schemas/economic_mobility.py CompassData; keep in
 * sync. Signals are a count of readings that point to pressure, never a score.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';
import type { LightCategory } from '@/hooks/useLightTrend';

export interface CompassPrice {
  item: string;
  unit: 'kg' | 'litre' | string;
  publisher: string;
  place: string;
  /** World Bank model estimates (every month), not prices published as collected. */
  modelled: boolean;
  /** The last month a price was surveyed at this place (World Bank only). */
  last_surveyed: string | null;
  stale: boolean;
  points: { month: string; price_ngn: number }[];
}

export interface CompassLga {
  lga: string;
  location: { lon: number; lat: number } | null;
  people: number;
  light_category: LightCategory | null;
  light_change_pct: number | null;
  season_pct: number | null;
  walk_median_min: number | null;
  drive_median_min: number | null;
  over_hour_walk_people: number;
  over_hour_walk_share: number | null;
  facilities: number | null;
  facilities_per_10k: number | null;
  storms: number;
  advisories: number;
  signals: string[];
}

export interface FarVillage {
  name: string;
  ward: string | null;
  lga: string | null;
  location: { lon: number; lat: number };
  people: number;
  walk_min: number;
  drive_min: number | null;
}

export interface Compass {
  available: boolean;
  reason: string | null;
  season_year: number | null;
  previous_year: number | null;
  season_state_pct: number | null;
  season_since: string | null;
  people: number;
  over_hour_walk_people: number;
  walk_median_min: number | null;
  access_measured: boolean;
  facilities_release: string | null;
  facilities_total: number | null;
  facilities_unlocated: number | null;
  lgas: CompassLga[];
  far_from_care: FarVillage[];
  prices: CompassPrice[];
  income_usd_month: number | null;
  income_ngn_month: number | null;
}

export function useCompass(tenantId: string): UseQueryResult<Compass, ApiException> {
  return useQuery<Compass, ApiException>({
    queryKey: ['mobility-compass', tenantId],
    enabled: Boolean(tenantId),
    // Light is yearly, prices monthly, the season weekly: an hour is plenty.
    staleTime: 60 * 60 * 1000,
    queryFn: async ({ signal }) => {
      const envelope: SuccessEnvelope<Compass> = await apiFetch<Compass>(
        '/economic_mobility/compass', { tenantId, signal },
      );
      return envelope.data;
    },
  });
}
