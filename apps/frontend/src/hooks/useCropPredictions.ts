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
  /** Grad-CAM heatmap overlay as a base64 PNG (Slice 5d). Null when the
   *  caller didn't request it OR when the classifier is in stub mode. */
  saliency_b64: string | null;
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
  /** Request Grad-CAM saliency overlay (Slice 5d). +~150ms compute. */
  compute_saliency?: boolean;
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
  location: { lon: number; lat: number } | null;
  /** LGA where the sample was captured (the target area), when known. */
  lga: string | null;
  /** Free-text tag — the crop the observer entered at upload, when given. */
  zone_name: string | null;
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

/** The classifier's CURRENT capability (what the next inference would use) —
 * distinct from per-row provenance, which keeps the version each historic
 * prediction was made with. Drives the panel's model badge so a trained
 * model reads TRAINED for every tenant, not only those with fresh rows. */
export interface CropModelInfo {
  model_name: string;
  model_version: string;
  execution_mode: string;
}

export function useCropModelInfo(): UseQueryResult<CropModelInfo, ApiException> {
  return useQuery<CropModelInfo, ApiException>({
    queryKey: ['crop-model-info'],
    staleTime: 5 * 60 * 1000, // capability changes only on redeploy
    queryFn: async ({ signal }) =>
      mlFetch<CropModelInfo>('/predict/crop_disease/model_info', { signal }),
  });
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

interface LgaListData {
  tenant_id: string;
  lgas: string[];
}

/** GET /api/v1/cropguard/lgas — LGA names for the tenant, for the Leaf
 *  Diagnosis record tag (so saved observations carry a consistent place). */
export function useTenantLgas(
  tenantId: string,
): UseQueryResult<string[], ApiException> {
  return useQuery<string[], ApiException>({
    queryKey: ['cropguard-lgas', tenantId],
    enabled: Boolean(tenantId),
    staleTime: 60 * 60 * 1000, // LGA lists never change within a session
    queryFn: async ({ signal }) => {
      const env = await apiFetch<LgaListData>('/cropguard/lgas', { tenantId, signal });
      return env.data.lgas;
    },
  });
}

// ─── Tiled mode (Slice 5e-a) ───────────────────────────────────────────────


export interface TileResult {
  row: number;
  col: number;
  bbox_x: number;
  bbox_y: number;
  bbox_w: number;
  bbox_h: number;
  predicted_class: string;
  prediction: number;
  confidence: number;
  confidence_band: 'HIGH' | 'MEDIUM' | 'LOW';
  top_k: CropTopKEntry[];
}

export interface CropTiledPredictionData {
  prediction_id: string | null;
  model_name: string;
  model_version: string;
  tenant_id: string;
  rows: number;
  cols: number;
  source_width: number;
  source_height: number;
  tile_width: number;
  tile_height: number;
  aggregate_class: string;
  aggregate_prediction: number;
  hottest_tile: TileResult;
  tiles: TileResult[];
  image_sha256: string;
  total_inference_time_ms: number;
  timestamp: string;
  persisted: boolean;
}

export interface CropTiledPredictionRequest {
  tenant_id: string;
  image_base64: string;
  rows?: number;
  cols?: number;
  top_k?: number;
  persist?: boolean;
  lat?: number;
  lon?: number;
  lga?: string;
  zone_name?: string;
}


export function usePredictCropDiseaseTiled(
  tenantId: string,
): UseMutationResult<
  CropTiledPredictionData,
  ApiException,
  CropTiledPredictionRequest
> {
  const qc = useQueryClient();
  return useMutation<
    CropTiledPredictionData,
    ApiException,
    CropTiledPredictionRequest
  >({
    mutationFn: async (body) =>
      mlFetch<CropTiledPredictionData>('/predict/crop_disease/tiled', {
        method: 'POST',
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['crop-predictions', tenantId] });
    },
  });
}
