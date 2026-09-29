'use client';

/**
 * The Overview's live panels (apps/api/routers/overview_live.py). Mirrors the
 * API schemas; keep in sync. Every number is read from what the feeds recorded
 * — these replaced a hard-coded status bar, six invented trend bars, and a
 * typed-in "conflict risk" per state (2026-09-29).
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';

export interface FeedState {
  source: string;
  label: string;
  last_success_at: string | null;
  last_status: string | null;
  max_age_hours: number;
  current: boolean;
}

export interface SystemStatusData {
  feeds: FeedState[];
  current: number;
  total: number;
  last_ingestion_at: string | null;
}

export interface MonthReadings { month: string; readings: number; runs: number }

export interface PilotSignals {
  tenant_id: string;
  storms: number;
  detections: number;
  land_alerts: number;
  villages: number;
  dark_villages: number;
  total: number;
}

export interface SignalsData { days: number; land_alert_days: number; pilots: PilotSignals[] }

async function get<T>(path: string, signal: AbortSignal): Promise<T> {
  const env: SuccessEnvelope<T> = await apiFetch<T>(path, { signal });
  return env.data;
}

export function useSystemStatus(): UseQueryResult<SystemStatusData, ApiException> {
  return useQuery<SystemStatusData, ApiException>({
    queryKey: ['overview-live', 'system'],
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
    queryFn: ({ signal }) => get<SystemStatusData>('/overview/system_status', signal),
  });
}

export function useReadingsTrend(): UseQueryResult<{ months: MonthReadings[] }, ApiException> {
  return useQuery<{ months: MonthReadings[] }, ApiException>({
    queryKey: ['overview-live', 'trend'],
    staleTime: 30 * 60_000,
    queryFn: ({ signal }) => get<{ months: MonthReadings[] }>('/overview/readings_trend', signal),
  });
}

export function useOverviewSignals(): UseQueryResult<SignalsData, ApiException> {
  return useQuery<SignalsData, ApiException>({
    queryKey: ['overview-live', 'signals'],
    staleTime: 10 * 60_000,
    queryFn: ({ signal }) => get<SignalsData>('/overview/signals', signal),
  });
}
