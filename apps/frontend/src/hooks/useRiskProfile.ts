'use client';

/**
 * GET /api/v1/cropguard/risk-profile — the pre-season risk profile of every LGA
 * in the active state (insurer accounts and the operator). Mirrors
 * apps/api/schemas/risk_profile.py RiskProfileData; keep in sync.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';

export type Band = 'high' | 'moderate' | 'low' | 'none';
export type BandKind = 'flood' | 'drought' | 'rains';

export interface MappedFlood {
  label: string;
  area_pct: number | null;
  crop_pct: number | null;
  crop_ha: number | null;
  cloud_pct: number | null;
}

export interface RiskFigures {
  area_km2: number;
  cropland_ha: number;
  cropland_pct: number | null;
  flood: {
    rp10_crop_pct: number | null;
    rp10_crop_ha: number | null;
    rp100_crop_pct: number | null;
    rp100_crop_ha: number | null;
    rp100_deep_crop_pct: number | null;
    mapped: Record<string, MappedFlood>;
  };
  rain: {
    season_months: number[];
    normal_mm: number;
    cv_pct: number | null;
    totals: Record<string, number>;
    drought_seasons: number[];
    worst: { year: number; pct_of_normal: number | null };
    first_year: number;
    last_year: number;
  };
  rains?: {
    years: number[];
    onset_median: string | null;
    false_starts: number[];
    late_onsets: number[];
    long_dry_spells: number[];
    failed_seasons: number[];
  };
  exposure: { villages: number; people: number; under5: number } | null;
  register: { type: string; date: string | null; name: string }[];
  centroid: [number, number];
  outline: { type: 'Polygon' | 'MultiPolygon'; coordinates: unknown };
}

export interface RiskLga {
  lga: string;
  band_flood: Band;
  band_drought: Band;
  band_rains: Band;
  figures: RiskFigures;
}

export interface RiskProfile {
  available: boolean;
  through_season: number | null;
  first_season: number | null;
  rains_first_season: number | null;
  method: string | null;
  measured_at: string | null;
  rule: Record<BandKind, string>;
  summary: {
    lgas: number;
    cropland_ha: number;
    rp10_cropland_ha: number;
    rp100_cropland_ha: number;
    mapped: { key: string; label: string; cropland_ha: number; lgas_with_water: number; agreement: number | null }[];
    bands: Record<BandKind, Record<Band, number>>;
    seasons: number;
    drought_seasons_min: number | null;
    drought_seasons_max: number | null;
    rains_seasons: number | null;
    rains_failed_min: number | null;
    rains_failed_max: number | null;
    people: number | null;
  } | null;
  lgas: RiskLga[];
  overlays: { layer: string; label: string; bounds: [number, number, number, number]; image: string }[];
  sources: string | null;
}

export function useRiskProfile(tenantId: string, enabled = true): UseQueryResult<RiskProfile, ApiException> {
  return useQuery<RiskProfile, ApiException>({
    queryKey: ['risk-profile', tenantId],
    enabled: Boolean(tenantId) && enabled,
    // A round is measured once a year, before planting.
    staleTime: 6 * 60 * 60 * 1000,
    queryFn: async ({ signal }) => {
      const envelope: SuccessEnvelope<RiskProfile> = await apiFetch<RiskProfile>(
        '/cropguard/risk-profile', { tenantId, signal },
      );
      return envelope.data;
    },
  });
}
