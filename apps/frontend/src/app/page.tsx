'use client';

import { useCallback, useEffect, useState } from 'react';
import { RoleProvider } from '@/context/RoleContext';
import { useAuth } from '@/context/AuthContext';
import ErrorBoundary from '@/components/ErrorBoundary';
import RoleSwitcher from '@/components/RoleSwitcher';
import Header from '@/components/Header';
import Navigation, { TabId } from '@/components/Navigation';
import PermissionBanner from '@/components/PermissionBanner';
import SystemStatus from '@/components/SystemStatus';
import Footer from '@/components/Footer';
import AlertBar from '@/components/AlertBar';
import StatsRow from '@/components/StatsRow';
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
import RegisterPrompt from '@/components/auth/RegisterPrompt';

const TAB_IDS: TabId[] = [
  'overview', 'economic-visibility', 'aid-coordination', 'farmland',
  'cropguard', 'shockguard', 'mobility-compass', 'skillsbridge', 'admin',
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
  'admin': 'Admin Panel',
};

function isTab(v: string | null): v is TabId {
  return !!v && (TAB_IDS as string[]).includes(v);
}

// Overview is open-access; every other tab needs an account (admin is gated
// separately by super-admin role). Anonymous visitors get a register prompt.
function isGatedModule(tab: TabId): boolean {
  return tab !== 'overview' && tab !== 'admin';
}

/** Initial tab: URL `?tab=` (shareable/deep-link) → localStorage → overview. */
function readInitialTab(): TabId {
  if (typeof window === 'undefined') return 'overview';
  const fromUrl = new URLSearchParams(window.location.search).get('tab');
  if (isTab(fromUrl)) return fromUrl;
  const stored = window.localStorage.getItem(TAB_STORAGE_KEY);
  return isTab(stored) ? stored : 'overview';
}

function DashboardContent() {
  // Persisted across refreshes AND reflected in the URL (?tab=) so module
  // views are shareable/deep-linkable. Mirrors how the active tenant persists.
  const [activeTab, setActiveTab] = useState<TabId>(readInitialTab);
  const { user, loading, isSuperAdmin } = useAuth();
  // Which module an anonymous visitor just tried to open (drives the prompt).
  const [gatedModule, setGatedModule] = useState<TabId | null>(null);

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

  // On mount: reflect the restored tab in the URL (shareable) without adding a
  // history entry, and keep activeTab in sync with browser back/forward.
  useEffect(() => {
    const cur = new URLSearchParams(window.location.search).get('tab');
    if (cur !== activeTab) {
      window.history.replaceState(
        { tab: activeTab }, '', `${window.location.pathname}?tab=${activeTab}`,
      );
    }
    const onPop = () => {
      const t = new URLSearchParams(window.location.search).get('tab');
      setActiveTab(isTab(t) ? t : 'overview');
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <a href="#main-content" className="skip-link">Skip to main content</a>
      <RoleSwitcher />
      <Header />
      <Navigation activeTab={activeTab} onTabChange={handleTabChange} lockModules={!user} />
      <PermissionBanner />

      {gatedModule && (
        <RegisterPrompt
          moduleLabel={TAB_LABELS[gatedModule]}
          onClose={() => setGatedModule(null)}
        />
      )}

      <main id="main-content" role="main">
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
          </div>
        )}

        {/* MODULE 03 — FARMLAND PROTECTION */}
        {activeTab === 'farmland' && (
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
        {activeTab === 'economic-visibility' && (
          <div className="tab-content" key="econ-vis">
            <ErrorBoundary fallbackModule="Economic Visibility">
              <EconomicVisibilityPanel />
            </ErrorBoundary>
          </div>
        )}

        {/* MODULE 02 — AID COORDINATION BRIDGE */}
        {activeTab === 'aid-coordination' && (
          <div className="tab-content" key="aid-coord">
            <ErrorBoundary fallbackModule="Aid Coordination Bridge">
              <AidCoordinationPanel />
            </ErrorBoundary>
          </div>
        )}

        {/* MODULE 04 — AGRICULTURE (CROPGUARD) */}
        {activeTab === 'cropguard' && (
          <div className="tab-content" key="cropguard">
            <ErrorBoundary fallbackModule="CropGuard">
              <CropGuardPanel />
            </ErrorBoundary>
          </div>
        )}

        {/* MODULE 05 — DISASTER RELIEF (SHOCKGUARD) */}
        {activeTab === 'shockguard' && (
          <div className="tab-content" key="shockguard">
            <ErrorBoundary fallbackModule="ShockGuard">
              <ShockGuardPanel />
            </ErrorBoundary>
          </div>
        )}

        {/* MODULE 06 — ECONOMIC MOBILITY COMPASS */}
        {activeTab === 'mobility-compass' && (
          <div className="tab-content" key="mobility">
            <ErrorBoundary fallbackModule="Economic Mobility Compass">
              <MobilityCompassPanel />
            </ErrorBoundary>
          </div>
        )}

        {/* MODULE 07 — SKILLSBRIDGE */}
        {activeTab === 'skillsbridge' && (
          <div className="tab-content" key="skillsbridge">
            <ErrorBoundary fallbackModule="SkillsBridge">
              <SkillsBridgePanel />
            </ErrorBoundary>
          </div>
        )}
      </main>

      <SystemStatus />
      <Footer />
    </>
  );
}

export default function Home() {
  return (
    <RoleProvider>
      <ErrorBoundary fallbackModule="Dashboard">
        <DashboardContent />
      </ErrorBoundary>
    </RoleProvider>
  );
}
