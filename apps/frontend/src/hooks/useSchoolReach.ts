'use client';

/**
 * GET /api/v1/skills/reach — the school reach list. Mirrors
 * apps/api/schemas/skills.py SchoolReachData; keep in sync.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';

export type SchoolLight = 'dark' | 'lit' | 'unknown';

export interface ReachSchool {
  name: string;
  category: string | null;
  management: string | null;
  lga: string | null;
  location: { lon: number; lat: number };
  /** dark: no village within 2 km lit or dim · lit: one is · unknown: no named village within 2 km. */
  light: SchoolLight;
  /** Place on the reach list (dark schools, one per village, most people first). */
  rank: number | null;
  village: string | null;
  ward: string | null;
  village_km: number | null;
  village_light: string | null;
  people: number | null;
  under5: number | null;
  villages_2km: number;
  lit_villages_2km: number;
  people_2km: number;
  under5_2km: number;
}

export interface ReachLga {
  lga: string;
  schools: number;
  assessed: number;
  dark: number;
  dark_pct: number | null;
}

export interface SchoolReach {
  available: boolean;
  reason: string | null;
  state: string | null;
  light_round: string | null;
  light_window: string | null;
  schools: number;
  assessed: number;
  dark: number;
  dark_pct: number | null;
  primary: number;
  secondary: number;
  dark_villages: number;
  people: number;
  under5: number;
  lgas: ReachLga[];
  rows: ReachSchool[];
}

export function useSchoolReach(tenantId: string): UseQueryResult<SchoolReach, ApiException> {
  return useQuery<SchoolReach, ApiException>({
    queryKey: ['school-reach', tenantId],
    enabled: Boolean(tenantId),
    // Schools and night light change yearly at most.
    staleTime: 60 * 60 * 1000,
    queryFn: async ({ signal }) => {
      const envelope: SuccessEnvelope<SchoolReach> = await apiFetch<SchoolReach>(
        '/skills/reach', { tenantId, signal },
      );
      return envelope.data;
    },
  });
}
