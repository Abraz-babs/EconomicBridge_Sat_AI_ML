'use client';

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { ApiException, apiFetch, mlFetch, type SuccessEnvelope } from '@/lib/api';


/** Mirrors apps/api/schemas/cropguard.py + apps/ml/schemas/yield_predictor.py. */

export interface YieldForecastRow {
  id: string;
  tenant_id: string;
  crop: string;
  prediction: number;
  confidence: number;
  confidence_band: 'HIGH' | 'MEDIUM' | 'LOW';
  requires_human_review: boolean;
  predicted_yield_t_ha: number;
  yield_pi_low_t_ha: number | null;
  yield_pi_high_t_ha: number | null;
  model_name: string;
  model_version: string;
  inference_time_ms: number | null;
  created_at: string;
}

interface YieldForecastListData {
  forecasts: YieldForecastRow[];
}


export interface YieldPredictionRequest {
  tenant_id: string;
  crop: string;
  ndvi_mean_30d: number;
  ndvi_anomaly: number;
  rainfall_30d_mm: number;
  rainfall_anomaly: number;
  soil_quality_index: number;
  historical_yield_mean_t_ha: number;
  days_to_harvest: number;
  lat?: number;
  lon?: number;
  lga?: string;
  zone_name?: string;
  persist?: boolean;
}

export interface YieldPredictionData {
  prediction_id: string | null;
  model_name: string;
  model_version: string;
  tenant_id: string;
  crop: string;
  prediction: number;
  confidence: number;
  confidence_band: 'HIGH' | 'MEDIUM' | 'LOW';
  requires_human_review: boolean;
  predicted_yield_t_ha: number;
  yield_pi_low_t_ha: number | null;
  yield_pi_high_t_ha: number | null;
  shap_values: Record<string, number>;
  shap_base_value: number | null;
  input_hash: string;
  inference_time_ms: number;
  timestamp: string;
  persisted: boolean;
}


// ─── List recent forecasts ────────────────────────────────────────────────


export interface UseYieldForecastsParams {
  tenantId: string;
  limit?: number;
  crop?: string;
  enabled?: boolean;
}

export interface YieldForecastsResult {
  forecasts: YieldForecastRow[];
}


export function useYieldForecasts(
  params: UseYieldForecastsParams,
): UseQueryResult<YieldForecastsResult, ApiException> {
  const limit = params.limit ?? 30;
  return useQuery<YieldForecastsResult, ApiException>({
    queryKey: ['yield-forecasts', params.tenantId, limit, params.crop ?? null],
    enabled: params.enabled !== false && Boolean(params.tenantId),
    staleTime: 30 * 1000,
    queryFn: async ({ signal }) => {
      const search = new URLSearchParams({ limit: String(limit) });
      if (params.crop) search.set('crop', params.crop);
      const envelope: SuccessEnvelope<YieldForecastListData> =
        await apiFetch<YieldForecastListData>(
          `/cropguard/yield/forecasts?${search.toString()}`,
          { tenantId: params.tenantId, signal },
        );
      return { forecasts: envelope.data.forecasts };
    },
  });
}


// ─── Trigger a new yield prediction (calls ML service) ────────────────────


export function usePredictYield(
  tenantId: string,
): UseMutationResult<YieldPredictionData, ApiException, YieldPredictionRequest> {
  const qc = useQueryClient();
  return useMutation<YieldPredictionData, ApiException, YieldPredictionRequest>({
    mutationFn: async (body) =>
      mlFetch<YieldPredictionData>('/predict/yield', {
        method: 'POST',
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['yield-forecasts', tenantId] });
    },
  });
}
