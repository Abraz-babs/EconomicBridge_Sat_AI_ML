'use client';

/**
 * The forecast check: ECMWF's rain forecast against the rain NASA's IMERG
 * measured, LGA by LGA. Mirrors apps/api/schemas/forecast_check.py — keep the
 * two in sync.
 *
 * Count lists are positional (see Counts below) so a season's record stays
 * small; every percentage on the page is computed from them, with its sample.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';
import type { ForecastFeed } from './useForecast';

/** [hits, false alarms, misses, correct dry, forecast mm, measured mm,
 *  abs error mm on wet pairs, wet pairs, then hits, false alarms, misses,
 *  correct calls for soaking days of 10 mm+]. Ribbon and per-LGA lists carry
 *  the first 4 and 6 of these. */
export type Counts = number[];
export type CheckModel = 'ifs' | 'aifs';

export interface CheckDay {
  day: string;
  lgas: number;
  wet: number;
  max_mm: number;
  max_lga: string;
  ifs: Counts[];      // per shown lead
  aifs: Counts[];
}

export interface CheckLga {
  lga: string;
  location: { lon: number; lat: number } | null;
  days: number;
  wet: number;
  ifs: Counts[];      // per shown lead
  aifs: Counts[];
}

export interface CheckChance {
  brier: (number | null)[][];              // per lead 0..9: [pairs, Brier, base-rate Brier]
  bins: Record<string, number[][]>;        // lead group -> per bin: [pairs, sum %, sum share]
}

export interface ForecastCheck {
  computed_at: string | null;
  first_day: string | null;
  last_day: string | null;
  days_checked: number;
  lga_days: number;
  pairs: number;
  wet_mm: number;
  heavy_mm: number;
  shown_leads: number[];
  chance_bins: number[];
  chance_groups: string[];
  recent_days: number;
  recent_from: string | null;
  scorecard: Record<string, Record<string, Counts[]>>;    // 'all' | 'recent' -> model -> per lead 0..14
  chances: Record<string, CheckChance>;
  ribbon: CheckDay[];
  lgas: CheckLga[];
  feed: ForecastFeed;
  product: string;
  attribution: string;
  measured_credit: string;
}

export interface CheckDayArea {
  lga: string;
  location: { lon: number; lat: number } | null;
  measured_mm: number;
  measured_max_mm: number;
  wet_share_1mm: number;
  wet_share_10mm: number;
  ifs_mm: (number | null)[];      // forecast made k days before, k = 0..14
  aifs_mm: (number | null)[];
  chance_1mm: (number | null)[];  // k = 0..9
  chance_10mm: (number | null)[];
}

export interface ForecastCheckDay {
  day: string | null;
  areas: CheckDayArea[];
  product: string;
}

/** GET /shockguard/forecast/check — the newest scorecard for the tenant. */
export function useForecastCheck(tenantId: string, enabled = true): UseQueryResult<ForecastCheck, ApiException> {
  return useQuery<ForecastCheck, ApiException>({
    queryKey: ['shockguard-forecast-check', tenantId],
    enabled: enabled && Boolean(tenantId),
    staleTime: 30 * 60 * 1000,
    queryFn: async ({ signal }) => {
      const envelope: SuccessEnvelope<ForecastCheck> = await apiFetch<ForecastCheck>('/shockguard/forecast/check', { tenantId, signal });
      return envelope.data;
    },
  });
}

/** GET /shockguard/forecast/check/day — one measured day, every LGA, every forecast made for it. */
export function useForecastCheckDay(tenantId: string, day: string | null, enabled = true): UseQueryResult<ForecastCheckDay, ApiException> {
  return useQuery<ForecastCheckDay, ApiException>({
    queryKey: ['shockguard-forecast-check-day', tenantId, day],
    enabled: enabled && Boolean(tenantId) && Boolean(day),
    staleTime: 30 * 60 * 1000,
    placeholderData: (prev) => prev,
    queryFn: async ({ signal }) => {
      const path = `/shockguard/forecast/check/day?day=${encodeURIComponent(day ?? '')}`;
      const envelope: SuccessEnvelope<ForecastCheckDay> = await apiFetch<ForecastCheckDay>(path, { tenantId, signal });
      return envelope.data;
    },
  });
}
