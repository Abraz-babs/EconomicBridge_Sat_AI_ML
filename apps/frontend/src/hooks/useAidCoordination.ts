'use client';

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';


/** Mirrors apps/api/schemas/aid_coordination.py — keep in sync. */

/** gap = no reported activity site · covered = reported activity ·
 *  duplicated = 2+ organisations working in the SAME sector there. */
export type CoverageStatus = 'gap' | 'covered' | 'duplicated';

export interface AgencyCoverageSummary {
  agency_slug: string;
  agency_name: string;
  sector: string;
  lgas_covered: string[];
  /** Null for IATI records — never invented. */
  beneficiaries_served: number | null;
  activities: number;
  statewide_activities: number;
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
  /** "Statewide", or "Countrywide" for Ghana / Senegal. */
  statewide_label: string;
  statewide_orgs: number;
  attribution: string | null;
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
