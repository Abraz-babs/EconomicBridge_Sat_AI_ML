'use client';

/**
 * ShockGuard's forecast side: ECMWF open data, the next 15 days per LGA.
 * Mirrors apps/api/schemas/forecast.py — keep the two in sync.
 *
 * Every list is one value per day counted from `first_day` (the run date, a
 * UTC day). A product ECMWF did not publish for the run is null, never a
 * stand-in from another model.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';
import type { LgaFeature } from './useLgaBoundaries';

export interface ForecastArea {
  lga: string;
  location: { lon: number; lat: number } | null;
  cells: number;
  rain_ifs_mm: number[];
  rain_ifs_max_mm: number[];
  rain_aifs_mm: number[] | null;
  chance_1mm: number[] | null;
  chance_10mm: number[] | null;
  chance_25mm: number[] | null;
  chance_50mm: number[] | null;
  temp_dawn_c: number[] | null;
  temp_afternoon_c: number[] | null;
}

export interface ForecastFeed {
  last_success_at: string | null;
  last_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
}

export interface Forecast {
  run_at: string | null;
  first_day: string | null;
  days: string[];
  areas: ForecastArea[];
  feed: ForecastFeed;
  source: string;
  attribution: string;
}

export interface ForecastCells {
  run_at: string | null;
  lat0: number | null;
  lon0: number | null;
  res: number;
  n_rows: number;
  n_cols: number;
  rain_ifs_mm: number[][];
  rain_aifs_mm: number[][] | null;
  chance_10mm: number[][] | null;
}

/** GET /shockguard/forecast — the newest stored run, every LGA of the tenant. */
export function useForecast(tenantId: string, enabled = true): UseQueryResult<Forecast, ApiException> {
  return useQuery<Forecast, ApiException>({
    queryKey: ['shockguard-forecast', tenantId],
    enabled: enabled && Boolean(tenantId),
    staleTime: 30 * 60 * 1000,
    queryFn: async ({ signal }) => {
      const envelope: SuccessEnvelope<Forecast> = await apiFetch<Forecast>('/shockguard/forecast', { tenantId, signal });
      return envelope.data;
    },
  });
}

/** GET /shockguard/forecast/cells — ECMWF's own 0.25° cells, fetched only when the layer is on. */
export function useForecastCells(tenantId: string, enabled: boolean): UseQueryResult<ForecastCells, ApiException> {
  return useQuery<ForecastCells, ApiException>({
    queryKey: ['shockguard-forecast-cells', tenantId],
    enabled: enabled && Boolean(tenantId),
    staleTime: 30 * 60 * 1000,
    queryFn: async ({ signal }) => {
      const envelope: SuccessEnvelope<ForecastCells> = await apiFetch<ForecastCells>('/shockguard/forecast/cells', { tenantId, signal });
      return envelope.data;
    },
  });
}

/** Static outline files: Nigeria's (shared with the other module maps) and
 *  Ghana + Senegal's (the forecast map's own file). Fetched once, cached. */
const OUTLINE_FILE: Record<string, string> = { ghana: '/geo/lga-boundaries-gh-sn.json', senegal: '/geo/lga-boundaries-gh-sn.json' };
const NIGERIA_FILE = '/geo/lga-boundaries-ng.json';

export function useForecastOutlines(tenantId: string): UseQueryResult<LgaFeature[], Error> {
  const file = OUTLINE_FILE[tenantId] ?? NIGERIA_FILE;
  return useQuery<{ features: LgaFeature[] }, Error, LgaFeature[]>({
    // Nigeria shares useLgaBoundaries' cache key, so the file is fetched once for both.
    queryKey: [file === NIGERIA_FILE ? 'lga-boundaries-ng' : 'lga-boundaries-gh-sn'],
    queryFn: async () => {
      const res = await fetch(file);
      if (!res.ok) throw new Error(`LGA outlines: ${res.status}`);
      return res.json();
    },
    staleTime: Infinity,
    gcTime: Infinity,
    select: (fc) => fc.features.filter((f) => f.properties.tenant === tenantId),
  });
}
