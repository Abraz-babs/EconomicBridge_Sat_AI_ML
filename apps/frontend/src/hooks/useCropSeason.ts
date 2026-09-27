'use client';

/**
 * GET /api/v1/cropguard/season — the season watch. Mirrors
 * apps/api/schemas/cropguard.py CropSeasonData; keep in sync.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';
import type { NearestPlace } from '@/lib/places';

export interface CropSeasonLga {
  lga: string;
  location: { lon: number; lat: number } | null;
  /** Farmland (crops + rangeland) that greened, keyed by season year. */
  farmland_ha: Record<string, number>;
  crops_ha: number | null;
  like_for_like_pct: number | null;
  seen_pct: number | null;
  stopped_growing: number;
}

export interface CropSeasonPatch {
  lga: string | null;
  kind: 'crops' | 'rangeland' | 'farmland';
  area_ha: number | null;
  peak_before: number | null;
  peak_now: number | null;
  location: { lon: number; lat: number } | null;
  detected_at: string | null;
  summary: string | null;
  nearest_place: NearestPlace | null;
}

export interface CropSeason {
  season_year: number | null;
  previous_year: number | null;
  years: number[];
  window_end: string | null;
  lgas: CropSeasonLga[];
  farmland_ha: number;
  like_for_like_pct: number | null;
  stopped_growing: number;
  stopped_crops: number;
  stopped_rangeland: number;
  patches: CropSeasonPatch[];
}

export function useCropSeason(tenantId: string): UseQueryResult<CropSeason, ApiException> {
  return useQuery<CropSeason, ApiException>({
    queryKey: ['crop-season', tenantId],
    enabled: Boolean(tenantId),
    staleTime: 30 * 60 * 1000,
    queryFn: async ({ signal }) => {
      const envelope: SuccessEnvelope<CropSeason> = await apiFetch<CropSeason>(
        '/cropguard/season', { tenantId, signal },
      );
      return envelope.data;
    },
  });
}
