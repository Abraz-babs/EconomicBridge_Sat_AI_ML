'use client';

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { ApiException, ingestionFetch } from '@/lib/api';

/**
 * Hooks targeting the ingestion microservice (port 8001) for Slice 10
 * observability + manual triggers. The ingestion service exposes a
 * plain JSON envelope (no `success/data/meta` wrapping) so we use
 * `ingestionFetch` from lib/api.ts, not `apiFetch`.
 */

// ─── /api/v1/scheduler/jobs ──────────────────────────────────────────────


export interface SchedulerJob {
  id: string;
  name: string;
  next_run_time: string | null;
  trigger: string;
}

export interface SchedulerJobsData {
  running: boolean;
  jobs: SchedulerJob[];
}

export function useSchedulerJobs(): UseQueryResult<SchedulerJobsData, ApiException> {
  return useQuery<SchedulerJobsData, ApiException>({
    queryKey: ['scheduler-jobs'],
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    queryFn: ({ signal }) =>
      ingestionFetch<SchedulerJobsData>('/scheduler/jobs', { signal }),
  });
}


// ─── /api/v1/scheduler/runs/recent ───────────────────────────────────────


export interface IngestionRunRow {
  run_id: string;
  tenant_id: string | null;
  source: string;
  status: string;
  trigger: string;
  started_at: string;
  finished_at: string | null;
  duration_seconds: number | null;
  records_ingested: number;
  error_message: string | null;
}

export interface RecentRunsData {
  rows: IngestionRunRow[];
  total: number;
}

export interface UseRecentRunsParams {
  limit?: number;
  tenantId?: string | null;
  source?: string | null;
}

export function useRecentRuns(
  params: UseRecentRunsParams = {},
): UseQueryResult<RecentRunsData, ApiException> {
  const limit = params.limit ?? 30;
  const tenantId = params.tenantId ?? null;
  const source = params.source ?? null;
  return useQuery<RecentRunsData, ApiException>({
    queryKey: ['scheduler-recent-runs', limit, tenantId, source],
    staleTime: 15_000,
    refetchOnWindowFocus: false,
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams();
      qs.set('limit', String(limit));
      if (tenantId) qs.set('tenant_id', tenantId);
      if (source) qs.set('source', source);
      return ingestionFetch<RecentRunsData>(
        `/scheduler/runs/recent?${qs.toString()}`,
        { signal },
      );
    },
  });
}


// ─── POST /api/v1/scheduler/jobs/{job_id}/run ────────────────────────────


export interface JobRunResult {
  job_id: string;
  result: Record<string, unknown>;
}

export function useRunSchedulerJob(): UseMutationResult<
  JobRunResult, ApiException, { jobId: string }
> {
  const qc = useQueryClient();
  return useMutation<JobRunResult, ApiException, { jobId: string }>({
    mutationFn: ({ jobId }) =>
      ingestionFetch<JobRunResult>(
        `/scheduler/jobs/${encodeURIComponent(jobId)}/run`,
        { method: 'POST' },
      ),
    onSuccess: () => {
      // The job will have populated ingestion_runs and (for conflict)
      // alert_events. Invalidate everything downstream so dashboards
      // pick up the new rows on their next visit.
      qc.invalidateQueries({ queryKey: ['scheduler-recent-runs'] });
      qc.invalidateQueries({ queryKey: ['farmland-alerts'] });
    },
  });
}


// ─── POST /api/v1/ingest/conflict ────────────────────────────────────────


export interface ConflictTriggerInput {
  tenantId: string;
  lookbackDays?: number;
}

export interface ConflictTriggerResult {
  tenant_id: string;
  clusters_built: number;
  predictions_made: number;
  alerts_written: number;
  skipped_below_threshold: number;
  skipped_capped: number;
  skipped_duplicates: number;
  error: string | null;
}

export function useTriggerConflictPipeline(): UseMutationResult<
  ConflictTriggerResult, ApiException, ConflictTriggerInput
> {
  const qc = useQueryClient();
  return useMutation<ConflictTriggerResult, ApiException, ConflictTriggerInput>({
    mutationFn: ({ tenantId, lookbackDays }) =>
      ingestionFetch<ConflictTriggerResult>('/ingest/conflict', {
        method: 'POST',
        body: {
          tenant_id: tenantId,
          ...(lookbackDays !== undefined ? { lookback_days: lookbackDays } : {}),
        },
      }),
    onSuccess: (_, variables) => {
      qc.invalidateQueries({ queryKey: ['scheduler-recent-runs'] });
      qc.invalidateQueries({
        queryKey: ['farmland-alerts', variables.tenantId],
      });
    },
  });
}
