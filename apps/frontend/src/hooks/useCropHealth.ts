'use client';

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch } from '@/lib/api';

export type CropHealth =
  | 'healthy' | 'moderate' | 'stressed' | 'poor' | 'bare' | 'unknown';

/** Mirrors apps/api/schemas/cropguard.CropHealthRow — one current row per LGA. */
export interface CropHealthRow {
  id: string;
  tenant_id: string;
  lga: string;
  lat: number;
  lon: number;
  ndvi: number | null;
  ndvi_date: string | null;
  health: CropHealth;
  verdict: string;
  source: string;
  created_at: string;
}

/** GET /api/v1/cropguard/crop-health — every LGA's current NDVI health. */
export function useCropHealth(
  tenantId: string,
): UseQueryResult<CropHealthRow[], ApiException> {
  return useQuery<CropHealthRow[], ApiException>({
    queryKey: ['crop-health', tenantId],
    enabled: Boolean(tenantId),
    staleTime: 5 * 60 * 1000,
    queryFn: async ({ signal }) => {
      const env = await apiFetch<{ rows: CropHealthRow[] }>(
        '/cropguard/crop-health?limit=600',
        { tenantId, signal },
      );
      return env.data.rows;
    },
  });
}
