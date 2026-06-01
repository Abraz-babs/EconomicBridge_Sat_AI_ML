'use client';

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';


export type ShockEventType = 'flood' | 'drought';
export type Severity = 'low' | 'medium' | 'high' | 'critical';
export type ConfidenceBand = 'HIGH' | 'MEDIUM' | 'LOW';


export interface FloodSeriesPoint {
  observed_at: string;
  backscatter_db: number;
}

export interface DroughtSeriesPoint {
  observed_at: string;
  lst_anomaly_c: number;
  ndvi_anomaly: number;
  stress_index: number;
}

export interface ShockScanData {
  event_id: string | null;
  tenant_id: string;
  event_type: ShockEventType;
  detector_name: string;
  detector_version: string;
  severity: Severity;
  confidence: number;
  confidence_band: ConfidenceBand;
  requires_human_review: boolean;
  triggered: boolean;
  projected_onset_hours: number;
  affected_area_km2: number;
  population_at_risk: number;
  metrics: Record<string, number>;
  flood_series: FloodSeriesPoint[];
  drought_series: DroughtSeriesPoint[];
  persisted: boolean;
  /** Set when a live request fell back to the modelled detector (sparse
   *  satellite coverage). Shown as a gentle info note, not an error. */
  notice?: string | null;
}

export type DataSource = 'synthetic' | 'live';

export interface ShockScanRequest {
  event_type: ShockEventType;
  demo_inject_anomaly?: boolean;
  persist?: boolean;
  /**
   * 'synthetic' (default) — deterministic per-tenant series; no live API
   * call; demo_inject_anomaly works.
   * 'live' — reads real Sentinel-1 / Sentinel-2 rows from
   * `tenant_<id>.satellite_observations`. Requires the operator to have
   * run `python -m scripts.ingest_satellite_observations` from apps/ingestion.
   * Drought stays synthetic (MODIS LST is Phase B).
   */
  data_source?: DataSource;
}


export interface ShockEventRow {
  id: string;
  tenant_id: string;
  event_type: ShockEventType;
  detector_name: string;
  detector_version: string;
  severity: Severity;
  confidence: number;
  confidence_band: ConfidenceBand;
  requires_human_review: boolean;
  projected_onset_hours: number;
  affected_area_km2: number;
  population_at_risk: number;
  lga: string | null;
  zone_name: string | null;
  location: { lon: number; lat: number } | null;
  metrics: Record<string, number>;
  source: string;
  created_at: string;
}

interface ShockEventListData {
  events: ShockEventRow[];
}


// ─── Scan mutation ────────────────────────────────────────────────────────


export function useShockScan(
  tenantId: string,
): UseMutationResult<ShockScanData, ApiException, ShockScanRequest> {
  const qc = useQueryClient();
  return useMutation<ShockScanData, ApiException, ShockScanRequest>({
    mutationFn: async (body) => {
      const envelope: SuccessEnvelope<ShockScanData> = await apiFetch<ShockScanData>(
        '/shockguard/scan',
        { method: 'POST', tenantId, body },
      );
      return envelope.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['shockguard-events', tenantId] });
    },
  });
}


// ─── List recent events ───────────────────────────────────────────────────


export interface UseShockEventsParams {
  tenantId: string;
  limit?: number;
  eventType?: ShockEventType;
  enabled?: boolean;
}


export function useShockEvents(
  params: UseShockEventsParams,
): UseQueryResult<{ events: ShockEventRow[] }, ApiException> {
  const limit = params.limit ?? 10;
  return useQuery<{ events: ShockEventRow[] }, ApiException>({
    queryKey: ['shockguard-events', params.tenantId, limit, params.eventType ?? null],
    enabled: params.enabled !== false && Boolean(params.tenantId),
    queryFn: async ({ signal }) => {
      const search = new URLSearchParams({ limit: String(limit) });
      if (params.eventType) search.set('event_type', params.eventType);
      const envelope: SuccessEnvelope<ShockEventListData> =
        await apiFetch<ShockEventListData>(
          `/shockguard/events?${search.toString()}`,
          { tenantId: params.tenantId, signal },
        );
      return { events: envelope.data.events };
    },
  });
}
