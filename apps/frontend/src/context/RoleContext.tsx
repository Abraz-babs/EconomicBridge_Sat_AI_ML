'use client';

import { createContext, useContext, useEffect, useState, ReactNode, useCallback } from 'react';
import { RoleId, RoleConfig, roles, roleColors } from '@/data/roles';

interface RoleContextValue {
  currentRole: RoleId;
  roleConfig: RoleConfig;
  accentColor: string;
  switchRole: (role: RoleId) => void;
}

const RoleContext = createContext<RoleContextValue | undefined>(undefined);

const ROLE_STORAGE_KEY = 'eb.activeRole';
const DEFAULT_ROLE: RoleId = 'ngo';

export function RoleProvider({ children }: { children: ReactNode }) {
  // Start from the SSR default so the server and first client render match;
  // restore the persisted role AFTER mount to avoid a hydration mismatch.
  const [currentRole, setCurrentRole] = useState<RoleId>(DEFAULT_ROLE);

  useEffect(() => {
    const stored = window.localStorage.getItem(ROLE_STORAGE_KEY);
    if (stored && stored in roles && stored !== DEFAULT_ROLE) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCurrentRole(stored as RoleId);
    }
  }, []);

  const switchRole = useCallback((role: RoleId) => {
    setCurrentRole(role);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(ROLE_STORAGE_KEY, role);
    }
  }, []);

  const value: RoleContextValue = {
    currentRole,
    roleConfig: roles[currentRole],
    accentColor: roleColors[currentRole],
    switchRole,
  };

  return <RoleContext.Provider value={value}>{children}</RoleContext.Provider>;
}

export function useRole() {
  const ctx = useContext(RoleContext);
  if (!ctx) throw new Error('useRole must be used within RoleProvider');
  return ctx;
}
