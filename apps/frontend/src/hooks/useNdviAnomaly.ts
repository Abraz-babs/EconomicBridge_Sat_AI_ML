'use client';

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';


export interface NdviSamplePoint {
  observed_at: string;
  ndvi: number;
}

export interface NdviScanData {
  anomaly_id: string | null;
  tenant_id: string;
  detector_name: string;
  detector_version: string;
  window_start: string;
  window_end: string;
  days_early_warning: number;
  ndvi_recent_mean: number;
  ndvi_baseline_mean: number;
  ndvi_baseline_std: number;
  z_score: number;
  disease_probability: number;
  anomaly: boolean;
  confidence_band: 'HIGH' | 'MEDIUM' | 'LOW';
  series: NdviSamplePoint[];
  crop: string | null;
  persisted: boolean;
}

export interface NdviScanRequest {
  crop?: string;
  demo_inject_anomaly?: boolean;
  persist?: boolean;
}


export interface NdviAnomalyRow {
  id: string;
  tenant_id: string;
  detector_name: string;
  detector_version: string;
  window_start: string;
  window_end: string;
  ndvi_recent_mean: number;
  ndvi_baseline_mean: number;
  ndvi_baseline_std: number;
  z_score: number;
  disease_probability: number;
  anomaly: boolean;
  confidence_band: 'HIGH' | 'MEDIUM' | 'LOW';
  crop: string | null;
  created_at: string;
}

interface NdviAnomalyListData {
  anomalies: NdviAnomalyRow[];
}


// ─── Scan mutation ────────────────────────────────────────────────────────


export function useScanNdviAnomaly(
  tenantId: string,
): UseMutationResult<NdviScanData, ApiException, NdviScanRequest> {
  const qc = useQueryClient();
  return useMutation<NdviScanData, ApiException, NdviScanRequest>({
    mutationFn: async (body) => {
      const envelope: SuccessEnvelope<NdviScanData> = await apiFetch<NdviScanData>(
        '/cropguard/ndvi/scan',
        { method: 'POST', tenantId, body },
      );
      return envelope.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ndvi-anomalies', tenantId] });
    },
  });
}


// ─── List anomalies ───────────────────────────────────────────────────────


export interface UseNdviAnomaliesParams {
  tenantId: string;
  limit?: number;
  anomaliesOnly?: boolean;
  enabled?: boolean;
}

export interface NdviAnomaliesResult {
  anomalies: NdviAnomalyRow[];
}

export function useNdviAnomalies(
  params: UseNdviAnomaliesParams,
): UseQueryResult<NdviAnomaliesResult, ApiException> {
  const limit = params.limit ?? 10;
  return useQuery<NdviAnomaliesResult, ApiException>({
    queryKey: ['ndvi-anomalies', params.tenantId, limit, params.anomaliesOnly ?? false],
    enabled: params.enabled !== false && Boolean(params.tenantId),
    staleTime: 30 * 1000,
    queryFn: async ({ signal }) => {
      const search = new URLSearchParams({ limit: String(limit) });
      if (params.anomaliesOnly) search.set('anomalies_only', 'true');
      const envelope: SuccessEnvelope<NdviAnomalyListData> =
        await apiFetch<NdviAnomalyListData>(
          `/cropguard/ndvi/anomalies?${search.toString()}`,
          { tenantId: params.tenantId, signal },
        );
      return { anomalies: envelope.data.anomalies };
    },
  });
}
