'use client';

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';

/** Mirrors apps/api/schemas/farmland.py — keep in sync. */
export type AlertSeverity = 'critical' | 'high' | 'medium' | 'low';
export type AlertStatus =
  | 'pending_review'
  | 'acknowledged'
  | 'resolved'
  | 'dismissed';
export type AlertType = 'conflict' | 'flood' | 'crop_disease' | 'drought';

export interface AlertResponse {
  id: string;
  tenant_id: string;
  alert_type: AlertType;
  severity: AlertSeverity;
  status: AlertStatus;
  zone_name: string | null;
  lga: string | null;
  location: { lon: number; lat: number } | null;
  confidence_score: number | null;
  affected_area_ha: number | null;
  livelihoods_at_risk: number | null;
  economic_value_ngn: number | null;
  predicted_breach_hours: number | null;
  satellite_source: string | null;
  satellite_pass_time: string | null;
  model_name: string | null;
  model_version: string | null;
  human_review_required: boolean;
  agencies_notified: string[] | null;
  created_at: string;
  updated_at: string;
}

interface AlertListData {
  alerts: AlertResponse[];
}

export interface UseFarmlandAlertsParams {
  /** Tenant slug for X-Tenant-Id (required). */
  tenantId: string;
  page?: number;
  perPage?: number;
  severity?: AlertSeverity[];
  status?: AlertStatus[];
  alertType?: AlertType[];
  /** Disable the fetch entirely (e.g. when tenantId isn't ready yet). */
  enabled?: boolean;
}

export interface FarmlandAlertsResult {
  alerts: AlertResponse[];
  pagination: { page: number; per_page: number; total: number } | null;
  traceId: string | null;
}

function buildQueryString(params: UseFarmlandAlertsParams): string {
  const search = new URLSearchParams();
  if (params.page) search.set('page', String(params.page));
  if (params.perPage) search.set('per_page', String(params.perPage));
  params.severity?.forEach((s) => search.append('severity', s));
  params.status?.forEach((s) => search.append('status', s));
  params.alertType?.forEach((t) => search.append('alert_type', t));
  const query = search.toString();
  return query ? `?${query}` : '';
}

export function useFarmlandAlerts(
  params: UseFarmlandAlertsParams,
): UseQueryResult<FarmlandAlertsResult, ApiException> {
  return useQuery<FarmlandAlertsResult, ApiException>({
    queryKey: [
      'farmland-alerts',
      params.tenantId,
      params.page ?? 1,
      params.perPage ?? 20,
      params.severity ?? null,
      params.status ?? null,
      params.alertType ?? null,
    ],
    enabled: params.enabled !== false && Boolean(params.tenantId),
    queryFn: async ({ signal }) => {
      const envelope: SuccessEnvelope<AlertListData> = await apiFetch<AlertListData>(
        `/farmland/alerts${buildQueryString(params)}`,
        { tenantId: params.tenantId, signal },
      );
      return {
        alerts: envelope.data.alerts,
        pagination: envelope.meta.pagination,
        traceId: envelope.meta.trace_id,
      };
    },
  });
}
