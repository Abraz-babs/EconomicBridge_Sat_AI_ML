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
  /** Signed-in user clicked a module OUTSIDE their tenant's subscription.
   *  The tab stays visible (padlocked) — the shop window stays full — and
   *  the click opens the subscribe prompt instead of the module. */
  onLockedModule?: (id: TabId, label: string) => void;
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

export default function Navigation({
  activeTab, onTabChange, lockModules = false, onLockedModule,
}: NavigationProps) {
  const { roleConfig } = useRole();
  const { isSuperAdmin, user } = useAuth();
  const { activeTenantId } = useTenant();
  // The subscription that locks follow is the USER'S OWN organisation's
  // (user.tenant_id — its registry slug), NOT whichever tenant is currently
  // being VIEWED (2026-07-17 fix: a Bizra admin viewing CARE International
  // was gated by CARE's plan, so their own disallowed modules stayed open).
  // Fallback to the viewed tenant only for legacy accounts without a slug.
  const subscriptionTenantId =
    !isSuperAdmin && user?.tenant_id ? user.tenant_id : activeTenantId;
  const { data: enabledModules } = useTenantModules(subscriptionTenantId);

  const isLocked = (navId: string) => roleConfig.navLocked.includes(navId);

  // Subscription policy (2026-07-16): unsubscribed modules are NEVER hidden —
  // every module stays visible so a tenant always sees the full catalogue;
  // the unsubscribed ones are padlocked and clicking opens the subscribe
  // prompt instead of the module. (Hiding also had a fail-open flicker while
  // entitlements loaded.) The API's 403 middleware stays the real enforcement.
  // Super-admins are never padlocked — they administer plans, not buy them.
  const notEntitled = (id: TabId) =>
    !isSuperAdmin &&
    MODULE_TAB_IDS.has(id) &&
    enabledModules !== undefined &&
    !enabledModules.includes(id);

  // The tabs actually shown: admin only for super-admin; Reports for any
  // signed-in account (it's login-gated, not subscription-gated); everything
  // else role-allowed. Module tabs always show regardless of entitlement.
  const shownTabs = tabs.filter((t) =>
    t.id === 'admin' ? isSuperAdmin
      : t.id === 'reports' ? Boolean(user)
      : !isLocked(t.navId),
  );

  return (
    <nav role="tablist" aria-label="Dashboard modules">
      {shownTabs.map(({ id, label }) => {
        const active = activeTab === id;
        const anonLocked = lockModules && MODULE_TAB_IDS.has(id);
        // Signed-in but the module isn't in the active tenant's plan.
        const subLocked = Boolean(user) && notEntitled(id);
        const locked = anonLocked || subLocked;
        return (
          <button
            key={id}
            id={`tab-${id}`}
            role="tab"
            type="button"
            aria-selected={active}
            className={`nav-tab ${active ? 'active' : ''}${locked ? ' nav-tab--locked' : ''}`}
            title={
              subLocked
                ? 'Not part of your current subscription — click for details'
                : anonLocked
                  ? 'Sign in or register to open this module'
                  : undefined
            }
            onClick={() =>
              subLocked ? onLockedModule?.(id, label) : onTabChange(id)
            }
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
