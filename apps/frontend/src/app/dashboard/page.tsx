'use client';

import { useCallback, useEffect, useState } from 'react';
import { RoleProvider } from '@/context/RoleContext';
import { useAuth } from '@/context/AuthContext';
import { useTenant, PILOT_TENANT_IDS } from '@/context/TenantContext';
import { useMyModules } from '@/hooks/useTenantModules';
import EmptyRegion from '@/components/common/EmptyRegion';
import NotSubscribed from '@/components/common/NotSubscribed';
import SubscribeModal from '@/components/common/SubscribeModal';
import ErrorBoundary from '@/components/ErrorBoundary';
import RoleSwitcher from '@/components/RoleSwitcher';
import Header from '@/components/Header';
import Navigation, { TabId } from '@/components/Navigation';
import PermissionBanner from '@/components/PermissionBanner';
import SystemStatus from '@/components/SystemStatus';
import Footer from '@/components/Footer';
import AlertBar from '@/components/AlertBar';
import StatsRow from '@/components/StatsRow';
import ProvenancePanel from '@/components/ProvenancePanel';
import SatelliteMap from '@/components/SatelliteMap';
import IntelligenceFeed from '@/components/IntelligenceFeed';
import DataAccessMatrix from '@/components/DataAccessMatrix';
import CoverageTrend from '@/components/CoverageTrend';
import CropHealthIndex from '@/components/CropHealthIndex';
import ActiveResponse from '@/components/ActiveResponse';
import FarmlandPanel from '@/components/farmland/FarmlandPanel';
import CropGuardPanel from '@/components/cropguard/CropGuardPanel';
import EconomicVisibilityPanel from '@/components/economic-visibility/EconomicVisibilityPanel';
import AidCoordinationPanel from '@/components/aid-coordination/AidCoordinationPanel';
import ShockGuardPanel from '@/components/shockguard/ShockGuardPanel';
import MobilityCompassPanel from '@/components/mobility/MobilityCompassPanel';
import SkillsBridgePanel from '@/components/skills/SkillsBridgePanel';
import AdminPanel from '@/components/admin/AdminPanel';
import ReportsPanel from '@/components/reports/ReportsPanel';
import RegisterPrompt from '@/components/auth/RegisterPrompt';

const TAB_IDS: TabId[] = [
  'overview', 'economic-visibility', 'aid-coordination', 'farmland',
  'cropguard', 'shockguard', 'mobility-compass', 'skillsbridge', 'reports', 'admin',
];
const TAB_STORAGE_KEY = 'eb.activeTab';

// Human labels for the "registration required" prompt.
const TAB_LABELS: Record<TabId, string> = {
  'overview': 'Overview',
  'economic-visibility': 'Poverty Mapping',
  'aid-coordination': 'Aid Coordination Bridge',
  'farmland': 'Farmland Protection',
  'cropguard': 'CropGuard',
  'shockguard': 'ShockGuard',
  'mobility-compass': 'Mobility Compass',
  'skillsbridge': 'SkillsBridge',
  'reports': 'Reports',
  'admin': 'Admin Panel',
};

// The 7 paid modules — subscription-gated + tenant-data-bearing.
const MODULE_TABS: ReadonlySet<TabId> = new Set<TabId>([
  'economic-visibility', 'aid-coordination', 'farmland', 'cropguard',
  'shockguard', 'mobility-compass', 'skillsbridge',
]);
const isModuleTab = (tab: TabId): boolean => MODULE_TABS.has(tab);

function isTab(v: string | null): v is TabId {
  return !!v && (TAB_IDS as string[]).includes(v);
}

// Overview is open-access; every other tab (modules + reports) needs an account
// (admin is gated separately by super-admin role). Anonymous → register prompt.
function isGatedModule(tab: TabId): boolean {
  return tab !== 'overview' && tab !== 'admin';
}

/** The deep-linked / persisted tab, read on the CLIENT only (after mount).
 *  Returns 'overview' on the server so SSR + first client render match. */
function readPersistedTab(): TabId {
  if (typeof window === 'undefined') return 'overview';
  const fromUrl = new URLSearchParams(window.location.search).get('tab');
  if (isTab(fromUrl)) return fromUrl;
  const stored = window.localStorage.getItem(TAB_STORAGE_KEY);
  return isTab(stored) ? stored : 'overview';
}

function DashboardContent() {
  // Start on 'overview' (the SSR default) so hydration matches; the persisted /
  // deep-linked tab is restored after mount in the effect below.
  const [activeTab, setActiveTab] = useState<TabId>('overview');
  const { user, loading, isSuperAdmin } = useAuth();
  const { activeTenant, activeTenantId } = useTenant();
  // Entitlements follow the USER'S OWN subscription via /auth/my-modules
  // (JWT-keyed; same query the nav uses — React Query dedupes). Not the
  // viewed tenant, and not the X-Tenant-Id path (permitted_tenants 403s
  // partner accounts asking about their own non-pilot org). undefined while
  // loading → fail-open. Super-admins are never gated.
  const { data: enabledModules } = useMyModules(Boolean(user) && !isSuperAdmin);
  const subscribed =
    isSuperAdmin ||
    !isModuleTab(activeTab) || enabledModules === undefined || enabledModules.includes(activeTab);
  // Tenant exists but its plan doesn't include this module → clean "not
  // subscribed" state instead of letting the panel hit a 403. (Reports isn't a
  // paid module, so it's never "not subscribed".)
  const showNotSubscribed = isModuleTab(activeTab) && !subscribed;
  // "No data yet" banner for a registered region with no seeded/ingested data.
  // The signal is pilot membership, NOT tenant.active (that's a map ACTIVE/
  // PLANNED display flag — Ghana & Senegal are pilots with data but active:false).
  const showEmptyRegion =
    isModuleTab(activeTab) && subscribed && !PILOT_TENANT_IDS.includes(activeTenantId);
  // A module tab renders only when the tenant is subscribed to it.
  const showModule = (tab: TabId) => activeTab === tab && subscribed;
  // Which module an anonymous visitor just tried to open (drives the prompt).
  const [gatedModule, setGatedModule] = useState<TabId | null>(null);
  // Which padlocked (unsubscribed) module a signed-in tenant just clicked —
  // drives the corporate subscribe prompt; the tab itself never switches.
  const [lockedModule, setLockedModule] = useState<TabId | null>(null);

  const handleTabChange = useCallback((tab: TabId) => {
    // Gate modules for anonymous visitors — overview stays open.
    if (!user && isGatedModule(tab)) {
      setGatedModule(tab);
      return;
    }
    setActiveTab(tab);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(TAB_STORAGE_KEY, tab);
      // pushState so the back/forward buttons navigate between modules.
      window.history.pushState({ tab }, '', `${window.location.pathname}?tab=${tab}`);
    }
  }, [user]);

  // Deep-link / restored-tab guard: once auth resolves, an anonymous visitor
  // landing on a gated module (?tab=farmland or a stored tab) is bounced to
  // overview and shown the prompt. This is a genuine sync-with-external-state
  // effect (auth resolves async; it also rewrites URL history), so the
  // set-state-in-effect lint rule is intentionally disabled here.
  useEffect(() => {
    if (loading || user || !isGatedModule(activeTab)) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setGatedModule(activeTab);
    setActiveTab('overview');
    if (typeof window !== 'undefined') {
      window.history.replaceState({ tab: 'overview' }, '', `${window.location.pathname}?tab=overview`);
    }
  }, [loading, user, activeTab]);

  // On mount (client only): restore the deep-linked / persisted tab — done here
  // rather than in useState so SSR + first client render both start on
  // 'overview' (no hydration mismatch). Also keep activeTab in sync with
  // browser back/forward.
  useEffect(() => {
    const initial = readPersistedTab();
    if (initial !== 'overview') {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setActiveTab(initial);
    }
    window.history.replaceState(
      { tab: initial }, '', `${window.location.pathname}?tab=${initial}`,
    );
    const onPop = () => {
      const t = new URLSearchParams(window.location.search).get('tab');
      setActiveTab(isTab(t) ? t : 'overview');
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  return (
    <>
      <a href="#main-content" className="skip-link">Skip to main content</a>
      <RoleSwitcher />
      <Header />
      <Navigation
        activeTab={activeTab}
        onTabChange={handleTabChange}
        lockModules={!user}
        onLockedModule={(id) => setLockedModule(id)}
      />
      <PermissionBanner />

      {gatedModule && (
        <RegisterPrompt
          moduleLabel={TAB_LABELS[gatedModule]}
          onClose={() => setGatedModule(null)}
        />
      )}

      {lockedModule && (
        <SubscribeModal
          moduleLabel={TAB_LABELS[lockedModule]}
          tenantName={activeTenant.name}
          onClose={() => setLockedModule(null)}
        />
      )}

      <main id="main-content" role="main">
        {/* Tenant not entitled to this module — clean state instead of a 403. */}
        {showNotSubscribed && (
          <div className="tab-content" key="not-subscribed">
            <NotSubscribed
              tenant={activeTenant}
              moduleLabel={TAB_LABELS[activeTab]}
              isSuperAdmin={isSuperAdmin}
            />
          </div>
        )}

        {/* Newly-registered region with no live data yet — set the context
            for the empty maps/stats below (shown across all module tabs). */}
        {showEmptyRegion && (
          <div className="tab-content" key="empty-region">
            <EmptyRegion tenant={activeTenant} />
          </div>
        )}

        {/* OVERVIEW TAB */}
        {activeTab === 'overview' && (
          <div className="tab-content" key="overview">
            <ErrorBoundary fallbackModule="Alert System">
              <AlertBar />
            </ErrorBoundary>
            <ErrorBoundary fallbackModule="Statistics">
              <StatsRow />
            </ErrorBoundary>
            <div className="two-col anim a3">
              <ErrorBoundary fallbackModule="Satellite Intelligence Map">
                <SatelliteMap />
              </ErrorBoundary>
              <div className="sidebar">
                <ErrorBoundary fallbackModule="Intelligence Feed">
                  <IntelligenceFeed />
                </ErrorBoundary>
                <ErrorBoundary fallbackModule="Data Access Matrix">
                  <DataAccessMatrix />
                </ErrorBoundary>
              </div>
            </div>
            <div className="bottom-row anim a4">
              <ErrorBoundary fallbackModule="Coverage Trend">
                <CoverageTrend />
              </ErrorBoundary>
              <ErrorBoundary fallbackModule="Crop Health Index">
                <CropHealthIndex />
              </ErrorBoundary>
              <ErrorBoundary fallbackModule="Active Response">
                <ActiveResponse />
              </ErrorBoundary>
            </div>
            <ErrorBoundary fallbackModule="Data Sources & Provenance">
              <ProvenancePanel />
            </ErrorBoundary>
          </div>
        )}

        {/* MODULE 03 — FARMLAND PROTECTION */}
        {showModule('farmland') && (
          <div className="tab-content" key="farmland">
            <ErrorBoundary fallbackModule="Farmland Protection">
              <FarmlandPanel />
            </ErrorBoundary>
          </div>
        )}

        {/* ADMIN PANEL — gated by real super-admin auth, not the demo role */}
        {activeTab === 'admin' && isSuperAdmin && (
          <div className="tab-content" key="admin">
            <ErrorBoundary fallbackModule="Admin Panel">
              <AdminPanel />
            </ErrorBoundary>
          </div>
        )}

        {/* MODULE 01 — POVERTY MAPPING (ECONOMIC VISIBILITY) */}
        {showModule('economic-visibility') && (
          <div className="tab-content" key="econ-vis">
            <ErrorBoundary fallbackModule="Economic Visibility">
              <EconomicVisibilityPanel />
            </ErrorBoundary>
          </div>
        )}

        {/* MODULE 02 — AID COORDINATION BRIDGE */}
        {showModule('aid-coordination') && (
          <div className="tab-content" key="aid-coord">
            <ErrorBoundary fallbackModule="Aid Coordination Bridge">
              <AidCoordinationPanel />
            </ErrorBoundary>
          </div>
        )}

        {/* MODULE 04 — AGRICULTURE (CROPGUARD) */}
        {showModule('cropguard') && (
          <div className="tab-content" key="cropguard">
            <ErrorBoundary fallbackModule="CropGuard">
              <CropGuardPanel />
            </ErrorBoundary>
          </div>
        )}

        {/* MODULE 05 — DISASTER RELIEF (SHOCKGUARD) */}
        {showModule('shockguard') && (
          <div className="tab-content" key="shockguard">
            <ErrorBoundary fallbackModule="ShockGuard">
              <ShockGuardPanel />
            </ErrorBoundary>
          </div>
        )}

        {/* MODULE 06 — ECONOMIC MOBILITY COMPASS */}
        {showModule('mobility-compass') && (
          <div className="tab-content" key="mobility">
            <ErrorBoundary fallbackModule="Economic Mobility Compass">
              <MobilityCompassPanel />
            </ErrorBoundary>
          </div>
        )}

        {/* MODULE 07 — SKILLSBRIDGE */}
        {showModule('skillsbridge') && (
          <div className="tab-content" key="skillsbridge">
            <ErrorBoundary fallbackModule="SkillsBridge">
              <SkillsBridgePanel />
            </ErrorBoundary>
          </div>
        )}

        {/* REPORTS — historical summary + CSV/PDF export (signed-in only) */}
        {activeTab === 'reports' && user && (
          <div className="tab-content" key="reports">
            <ErrorBoundary fallbackModule="Reports">
              <ReportsPanel />
            </ErrorBoundary>
          </div>
        )}
      </main>

      <SystemStatus />
      <Footer />
    </>
  );
}

export default function DashboardPage() {
  return (
    <RoleProvider>
      <ErrorBoundary fallbackModule="Dashboard">
        <DashboardContent />
      </ErrorBoundary>
    </RoleProvider>
  );
}
