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

export function RoleProvider({ children }: { children: ReactNode }) {
  const [currentRole, setCurrentRole] = useState<RoleId>('ngo');

  const switchRole = useCallback((role: RoleId) => {
    setCurrentRole(role);
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
