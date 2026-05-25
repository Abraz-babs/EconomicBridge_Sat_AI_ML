'use client';

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';


export type ConnectivityBand = 'no_signal' | 'limited' | 'basic' | 'broadband';


export interface SkillsIndicatorRow {
  id: string;
  tenant_id: string;
  lga: string;
  location: { lon: number; lat: number };
  school_count: number;
  school_density_per_10k: number;
  internet_coverage_pct: number;
  connectivity_band: ConnectivityBand;
  mobile_coverage_pct: number;
  electricity_reliability: number;
  youth_population: number;
  learning_gap_index: number;
  observed_at: string;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface SkillsStatsData {
  tenant_id: string;
  total_lgas: number;
  median_internet_coverage_pct: number;
  median_school_density: number;
  total_schools: number;
  total_youth_population: number;
  best_connectivity_lga: string | null;
  worst_gap_lga: string | null;
  most_underserved_lga: string | null;
  most_schools_lga: string | null;
  indicators: SkillsIndicatorRow[];
  sources: string[];
}


export interface UseSkillsBridgeParams {
  tenantId: string;
  enabled?: boolean;
}


export function useSkillsBridge(
  params: UseSkillsBridgeParams,
): UseQueryResult<SkillsStatsData, ApiException> {
  return useQuery<SkillsStatsData, ApiException>({
    queryKey: ['skills-bridge', params.tenantId],
    enabled: params.enabled !== false && Boolean(params.tenantId),
    queryFn: async ({ signal }) => {
      const envelope: SuccessEnvelope<SkillsStatsData> =
        await apiFetch<SkillsStatsData>(
          '/skills/indicators',
          { tenantId: params.tenantId, signal },
        );
      return envelope.data;
    },
  });
}
