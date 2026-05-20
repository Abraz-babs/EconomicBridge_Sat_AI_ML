'use client';

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, ingestionFetch } from '@/lib/api';

/** Mirrors apps/ingestion/routers/imagery.py — keep in sync. */
export interface RecentScene {
  scene_id: string;
  collection: string;
  captured_at: string;
  cloud_cover_pct: number | null;
  mgrs_tile: string | null;
  bbox_west: number;
  bbox_south: number;
  bbox_east: number;
  bbox_north: number;
  self_href: string | null;
}

export interface ImageryRecentResponse {
  tenant_id: string;
  collection: string;
  days: number;
  bbox: number[];
  max_cloud_cover_pct: number | null;
  total: number;
  scenes: RecentScene[];
  fetched_at: string;
  cached: boolean;
  cache_ttl_seconds: number;
}

/**
 * Fetch the most-recent Sentinel scenes covering a tenant ROI for a
 * single collection.
 *
 * Backed by a 10-minute server-side TTL cache (see imagery.py) so
 * polling every page load is cheap. Frontend `staleTime` mirrors that
 * so React Query also avoids redundant fetches inside the same tab.
 */
export function useRecentImagery(
  tenantId: string | null | undefined,
  collection: 'sentinel-2-l2a' | 'sentinel-1-grd',
): UseQueryResult<ImageryRecentResponse, ApiException> {
  return useQuery<ImageryRecentResponse, ApiException>({
    queryKey: ['recent-imagery', tenantId, collection],
    enabled: !!tenantId,
    staleTime: 10 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: async ({ signal }) => {
      const search = new URLSearchParams();
      search.set('tenant_id', tenantId as string);
      search.set('collection', collection);
      search.set('days', '14');
      search.set('limit', '10');
      return ingestionFetch<ImageryRecentResponse>(
        `/imagery/recent?${search.toString()}`,
        { signal },
      );
    },
  });
}

// ─── Derived helpers ───────────────────────────────────────────────────────


/** The most recent scene (max `captured_at`), or null if none. */
export function newestScene(
  scenes: RecentScene[] | undefined,
): RecentScene | null {
  if (!scenes || scenes.length === 0) return null;
  return scenes.reduce((best, s) =>
    new Date(s.captured_at).getTime() > new Date(best.captured_at).getTime()
      ? s
      : best,
  );
}

/** Hours between `iso` and `now`, rounded — non-negative. */
export function hoursAgo(iso: string, now: Date = new Date()): number {
  const ms = now.getTime() - new Date(iso).getTime();
  return Math.max(0, Math.round(ms / 3_600_000));
}
