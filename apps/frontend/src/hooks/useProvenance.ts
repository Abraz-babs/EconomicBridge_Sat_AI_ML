'use client';

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch } from '@/lib/api';

/** Mirrors apps/api/schemas/provenance.py. */
export interface FeedProvenance {
  module: string;
  signal: string;
  satellites: string[];
  provider: string;
  license: string;
  attribution: string;
  kind: 'live' | 'modelled' | 'derived';
  cadence: string;
  method: string;
}

export interface ComputeBudget {
  provider: string;
  tier: string;
  monthly_pu: number;
  monthly_requests: number;
  note: string;
}

export interface ProvenanceData {
  feeds: FeedProvenance[];
  compute: ComputeBudget;
  summary: string;
}

/** GET /api/v1/provenance — static data-source catalog (no tenant needed). */
export function useProvenance(): UseQueryResult<ProvenanceData, ApiException> {
  return useQuery<ProvenanceData, ApiException>({
    queryKey: ['provenance'],
    staleTime: 60 * 60 * 1000, // catalog only changes on deploy
    queryFn: async ({ signal }) => {
      const env = await apiFetch<ProvenanceData>('/provenance', { signal });
      return env.data;
    },
  });
}
