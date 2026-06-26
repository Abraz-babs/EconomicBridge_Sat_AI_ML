'use client';

import { useMutation, type UseMutationResult } from '@tanstack/react-query';

import { ApiException, ingestionFetch } from '@/lib/api';

/** Mirrors apps/ingestion/routers/farm_check.py. */
export interface FarmCheckRequest {
  lat: number;
  lon: number;
  crop: string;
  half_m?: number;
}

export interface FarmCheckTrendPoint {
  date: string;
  ndvi: number;
}

export type FarmHealth =
  | 'healthy' | 'moderate' | 'stressed' | 'poor' | 'bare' | 'unknown';

export interface FarmCheckResult {
  lat: number;
  lon: number;
  crop: string;
  ndvi: number | null;
  ndvi_date: string | null;
  health: FarmHealth;
  verdict: string;
  sar_db: number | null;
  sar_date: string | null;
  trend: FarmCheckTrendPoint[];
  sample_count: number;
  area_ha: number;
  resolution_m: number;
  source: string;
  note: string;
}

/**
 * POST /ingestion/api/v1/cropguard/farm-check — per-farm Sentinel-2 NDVI +
 * Sentinel-1 SAR vegetation-health check for a single coordinate + crop.
 */
export function useFarmCheck(): UseMutationResult<
  FarmCheckResult,
  ApiException,
  FarmCheckRequest
> {
  return useMutation<FarmCheckResult, ApiException, FarmCheckRequest>({
    mutationFn: (body) =>
      ingestionFetch<FarmCheckResult>('/cropguard/farm-check', {
        method: 'POST',
        body,
      }),
  });
}
