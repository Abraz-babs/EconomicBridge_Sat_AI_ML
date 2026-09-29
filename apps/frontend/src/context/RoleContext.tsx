'use client';

/**
 * The real access profile of whoever is looking at the dashboard.
 *
 * Until 2026-09-29 this held a "View as" persona picked from a demo list of
 * real organisations' names. Now it is derived — nothing to switch: the
 * signed-in account (useAuth), its organisation's name from the public tenant
 * registry, and the super-admin's real "view as account" simulation
 * (useViewAs). See data/roles.ts for the three kinds.
 */

import { createContext, useContext, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';

import { useAuth } from '@/context/AuthContext';
import { accentColors, accessProfile, type AccessProfile } from '@/data/roles';
import { useViewAs } from '@/hooks/useViewAs';
import { apiFetch, type SuccessEnvelope } from '@/lib/api';

interface RoleContextValue {
  roleConfig: AccessProfile;
  accentColor: string;
}

const RoleContext = createContext<RoleContextValue | undefined>(undefined);

interface RegistryNames {
  tenants: { id: string; name: string }[];
}

function useOrgNames(enabled: boolean): Record<string, string> {
  const { data } = useQuery<RegistryNames>({
    queryKey: ['tenant-registry-names'],
    enabled,
    staleTime: 10 * 60_000,
    retry: 0,
    queryFn: async ({ signal }) => {
      const env: SuccessEnvelope<RegistryNames> = await apiFetch<RegistryNames>('/public-tenants', { signal });
      return env.data;
    },
  });
  return Object.fromEntries((data?.tenants ?? []).map((t) => [t.id, t.name]));
}

export function RoleProvider({ children }: { children: ReactNode }) {
  const { user, isSuperAdmin } = useAuth();
  const viewAs = useViewAs();
  const simulating = isSuperAdmin ? viewAs : null;
  const names = useOrgNames(Boolean(user));

  let roleConfig: AccessProfile;
  if (!user) {
    roleConfig = accessProfile('visitor', null);
  } else if (simulating) {
    roleConfig = accessProfile('partner', simulating.label, { simulating: true });
  } else if (isSuperAdmin) {
    roleConfig = accessProfile('operator', (user.tenant_id && names[user.tenant_id]) || 'Bizra Farms · EconomicBridge');
  } else {
    roleConfig = accessProfile('partner', (user.tenant_id && names[user.tenant_id]) || user.full_name || null);
  }

  return (
    <RoleContext.Provider value={{ roleConfig, accentColor: accentColors[roleConfig.kind] }}>
      {children}
    </RoleContext.Provider>
  );
}

export function useRole() {
  const ctx = useContext(RoleContext);
  if (!ctx) throw new Error('useRole must be used within RoleProvider');
  return ctx;
}
