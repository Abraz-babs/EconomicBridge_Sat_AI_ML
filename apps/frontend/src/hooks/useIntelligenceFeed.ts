'use client';

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';


/** Mirrors apps/api/schemas/intelligence_feed.py — keep in sync. */
export type FeedKind =
  | 'alert_event'
  | 'ndvi_anomaly'
  | 'shock_event'
  | 'aid_coverage'
  | 'poverty_village';

export type FeedTag = 'Disaster' | 'Agriculture' | 'Poverty' | 'Aid' | 'Encroachment';
export type FeedSeverity = 'low' | 'medium' | 'high' | 'critical';

export interface FeedEvent {
  kind: FeedKind;
  tenant_id: string;
  title: string;
  region: string | null;
  tag: FeedTag;
  severity: FeedSeverity;
  source: string;
  observed_at: string;
}

interface IntelligenceFeedData {
  events: FeedEvent[];
  total: number;
}


export interface UseIntelligenceFeedParams {
  limit?: number;
  enabled?: boolean;
  /** Refetch interval in ms. Default 60s — matches the v0.3 panel meta. */
  refetchIntervalMs?: number;
}


export function useIntelligenceFeed(
  params: UseIntelligenceFeedParams = {},
): UseQueryResult<IntelligenceFeedData, ApiException> {
  const limit = params.limit ?? 20;
  return useQuery<IntelligenceFeedData, ApiException>({
    queryKey: ['intelligence-feed', limit],
    enabled: params.enabled !== false,
    refetchInterval: params.refetchIntervalMs ?? 60_000,
    queryFn: async ({ signal }) => {
      const search = new URLSearchParams({ limit: String(limit) });
      const envelope: SuccessEnvelope<IntelligenceFeedData> =
        await apiFetch<IntelligenceFeedData>(
          `/intelligence/feed?${search.toString()}`,
          { signal },
        );
      return envelope.data;
    },
  });
}
