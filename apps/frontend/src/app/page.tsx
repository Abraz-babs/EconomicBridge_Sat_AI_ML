'use client';

import { useState } from 'react';
import { RoleProvider, useRole } from '@/context/RoleContext';
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
import AdminPanel from '@/components/admin/AdminPanel';
import ModuleStub from '@/components/stubs/ModuleStub';

function DashboardContent() {
  const [activeTab, setActiveTab] = useState<TabId>('overview');
  const { currentRole } = useRole();

  return (
    <>
      <a href="#main-content" className="skip-link">Skip to main content</a>
      <RoleSwitcher />
      <Header />
      <Navigation activeTab={activeTab} onTabChange={setActiveTab} />
      <PermissionBanner />

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

        {/* ADMIN PANEL */}
        {activeTab === 'admin' && currentRole === 'admin' && (
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
            <ModuleStub
              num="06"
              title="Economic Mobility Compass"
              description="Regional cost-of-living and income comparison for resettlement agencies and displaced households. Integrates NBS API and ECOWAS STAT data for cross-border economic analysis."
              dataSources={['NBS API', 'ECOWAS STAT', 'World Bank', 'IOM DTM']}
              quarter="Q2 2026"
              quarterLabel="Coming September 2026"
              capabilities={[
                'Regional cost-of-living index with real-time updates',
                'Income opportunity mapping per LGA and state',
                'Resettlement suitability scoring for displaced populations',
                'Cross-border economic comparison across ECOWAS nations',
              ]}
            />
          </div>
        )}

        {/* MODULE 07 — SKILLSBRIDGE */}
        {activeTab === 'skillsbridge' && (
          <div className="tab-content" key="skillsbridge">
            <ModuleStub
              num="07"
              title="SkillsBridge"
              description="Remote education access mapping for areas with geographical barriers. Satellite-verified connectivity mapping to guide digital learning infrastructure deployment."
              dataSources={['Connectivity Mapping', 'Satellite Imagery', 'UNICEF GIGA', 'ITU Data']}
              quarter="Q3 2026"
              quarterLabel="Coming December 2026"
              capabilities={[
                'Satellite-verified internet connectivity mapping',
                'Educational facility accessibility analysis',
                'Digital learning infrastructure gap identification',
                'Partnership with UNICEF GIGA connectivity initiative',
              ]}
            />
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
