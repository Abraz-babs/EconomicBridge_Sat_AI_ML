'use client';

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { ApiException, apiFetch, downloadFile, type SuccessEnvelope } from '@/lib/api';

export interface ReportMetric { label: string; display: string }
export interface ReportBreakdownRow { key: string; count: number }
export interface ReportSummary {
  module: string;
  label: string;
  date_from: string;
  date_to: string;
  total_rows: number;
  metrics: ReportMetric[];
  breakdown: { title: string; rows: ReportBreakdownRow[] } | null;
}
export interface ReportModule { key: string; label: string }

function qs(module: string, from: string, to: string): string {
  const p = new URLSearchParams({ module });
  if (from) p.set('from', from);
  if (to) p.set('to', to);
  return `?${p.toString()}`;
}

/** The modules that support reports (drives the picker). */
export function useReportModules(): UseQueryResult<ReportModule[], ApiException> {
  return useQuery<ReportModule[], ApiException>({
    queryKey: ['report-modules'],
    staleTime: 5 * 60 * 1000,
    queryFn: async ({ signal }) => {
      const env: SuccessEnvelope<ReportModule[]> =
        await apiFetch<ReportModule[]>('/reports/modules', { signal });
      return env.data;
    },
  });
}

/** Aggregated summary for a tenant + module over a date window. */
export function useReportSummary(
  tenantId: string, module: string, from: string, to: string,
): UseQueryResult<ReportSummary, ApiException> {
  return useQuery<ReportSummary, ApiException>({
    queryKey: ['report-summary', tenantId, module, from, to],
    enabled: Boolean(tenantId && module),
    staleTime: 60 * 1000,
    queryFn: async ({ signal }) => {
      const env: SuccessEnvelope<ReportSummary> =
        await apiFetch<ReportSummary>(`/reports/summary${qs(module, from, to)}`, { tenantId, signal });
      return env.data;
    },
  });
}

export function downloadReportCsv(tenantId: string, module: string, from: string, to: string): Promise<void> {
  return downloadFile(`/reports/export.csv${qs(module, from, to)}`,
    `${tenantId}_${module}_${from || 'all'}_${to || 'now'}.csv`, { tenantId });
}

export function downloadReportPdf(tenantId: string, module: string, from: string, to: string): Promise<void> {
  return downloadFile(`/reports/export.pdf${qs(module, from, to)}`,
    `${tenantId}_${module}_${from || 'all'}_${to || 'now'}.pdf`, { tenantId });
}

// ─── Scheduled report subscriptions (super-admin) ───────────────────────────

export interface ReportSubscription {
  id: string;
  tenant_id: string;
  module: string;
  frequency: string;
  recipient_email: string;
  enabled: boolean;
  last_sent_at: string | null;
  created_at: string | null;
}

export interface NewSubscription {
  tenant_id: string;
  module: string;
  frequency: string;
  recipient_email: string;
}

export function useReportSubscriptions(): UseQueryResult<ReportSubscription[], ApiException> {
  return useQuery<ReportSubscription[], ApiException>({
    queryKey: ['report-subscriptions'],
    staleTime: 15 * 1000,
    queryFn: async ({ signal }) => {
      const env: SuccessEnvelope<ReportSubscription[]> =
        await apiFetch<ReportSubscription[]>('/reports/subscriptions', { signal });
      return env.data;
    },
  });
}

export function useCreateReportSubscription(): UseMutationResult<
  ReportSubscription, ApiException, NewSubscription
> {
  const qc = useQueryClient();
  return useMutation<ReportSubscription, ApiException, NewSubscription>({
    mutationFn: async (body) => {
      const env: SuccessEnvelope<ReportSubscription> =
        await apiFetch<ReportSubscription>('/reports/subscriptions', { method: 'POST', body });
      return env.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['report-subscriptions'] }),
  });
}

export function useDeleteReportSubscription(): UseMutationResult<void, ApiException, string> {
  const qc = useQueryClient();
  return useMutation<void, ApiException, string>({
    mutationFn: async (id) => {
      await apiFetch(`/reports/subscriptions/${id}`, { method: 'DELETE' });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['report-subscriptions'] }),
  });
}
