'use client';

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { ApiException, apiFetch, mlFetch, type SuccessEnvelope } from '@/lib/api';

/** Mirrors apps/ml/schemas/crop.py — keep in sync. */

export interface CropTopKEntry {
  class_name: string;
  probability: number;
}

export interface CropPredictionData {
  prediction_id: string | null;
  model_name: string;
  model_version: string;
  tenant_id: string;
  predicted_class: string;
  prediction: number;
  confidence: number;
  confidence_band: 'HIGH' | 'MEDIUM' | 'LOW';
  requires_human_review: boolean;
  top_k: CropTopKEntry[];
  image_source: 's3' | 'inline';
  image_s3_bucket: string | null;
  image_s3_key: string | null;
  image_sha256: string;
  input_hash: string;
  inference_time_ms: number;
  timestamp: string;
  persisted: boolean;
}

/** Body of POST /api/v1/predict/crop_disease (ML service). */
export interface CropPredictionRequest {
  tenant_id: string;
  image_base64: string;
  top_k?: number;
  persist?: boolean;
  lat?: number;
  lon?: number;
  lga?: string;
  zone_name?: string;
}

/**
 * One row in the recent-predictions feed (apps/api GET /cropguard/predictions).
 * Strict subset of CropPredictionData — the persisted columns + a few
 * audit fields the dashboard wants.
 */
export interface CropPredictionRow {
  id: string;
  tenant_id: string;
  predicted_class: string;
  prediction: number;
  confidence: number;
  confidence_band: 'HIGH' | 'MEDIUM' | 'LOW';
  requires_human_review: boolean;
  top_k: CropTopKEntry[];
  image_source: 's3' | 'inline';
  image_s3_key: string | null;
  model_name: string;
  model_version: string;
  inference_time_ms: number | null;
  created_at: string;
}

interface CropPredictionsListData {
  predictions: CropPredictionRow[];
}

// ─── List recent predictions ───────────────────────────────────────────────


export interface UseCropPredictionsParams {
  tenantId: string;
  limit?: number;
  enabled?: boolean;
}

export interface CropPredictionsResult {
  predictions: CropPredictionRow[];
  traceId: string | null;
}

export function useCropPredictions(
  params: UseCropPredictionsParams,
): UseQueryResult<CropPredictionsResult, ApiException> {
  const limit = params.limit ?? 10;
  return useQuery<CropPredictionsResult, ApiException>({
    queryKey: ['crop-predictions', params.tenantId, limit],
    enabled: params.enabled !== false && Boolean(params.tenantId),
    staleTime: 30 * 1000,
    queryFn: async ({ signal }) => {
      const envelope: SuccessEnvelope<CropPredictionsListData> = await apiFetch<CropPredictionsListData>(
        `/cropguard/predictions?limit=${limit}`,
        { tenantId: params.tenantId, signal },
      );
      return {
        predictions: envelope.data.predictions,
        traceId: envelope.meta.trace_id,
      };
    },
  });
}

// ─── Upload + predict mutation ─────────────────────────────────────────────


/**
 * Strip the `data:image/...;base64,` prefix that FileReader.readAsDataURL
 * emits. The backend wants raw base64 only.
 */
export function stripDataUrlPrefix(dataUrl: string): string {
  const comma = dataUrl.indexOf(',');
  return comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;
}

/**
 * Convert a File to a raw-base64 string suitable for the
 * `image_base64` field of CropPredictionRequest.
 */
export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result === 'string') {
        resolve(stripDataUrlPrefix(result));
      } else {
        reject(new Error('FileReader returned non-string result'));
      }
    };
    reader.onerror = () => reject(reader.error ?? new Error('FileReader failed'));
    reader.readAsDataURL(file);
  });
}


export function usePredictCropDisease(
  tenantId: string,
): UseMutationResult<CropPredictionData, ApiException, CropPredictionRequest> {
  const qc = useQueryClient();
  return useMutation<CropPredictionData, ApiException, CropPredictionRequest>({
    mutationFn: async (body) =>
      mlFetch<CropPredictionData>('/predict/crop_disease', {
        method: 'POST',
        body,
      }),
    onSuccess: () => {
      // Newly-persisted row should appear in the recent-feed soon.
      qc.invalidateQueries({ queryKey: ['crop-predictions', tenantId] });
    },
  });
}
