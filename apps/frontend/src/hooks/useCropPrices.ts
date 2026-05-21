'use client';

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';


/** Mirrors apps/api/schemas/cropguard.py — keep in sync. */

export interface CropPricePoint {
  crop: string;
  region: string;
  observed_at: string;
  price_ngn_per_kg: number;
  source: string;
}

export interface CropPriceSeriesData {
  crop: string;
  region: string;
  months: number;
  points: CropPricePoint[];
  latest_price: number | null;
  earliest_price: number | null;
  pct_change: number | null;
  sources: string[];
}

export interface CropPriceCorrelationData {
  region: string;
  months: number;
  crops: string[];
  matrix: number[][];
}


export interface UseCropPriceSeriesParams {
  tenantId: string;
  crop: string;
  months?: number;
  enabled?: boolean;
}


/** Single-crop price time series. */
export function useCropPriceSeries(
  params: UseCropPriceSeriesParams,
): UseQueryResult<CropPriceSeriesData, ApiException> {
  const months = params.months ?? 24;
  return useQuery<CropPriceSeriesData, ApiException>({
    queryKey: ['crop-prices', params.tenantId, params.crop, months],
    enabled: params.enabled !== false && Boolean(params.tenantId && params.crop),
    staleTime: 60 * 1000,
    queryFn: async ({ signal }) => {
      const search = new URLSearchParams({
        crop: params.crop,
        months: String(months),
      });
      const envelope: SuccessEnvelope<CropPriceSeriesData> =
        await apiFetch<CropPriceSeriesData>(
          `/cropguard/prices?${search.toString()}`,
          { tenantId: params.tenantId, signal },
        );
      return envelope.data;
    },
  });
}


export interface UseCropPriceCorrelationParams {
  tenantId: string;
  months?: number;
  enabled?: boolean;
}


/** Correlation matrix across all crops in the tenant region. */
export function useCropPriceCorrelation(
  params: UseCropPriceCorrelationParams,
): UseQueryResult<CropPriceCorrelationData, ApiException> {
  const months = params.months ?? 24;
  return useQuery<CropPriceCorrelationData, ApiException>({
    queryKey: ['crop-prices-corr', params.tenantId, months],
    enabled: params.enabled !== false && Boolean(params.tenantId),
    staleTime: 60 * 1000,
    queryFn: async ({ signal }) => {
      const envelope: SuccessEnvelope<CropPriceCorrelationData> =
        await apiFetch<CropPriceCorrelationData>(
          `/cropguard/prices/correlation?months=${months}`,
          { tenantId: params.tenantId, signal },
        );
      return envelope.data;
    },
  });
}
