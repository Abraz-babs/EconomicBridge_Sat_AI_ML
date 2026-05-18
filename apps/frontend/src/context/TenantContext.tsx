'use client';

import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useMemo,
  useState,
} from 'react';

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

export function TenantProvider({ children }: { children: ReactNode }) {
  const [activeTenantId, setId] = useState<string>(readInitial);

  const pilotTenants = useMemo(
    () =>
      PILOT_TENANT_IDS
        .map((id) => TENANTS.find((t) => t.id === id))
        .filter((t): t is Tenant => Boolean(t)),
    [],
  );

  const activeTenant = useMemo(
    () => TENANTS.find((t) => t.id === activeTenantId) ?? pilotTenants[0],
    [activeTenantId, pilotTenants],
  );

  const setActiveTenant = useCallback((id: string) => {
    if (!PILOT_TENANT_IDS.includes(id)) return;
    setId(id);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STORAGE_KEY, id);
    }
  }, []);

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
