'use client';

import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useMemo,
  useState,
} from 'react';
import { useQuery } from '@tanstack/react-query';

import { apiFetch, type SuccessEnvelope } from '@/lib/api';
import { TENANTS, type Tenant } from '@/data/tenants';

/**
 * Which tenant is currently being viewed.
 *
 * Open-access model: anonymous visitors can switch between active pilot
 * tenants freely. Defaults to Kebbi (the reference deployment).
 *
 * Distinct from RoleContext — role is a permissions/persona switch, tenant is
 * a data-scope switch. Both are independent demo affordances today; paid-tier
 * accounts will eventually pin these from server-side claims.
 */

const STORAGE_KEY = 'eb_active_tenant';

export const PILOT_TENANT_IDS: readonly string[] = [
  'kebbi',
  'benue',
  'plateau',
  'kaduna',
  'niger',
  'zamfara',
  'nasarawa',
  'fct',
  'ghana',
  'senegal',
] as const;

const DEFAULT_TENANT_ID = 'kebbi';

interface TenantContextValue {
  /** Slug — e.g. "kebbi". */
  activeTenantId: string;
  /** Full Tenant record from the static catalogue. */
  activeTenant: Tenant;
  /** All allowlisted (pilot) tenants, in display order. */
  pilotTenants: Tenant[];
  setActiveTenant: (id: string) => void;
}

const TenantContext = createContext<TenantContextValue | undefined>(undefined);

function readInitial(): string {
  if (typeof window === 'undefined') return DEFAULT_TENANT_ID;
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored && PILOT_TENANT_IDS.includes(stored)) return stored;
  return DEFAULT_TENANT_ID;
}

interface RegistryShape {
  tenants: { id: string; tenant_type: string }[];
  categories: { key: string; geographic: boolean }[];
}

export function TenantProvider({ children }: { children: ReactNode }) {
  const [activeTenantId, setId] = useState<string>(readInitial);

  // Registered tenants from the super-admin registry. Lets newly-provisioned
  // GEOGRAPHIC tenants appear in the selectors. Fail-safe: on error/loading the
  // selector falls back to the hardcoded pilots.
  const { data: registry } = useQuery<RegistryShape>({
    queryKey: ['tenant-registry-select'],
    staleTime: 60_000,
    retry: 0,
    queryFn: async ({ signal }) => {
      const env: SuccessEnvelope<RegistryShape> =
        await apiFetch<RegistryShape>('/admin/tenants', { signal });
      return env.data;
    },
  });

  // Valid selectable tenant ids = pilots ∪ registered GEOGRAPHIC tenants that
  // have static metadata (centroid etc.) in the catalogue. Org tenants (NGO /
  // research / funder) are access entities, not data views — excluded here.
  const validIds = useMemo(() => {
    const ids = new Set<string>(PILOT_TENANT_IDS);
    if (registry) {
      const geo = new Set(registry.categories.filter((c) => c.geographic).map((c) => c.key));
      for (const t of registry.tenants) {
        if (geo.has(t.tenant_type) && TENANTS.some((x) => x.id === t.id)) ids.add(t.id);
      }
    }
    return ids;
  }, [registry]);

  const pilotTenants = useMemo(() => {
    const extras = [...validIds].filter((id) => !PILOT_TENANT_IDS.includes(id)).sort();
    return [...PILOT_TENANT_IDS, ...extras]
      .map((id) => TENANTS.find((t) => t.id === id))
      .filter((t): t is Tenant => Boolean(t));
  }, [validIds]);

  const activeTenant = useMemo(
    () => TENANTS.find((t) => t.id === activeTenantId) ?? pilotTenants[0],
    [activeTenantId, pilotTenants],
  );

  const setActiveTenant = useCallback((id: string) => {
    if (!validIds.has(id)) return;
    setId(id);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STORAGE_KEY, id);
    }
  }, [validIds]);

  const value = useMemo<TenantContextValue>(
    () => ({ activeTenantId, activeTenant, pilotTenants, setActiveTenant }),
    [activeTenantId, activeTenant, pilotTenants, setActiveTenant],
  );

  return <TenantContext.Provider value={value}>{children}</TenantContext.Provider>;
}

export function useTenant(): TenantContextValue {
  const ctx = useContext(TenantContext);
  if (!ctx) throw new Error('useTenant must be used within TenantProvider');
  return ctx;
}
