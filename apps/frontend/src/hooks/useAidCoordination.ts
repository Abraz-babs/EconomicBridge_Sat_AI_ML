'use client';

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';


/** Mirrors apps/api/schemas/aid_coordination.py — keep in sync. */

export type CoverageStatus = 'gap' | 'covered' | 'duplicated';

export interface AgencyCoverageSummary {
  agency_slug: string;
  agency_name: string;
  sector: string;
  lgas_covered: string[];
  beneficiaries_served: number;
}

export interface LgaPoint {
  lga: string;
  lon: number;
  lat: number;
  agency_count: number;
  status: CoverageStatus;
  agency_slugs: string[];
}

export interface CoverageMatrixRow {
  agency_slug: string;
  agency_name: string;
  row: number[];
}

export interface AidCoordinationStats {
  tenant_id: string;
  active_agencies: number;
  total_lgas: number;
  covered_lgas: number;
  coverage_pct: number;
  duplication_pct: number;
  gap_lgas: string[];
  agencies: AgencyCoverageSummary[];
  matrix: CoverageMatrixRow[];
  lga_columns: string[];
  lga_points: LgaPoint[];
  sources: string[];
}


export interface UseAidCoordinationParams {
  tenantId: string;
  enabled?: boolean;
}


export function useAidCoordination(
  params: UseAidCoordinationParams,
): UseQueryResult<AidCoordinationStats, ApiException> {
  return useQuery<AidCoordinationStats, ApiException>({
    queryKey: ['aid-coordination', params.tenantId],
    enabled: params.enabled !== false && Boolean(params.tenantId),
    queryFn: async ({ signal }) => {
      const envelope: SuccessEnvelope<AidCoordinationStats> =
        await apiFetch<AidCoordinationStats>(
          '/aid_coordination/coverage',
          { tenantId: params.tenantId, signal },
        );
      return envelope.data;
    },
  });
}
