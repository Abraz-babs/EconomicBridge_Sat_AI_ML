'use client';

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';

/** Mirrors apps/api/schemas/poverty.py VillageLightData — keep in sync. */
export interface VillageLightStats {
  villages: number;
  unlit: number;
  dim: number;
  lit: number;
  unknown: number;
  unlit_both_seasons: number;
  people: number;
  people_unlit: number;
  under5_unlit: number;
}

export interface LgaLightRow {
  lga: string;
  villages: number;
  unlit: number;
  people_unlit: number;
  under5_unlit: number;
}

export interface UnlitVillage {
  name: string;
  ward: string | null;
  lga: string | null;
  location: { lon: number; lat: number };
  people: number;
  under5: number;
  radiance_dry: number | null;
  radiance_wet: number | null;
  light_class_wet: string | null;
}

/** [lon, lat, dry class, wet class, people]; classes 0 unlit · 1 dim · 2 lit · 3 unknown. */
export type VillagePoint = [number, number, number, number, number];

export interface VillageLight {
  period: string | null;
  periods: string[];
  dry_window: string | null;
  wet_window: string | null;
  sources: string | null;
  stats: VillageLightStats | null;
  lgas: LgaLightRow[];
  top_unlit: UnlitVillage[];
  points: VillagePoint[];
}

/** GET /api/v1/economic_visibility/village-light — measured night light and
 *  people at every real village of the tenant (latest round by default). */
export function useVillageLight(tenantId: string): UseQueryResult<VillageLight, ApiException> {
  return useQuery<VillageLight, ApiException>({
    queryKey: ['village-light', tenantId],
    enabled: Boolean(tenantId),
    // A yearly measurement: no need to refetch on every focus.
    staleTime: 60 * 60 * 1000,
    queryFn: async ({ signal }) => {
      const envelope: SuccessEnvelope<VillageLight> = await apiFetch<VillageLight>(
        '/economic_visibility/village-light?top=40',
        { tenantId, signal },
      );
      return envelope.data;
    },
  });
}
