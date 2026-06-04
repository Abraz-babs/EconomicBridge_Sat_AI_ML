'use client';

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

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
