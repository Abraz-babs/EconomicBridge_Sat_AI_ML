'use client';

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';

export interface AccountSummary {
  user_id: string;
  email: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
  org_name: string | null;
  org_slug: string | null;
  last_login_at: string | null;
  last_seen: string | null;
  requests: number;
  active_days: number;
  logins: number;
  modules: string[];
  tenants: string[];
}

export interface AccountActivity {
  window_days: number;
  accounts: AccountSummary[];
}

export interface DailyPoint { day: string; requests: number }
export interface NamedCount { name: string; requests: number }
export interface LoginEvent {
  at: string;
  ip_address: string | null;
  user_agent: string | null;
}

export interface AccountDetail {
  window_days: number;
  daily: DailyPoint[];
  by_module: NamedCount[];
  by_tenant: NamedCount[];
  logins: LoginEvent[];
}

/** Every account's usage over the trailing window. Super-admin only (403 otherwise). */
export function useAccountActivity(
  days: number,
): UseQueryResult<AccountActivity, ApiException> {
  return useQuery<AccountActivity, ApiException>({
    queryKey: ['account-activity', days],
    // Counters flush server-side every 30s, so anything shorter re-fetches
    // numbers that cannot have changed.
    staleTime: 30 * 1000,
    queryFn: async ({ signal }) => {
      const env: SuccessEnvelope<AccountActivity> =
        await apiFetch<AccountActivity>(`/admin/activity?days=${days}`, { signal });
      return env.data;
    },
  });
}

/** One account's daily series, module/tenant split and recent sign-ins. */
export function useAccountDetail(
  userId: string | null,
  days: number,
): UseQueryResult<AccountDetail, ApiException> {
  return useQuery<AccountDetail, ApiException>({
    queryKey: ['account-detail', userId, days],
    enabled: Boolean(userId),
    staleTime: 30 * 1000,
    queryFn: async ({ signal }) => {
      const env: SuccessEnvelope<AccountDetail> =
        await apiFetch<AccountDetail>(`/admin/activity/${userId}?days=${days}`, { signal });
      return env.data;
    },
  });
}
