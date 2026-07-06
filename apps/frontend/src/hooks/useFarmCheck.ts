'use client';

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { ApiException, apiFetch, ingestionFetch } from '@/lib/api';

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

export interface FarmCheckPass {
  date: string;
  ndvi: number;
  health: FarmHealth;
  verdict: string;
  sample_count: number;
  cloud_affected: boolean;
}

export type StressLevel = 'none' | 'moderate' | 'high' | 'unknown';

export interface FarmStress {
  level: StressLevel;
  z: number | null;
  message: string;
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
  passes: FarmCheckPass[];
  stress: FarmStress;
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

// ─── Save + recall records (apps/api GET/POST /cropguard/farm-checks) ───────

/** One saved Farm Check — mirrors apps/api schemas/farm_check.FarmCheckRecordRow.
 *  The computed reading PLUS the lga/crop record tags, kept for recall. */
export interface FarmCheckRecord {
  id: string;
  tenant_id: string;
  lat: number;
  lon: number;
  crop: string;
  lga: string | null;
  owner_name: string | null;
  ndvi: number | null;
  ndvi_date: string | null;
  health: FarmHealth;
  verdict: string;
  sar_db: number | null;
  sar_date: string | null;
  stress: FarmStress | null;
  trend: FarmCheckTrendPoint[];
  passes: FarmCheckPass[];
  sample_count: number;
  area_ha: number;
  resolution_m: number;
  source: string;
  note: string | null;
  created_at: string;
}

/** POST body: the whole result plus the record tags (state = X-Tenant-Id header). */
export type FarmCheckSaveBody = FarmCheckResult & { lga?: string; owner_name?: string };

interface FarmCheckSaveResponse {
  record_id: string;
  saved: boolean;
}

interface FarmCheckRecordsData {
  records: FarmCheckRecord[];
}

/** POST /cropguard/farm-checks — persist a Farm Check as a recallable record. */
export function useSaveFarmCheck(
  tenantId: string,
): UseMutationResult<FarmCheckSaveResponse, ApiException, FarmCheckSaveBody> {
  const qc = useQueryClient();
  return useMutation<FarmCheckSaveResponse, ApiException, FarmCheckSaveBody>({
    mutationFn: async (body) => {
      const env = await apiFetch<FarmCheckSaveResponse>('/cropguard/farm-checks', {
        method: 'POST',
        body,
        tenantId,
      });
      return env.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['farm-check-records', tenantId] });
    },
  });
}

/** GET /cropguard/farm-checks — recent saved checks for the tenant (state). */
export function useFarmCheckRecords(
  tenantId: string,
  enabled = true,
): UseQueryResult<FarmCheckRecord[], ApiException> {
  return useQuery<FarmCheckRecord[], ApiException>({
    queryKey: ['farm-check-records', tenantId],
    enabled: enabled && Boolean(tenantId),
    staleTime: 30 * 1000,
    queryFn: async ({ signal }) => {
      const env = await apiFetch<FarmCheckRecordsData>(
        '/cropguard/farm-checks?limit=20',
        { tenantId, signal },
      );
      return env.data.records;
    },
  });
}
