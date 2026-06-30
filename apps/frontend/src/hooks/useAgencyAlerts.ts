'use client';

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';

// Government-agency EMAIL alert subscriptions (super-admin). Each row emails a
// responsible agency the NEW alerts relevant to its duty for a tenant + module.

export interface AgencySubscription {
  id: string;
  agency_name: string;
  recipient_email: string;
  tenant_id: string;
  module: string;
  severity_threshold: string;
  is_active: boolean;
  last_notified_at: string | null;
  created_at: string;
}

export interface NewAgencySubscription {
  agency_name: string;
  recipient_email: string;
  tenant_id: string;
  module: string;
  severity_threshold: string;
}

export interface AgencySendResult {
  subscription_id: string;
  agency: string;
  tenant_id: string;
  module: string;
  new_alerts: number;
  emailed: boolean;
}

export function useAgencySubscriptions(): UseQueryResult<AgencySubscription[], ApiException> {
  return useQuery<AgencySubscription[], ApiException>({
    queryKey: ['agency-subscriptions'],
    staleTime: 15 * 1000,
    queryFn: async ({ signal }) => {
      const env: SuccessEnvelope<{ subscriptions: AgencySubscription[] }> =
        await apiFetch<{ subscriptions: AgencySubscription[] }>(
          '/admin/agency-alerts/subscriptions', { signal });
      return env.data.subscriptions;
    },
  });
}

export function useCreateAgencySubscription(): UseMutationResult<
  AgencySubscription, ApiException, NewAgencySubscription
> {
  const qc = useQueryClient();
  return useMutation<AgencySubscription, ApiException, NewAgencySubscription>({
    mutationFn: async (body) => {
      const env: SuccessEnvelope<AgencySubscription> =
        await apiFetch<AgencySubscription>(
          '/admin/agency-alerts/subscriptions', { method: 'POST', body });
      return env.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agency-subscriptions'] }),
  });
}

export function useDeleteAgencySubscription(): UseMutationResult<void, ApiException, string> {
  const qc = useQueryClient();
  return useMutation<void, ApiException, string>({
    mutationFn: async (id) => {
      await apiFetch(`/admin/agency-alerts/subscriptions/${id}`, { method: 'DELETE' });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agency-subscriptions'] }),
  });
}

export function useSendAgencyDigests(): UseMutationResult<
  AgencySendResult[], ApiException, { force: boolean }
> {
  const qc = useQueryClient();
  return useMutation<AgencySendResult[], ApiException, { force: boolean }>({
    mutationFn: async ({ force }) => {
      const env: SuccessEnvelope<{ results: AgencySendResult[] }> =
        await apiFetch<{ results: AgencySendResult[] }>(
          `/admin/agency-alerts/send?force=${force}`, { method: 'POST' });
      return env.data.results;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agency-subscriptions'] }),
  });
}
