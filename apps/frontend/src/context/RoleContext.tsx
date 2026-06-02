'use client';

import { createContext, useContext, useState, ReactNode, useCallback } from 'react';
import { RoleId, RoleConfig, roles, roleColors } from '@/data/roles';

interface RoleContextValue {
  currentRole: RoleId;
  roleConfig: RoleConfig;
  accentColor: string;
  switchRole: (role: RoleId) => void;
}

const RoleContext = createContext<RoleContextValue | undefined>(undefined);

const ROLE_STORAGE_KEY = 'eb.activeRole';

function readInitialRole(): RoleId {
  if (typeof window === 'undefined') return 'ngo';
  const stored = window.localStorage.getItem(ROLE_STORAGE_KEY);
  if (stored && stored in roles) return stored as RoleId;
  return 'ngo';
}

export function RoleProvider({ children }: { children: ReactNode }) {
  const [currentRole, setCurrentRole] = useState<RoleId>(readInitialRole);

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
