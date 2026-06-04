'use client';

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, downloadFile, type SuccessEnvelope } from '@/lib/api';

export interface ReportSummary {
  tenant_id: string;
  date_from: string;
  date_to: string;
  total_alerts: number;
  live_alerts: number;
  seed_alerts: number;
  by_severity: Record<string, number>;
  by_status: Record<string, number>;
  resolved: number;
  affected_area_ha: number;
  livelihoods_at_risk: number;
  economic_value_ngn: number;
}

function qs(from: string, to: string): string {
  const p = new URLSearchParams();
  if (from) p.set('from', from);
  if (to) p.set('to', to);
  const s = p.toString();
  return s ? `?${s}` : '';
}

/** Historical alert summary for a tenant over a date window. */
export function useReportSummary(
  tenantId: string, from: string, to: string,
): UseQueryResult<ReportSummary, ApiException> {
  return useQuery<ReportSummary, ApiException>({
    queryKey: ['report-summary', tenantId, from, to],
    enabled: Boolean(tenantId),
    staleTime: 60 * 1000,
    queryFn: async ({ signal }) => {
      const env: SuccessEnvelope<ReportSummary> =
        await apiFetch<ReportSummary>(`/reports/summary${qs(from, to)}`, { tenantId, signal });
      return env.data;
    },
  });
}

/** Download the alert history CSV for a tenant + window. */
export function downloadReportCsv(tenantId: string, from: string, to: string): Promise<void> {
  const fname = `${tenantId}_alerts_${from || 'all'}_${to || 'now'}.csv`;
  return downloadFile(`/reports/export.csv${qs(from, to)}`, fname, { tenantId });
}
