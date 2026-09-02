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


/** Per-detector health, so a live feed cannot mask a dead one. */
interface FeedStatusWire {
  source: string;
  label: string;
  last_success_at?: string | null;
  last_run_at?: string | null;
  last_status?: string | null;
  last_error?: string | null;
  active_events?: number;
}

export interface FeedStatus {
  source: string;
  label: string;
  lastSuccessAt: string | null;
  lastRunAt: string | null;
  lastStatus: string | null;
  lastError: string | null;
  activeEvents: number;
}

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
  // Null for ROI-level satellite scans that flag a signal without quantifying
  // onset / area / population (the on-demand detector + seed fill these).
  projected_onset_hours: number | null;
  affected_area_km2: number | null;
  population_at_risk: number | null;
  lga: string | null;
  zone_name: string | null;
  location: { lon: number; lat: number } | null;
  metrics: Record<string, number>;
  source: string;
  created_at: string;
}

interface ShockEventListData {
  events: ShockEventRow[];
  // Monitoring status — proves the detector scanned recently even when no
  // shock is active (0 = scanned, all clear).
  last_scan_at?: string | null;
  active_shock_count?: number;
  feeds?: FeedStatusWire[];
}

export interface ShockEventsResult {
  events: ShockEventRow[];
  lastScanAt: string | null;
  activeShockCount: number;
  feeds: FeedStatus[];
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
): UseQueryResult<ShockEventsResult, ApiException> {
  const limit = params.limit ?? 10;
  return useQuery<ShockEventsResult, ApiException>({
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
      return {
        events: envelope.data.events,
        lastScanAt: envelope.data.last_scan_at ?? null,
        activeShockCount: envelope.data.active_shock_count ?? 0,
        feeds: (envelope.data.feeds ?? []).map((f) => ({
          source: f.source,
          label: f.label,
          lastSuccessAt: f.last_success_at ?? null,
          lastRunAt: f.last_run_at ?? null,
          lastStatus: f.last_status ?? null,
          lastError: f.last_error ?? null,
          activeEvents: f.active_events ?? 0,
        })),
      };
    },
  });
}


// ─── Storms (half-hourly IMERG) ───────────────────────────────────────────
//
// Kept separate from ShockEventRow on purpose. A storm is a MEASUREMENT of
// what fell — depth, rate, duration — and a shock event is a claim that
// something went wrong. Folding storms into the events list would have meant
// labelling them 'flood', which is the conflation that scored 0 of 11 on the
// Kebbi 2024 backtest.

export interface StormRow {
  id: string;
  tenant_id: string;
  lga: string;
  location: { lon: number; lat: number } | null;
  started_at: string;
  ended_at: string;
  peak_at: string;
  /** True when a calendar-day total would have split this storm in two —
   *  the defect that made the platform miss the 30 Aug Abuja storm. */
  crosses_midnight_utc: boolean;
  peak_mm_hr: number;
  total_mm: number;
  max_1h_mm: number | null;
  max_3h_mm: number | null;
  max_6h_mm: number | null;
  duration_h: number | null;
  /** Rank within this LGA's OWN record. Never render without baselineDays. */
  percentile_1h: number | null;
  percentile_3h: number | null;
  baseline_days: number | null;
  severity: Severity | null;
  detector_version: string;
  detected_at: string;
}

export interface StormMeasurement {
  lga: string;
  day: string;
  max_1h_mm: number | null;
  max_3h_mm: number | null;
  peak_mm_hr: number | null;
  slices_seen: number;
  slices_expected: number;
}

interface StormListWire {
  storms: StormRow[];
  measured: StormMeasurement[];
  measured_day?: string | null;
  measured_lga_count?: number;
  baseline_days?: number;
  rateable_lgas?: number;
  known_lgas?: number;
  min_baseline_days?: number;
  last_scan_at?: string | null;
}

export interface StormsResult {
  storms: StormRow[];
  /** Wettest LGAs on the latest scanned day. Lets an empty storms list read
   *  as "scanned, nothing exceptional" rather than as a dead feed. */
  measured: StormMeasurement[];
  measuredDay: string | null;
  measuredLgaCount: number;
  /** Calendar days of archive. NOT the per-place figure: a place records a
   *  day only when rain fell there, so a dry district can sit on 4 days of
   *  its own history while the archive holds 29. */
  baselineDays: number;
  /** Places with enough of their own rain-day history to be ranked, out of
   *  every place seen raining at all. This is what actually gates alerting. */
  rateableLgas: number;
  knownLgas: number;
  minBaselineDays: number;
  lastScanAt: string | null;
}


export function useStorms(params: {
  tenantId: string;
  limit?: number;
  enabled?: boolean;
}): UseQueryResult<StormsResult, ApiException> {
  const limit = params.limit ?? 10;
  return useQuery<StormsResult, ApiException>({
    queryKey: ['shockguard-storms', params.tenantId, limit],
    enabled: params.enabled !== false && Boolean(params.tenantId),
    queryFn: async ({ signal }) => {
      const envelope: SuccessEnvelope<StormListWire> =
        await apiFetch<StormListWire>(
          `/shockguard/storms?limit=${limit}`,
          { tenantId: params.tenantId, signal },
        );
      return {
        storms: envelope.data.storms ?? [],
        measured: envelope.data.measured ?? [],
        measuredDay: envelope.data.measured_day ?? null,
        measuredLgaCount: envelope.data.measured_lga_count ?? 0,
        baselineDays: envelope.data.baseline_days ?? 0,
        rateableLgas: envelope.data.rateable_lgas ?? 0,
        knownLgas: envelope.data.known_lgas ?? 0,
        minBaselineDays: envelope.data.min_baseline_days ?? 21,
        lastScanAt: envelope.data.last_scan_at ?? null,
      };
    },
  });
}
