'use client';

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { ApiException, apiFetch, type SuccessEnvelope } from '@/lib/api';

export interface ModuleState { key: string; label: string; enabled: boolean }
export interface RegisteredTenant {
  id: string;
  name: string;
  tenant_type: string;
  country: string;
  status: string;
  subscription_tier: string;
  mou_reference: string | null;
  modules: ModuleState[];
}

interface TenantModulesData {
  tenant_id: string;
  enabled: string[];
  catalog: { key: string; label: string }[];
}

/** Active tenant's enabled module keys — drives the dashboard nav. */
export function useTenantModules(tenantId: string): UseQueryResult<string[], ApiException> {
  return useQuery<string[], ApiException>({
    queryKey: ['tenant-modules', tenantId],
    enabled: Boolean(tenantId),
    staleTime: 30 * 1000,
    queryFn: async ({ signal }) => {
      const env: SuccessEnvelope<TenantModulesData> =
        await apiFetch<TenantModulesData>('/tenant-modules', { tenantId, signal });
      return env.data.enabled;
    },
  });
}

// ─── Super-admin: registry + entitlement management ────────────────────────

interface TenantRegistryData {
  tenants: RegisteredTenant[];
  catalog: { key: string; label: string }[];
}

export function useAdminTenants(): UseQueryResult<TenantRegistryData, ApiException> {
  return useQuery<TenantRegistryData, ApiException>({
    queryKey: ['admin-tenants'],
    staleTime: 15 * 1000,
    queryFn: async ({ signal }) => {
      const env: SuccessEnvelope<TenantRegistryData> =
        await apiFetch<TenantRegistryData>('/admin/tenants', { signal });
      return env.data;
    },
  });
}

export function useSetTenantModules(): UseMutationResult<
  RegisteredTenant, ApiException, { tenantId: string; enabledKeys: string[] }
> {
  const qc = useQueryClient();
  return useMutation<RegisteredTenant, ApiException, { tenantId: string; enabledKeys: string[] }>({
    mutationFn: async ({ tenantId, enabledKeys }) => {
      const env: SuccessEnvelope<RegisteredTenant> = await apiFetch<RegisteredTenant>(
        `/admin/tenants/${tenantId}/modules`,
        { method: 'PATCH', body: { enabled_keys: enabledKeys } },
      );
      return env.data;
    },
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: ['admin-tenants'] });
      qc.invalidateQueries({ queryKey: ['tenant-modules', vars.tenantId] });
    },
  });
}

export interface RegisterTenantVars {
  id: string;
  name: string;
  tenant_type: string;
  country: string;
  subscription_tier: string;
  mou_reference: string | null;
  enabled_keys: string[];
}

export function useRegisterTenant(): UseMutationResult<
  RegisteredTenant, ApiException, RegisterTenantVars
> {
  const qc = useQueryClient();
  return useMutation<RegisteredTenant, ApiException, RegisterTenantVars>({
    mutationFn: async (vars) => {
      const env: SuccessEnvelope<RegisteredTenant> =
        await apiFetch<RegisteredTenant>('/admin/tenants', { method: 'POST', body: vars });
      return env.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-tenants'] }),
  });
}
