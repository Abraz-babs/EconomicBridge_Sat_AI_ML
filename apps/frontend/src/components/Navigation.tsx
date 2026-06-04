'use client';

import { useAuth } from '@/context/AuthContext';
import { useRole } from '@/context/RoleContext';
import { useTenant } from '@/context/TenantContext';
import { useTenantModules } from '@/hooks/useTenantModules';

// Tabs that ARE modules (gated per tenant). overview + admin are always-on.
const MODULE_TAB_IDS = new Set<string>([
  'economic-visibility', 'aid-coordination', 'farmland', 'cropguard',
  'shockguard', 'mobility-compass', 'skillsbridge',
]);

export type TabId =
  | 'overview'
  | 'economic-visibility'
  | 'aid-coordination'
  | 'farmland'
  | 'cropguard'
  | 'shockguard'
  | 'mobility-compass'
  | 'skillsbridge'
  | 'reports'
  | 'admin';

interface NavigationProps {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  /** Anonymous visitor — show a lock on the (gated) module tabs. */
  lockModules?: boolean;
}

const tabs: { id: TabId; label: string; navId: string }[] = [
  { id: 'overview', label: 'Overview', navId: 'navOverview' },
  { id: 'economic-visibility', label: 'Poverty Mapping (Economic Visibility)', navId: 'navEconVis' },
  { id: 'aid-coordination', label: 'Aid Coordination Bridge', navId: 'navAidCoord' },
  { id: 'farmland', label: 'Farmland Protection', navId: 'navFarmland' },
  { id: 'cropguard', label: 'Agriculture (CropGuard)', navId: 'navCropGuard' },
  { id: 'shockguard', label: 'Disaster Relief (ShockGuard)', navId: 'navShockGuard' },
  { id: 'mobility-compass', label: 'Mobility Compass', navId: 'navMobility' },
  { id: 'skillsbridge', label: 'SkillsBridge', navId: 'navSkills' },
  { id: 'reports', label: 'Reports', navId: 'navReports' },
  { id: 'admin', label: 'Admin Panel', navId: 'navAdmin' },
];

export default function Navigation({ activeTab, onTabChange, lockModules = false }: NavigationProps) {
  const { roleConfig } = useRole();
  const { isSuperAdmin, user } = useAuth();
  const { activeTenantId } = useTenant();
  const { data: enabledModules } = useTenantModules(activeTenantId);

  const isLocked = (navId: string) => roleConfig.navLocked.includes(navId);

  // A module tab shows only if the active tenant is entitled to it. While
  // entitlements load (undefined), show all (fail-open UI). overview is never
  // module-gated; the admin tab is gated by REAL super-admin auth (not the demo
  // role) so a tenant can never reach the admin panel.
  const entitled = (id: TabId) =>
    !MODULE_TAB_IDS.has(id) || enabledModules === undefined || enabledModules.includes(id);

  // The tabs actually shown: admin only for super-admin; Reports for any
  // signed-in account (it's login-gated, not subscription-gated); everything
  // else role-allowed AND tenant-entitled.
  const shownTabs = tabs.filter((t) =>
    t.id === 'admin' ? isSuperAdmin
      : t.id === 'reports' ? Boolean(user)
      : !isLocked(t.navId) && entitled(t.id),
  );

  return (
    <nav role="tablist" aria-label="Dashboard modules">
      {shownTabs.map(({ id, label }) => {
        const active = activeTab === id;
        const locked = lockModules && MODULE_TAB_IDS.has(id);
        return (
          <button
            key={id}
            id={`tab-${id}`}
            role="tab"
            type="button"
            aria-selected={active ? 'true' : 'false'}
            aria-controls={`panel-${id}`}
            className={`nav-tab ${active ? 'active' : ''}${locked ? ' nav-tab--locked' : ''}`}
            title={locked ? 'Sign in or register to open this module' : undefined}
            onClick={() => onTabChange(id)}
            tabIndex={active ? 0 : -1}
            onKeyDown={(e) => {
              const visibleTabs = shownTabs;
              const currentIdx = visibleTabs.findIndex((t) => t.id === id);
              if (e.key === 'ArrowRight' && currentIdx < visibleTabs.length - 1) {
                e.preventDefault();
                const next = visibleTabs[currentIdx + 1];
                onTabChange(next.id);
                document.getElementById(`tab-${next.id}`)?.focus();
              } else if (e.key === 'ArrowLeft' && currentIdx > 0) {
                e.preventDefault();
                const prev = visibleTabs[currentIdx - 1];
                onTabChange(prev.id);
                document.getElementById(`tab-${prev.id}`)?.focus();
              } else if (e.key === 'Home') {
                e.preventDefault();
                const first = visibleTabs[0];
                onTabChange(first.id);
                document.getElementById(`tab-${first.id}`)?.focus();
              } else if (e.key === 'End') {
                e.preventDefault();
                const last = visibleTabs[visibleTabs.length - 1];
                onTabChange(last.id);
                document.getElementById(`tab-${last.id}`)?.focus();
              }
            }}
          >
            {label}
            {locked && <span className="nav-lock" aria-hidden="true">🔒</span>}
          </button>
        );
      })}
    </nav>
  );
}
