'use client';

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, ingestionFetch } from '@/lib/api';

/** Mirrors apps/ingestion/routers/passes.py — keep in sync. */
export interface SatellitePass {
  satellite_name: string;
  satellite_group: 'S1' | 'S2' | 'VIIRS' | 'MODIS';
  norad_id: number;
  observer_lat: number;
  observer_lon: number;
  start_utc: string;
  max_utc: string;
  end_utc: string;
  max_elevation_deg: number;
  max_azimuth_compass: string;
  duration_seconds: number;
}

export interface PassesUpcomingResponse {
  tenant_id: string;
  observer_lat: number;
  observer_lon: number;
  days: number;
  min_elevation_deg: number;
  satellites_queried: string[];
  passes: SatellitePass[];
  total: number;
}

export interface UseSatellitePassesParams {
  tenantId: string | null | undefined;
  days?: number;
  /** Override the default satellite list. */
  satellites?: string[];
}

/**
 * Fetch upcoming satellite passes for a tenant from the ingestion service.
 *
 * The result is cached for 5 minutes — passes are predicted from orbital
 * elements that change slowly, so even an hour-old answer is correct to
 * the second. The 5-minute staleTime keeps the UI smooth while still
 * picking up new N2YO data over the course of a long session.
 */
export function useSatellitePasses(
  params: UseSatellitePassesParams,
): UseQueryResult<PassesUpcomingResponse, ApiException> {
  const tenantId = params.tenantId ?? null;
  const days = params.days ?? 2;

  return useQuery<PassesUpcomingResponse, ApiException>({
    queryKey: ['satellite-passes', tenantId, days, params.satellites?.join(',') ?? null],
    enabled: !!tenantId,
    staleTime: 5 * 60 * 1000,        // 5 min
    gcTime: 30 * 60 * 1000,          // 30 min
    refetchOnWindowFocus: false,     // pass times don't drift on focus
    queryFn: async ({ signal }) => {
      const search = new URLSearchParams();
      search.set('tenant_id', tenantId as string);
      search.set('days', String(days));
      for (const sat of params.satellites ?? []) {
        search.append('satellites', sat);
      }
      return ingestionFetch<PassesUpcomingResponse>(
        `/passes/upcoming?${search.toString()}`,
        { signal },
      );
    },
  });
}

// ─── Derived helpers ───────────────────────────────────────────────────────


/** The single next pass strictly in the future, or null if none. */
export function pickNextPass(
  passes: SatellitePass[] | undefined,
  now: Date = new Date(),
): SatellitePass | null {
  if (!passes || passes.length === 0) return null;
  const future = passes
    .filter((p) => new Date(p.start_utc).getTime() > now.getTime())
    .sort(
      (a, b) =>
        new Date(a.start_utc).getTime() - new Date(b.start_utc).getTime(),
    );
  return future[0] ?? null;
}

/** The most recent past pass within the last 12 hours, or null. */
export function pickLastPass(
  passes: SatellitePass[] | undefined,
  now: Date = new Date(),
): SatellitePass | null {
  if (!passes || passes.length === 0) return null;
  const cutoff = now.getTime() - 12 * 60 * 60 * 1000;
  const past = passes
    .filter((p) => {
      const t = new Date(p.start_utc).getTime();
      return t <= now.getTime() && t >= cutoff;
    })
    .sort(
      (a, b) =>
        new Date(b.start_utc).getTime() - new Date(a.start_utc).getTime(),
    );
  return past[0] ?? null;
}

/** Minutes between `instant` and `now` — signed (negative = past). */
export function minutesUntil(instant: string, now: Date = new Date()): number {
  return Math.round((new Date(instant).getTime() - now.getTime()) / 60000);
}
