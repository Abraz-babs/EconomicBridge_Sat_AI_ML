'use client';

import { useRole } from '@/context/RoleContext';

export type TabId =
  | 'overview'
  | 'economic-visibility'
  | 'aid-coordination'
  | 'farmland'
  | 'cropguard'
  | 'shockguard'
  | 'mobility-compass'
  | 'skillsbridge'
  | 'admin';

interface NavigationProps {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
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
  { id: 'admin', label: 'Admin Panel', navId: 'navAdmin' },
];

export default function Navigation({ activeTab, onTabChange }: NavigationProps) {
  const { roleConfig } = useRole();

  const isLocked = (navId: string) => roleConfig.navLocked.includes(navId);

  return (
    <nav role="tablist" aria-label="Dashboard modules">
      {tabs.map(({ id, label, navId }) => {
        const locked = isLocked(navId);
        const active = activeTab === id;
        return (
          <button
            key={id}
            id={`tab-${id}`}
            role="tab"
            aria-selected={active}
            aria-disabled={locked}
            aria-controls={`panel-${id}`}
            className={`nav-tab ${active ? 'active' : ''} ${locked ? 'locked' : ''}`}
            onClick={() => {
              if (!locked) onTabChange(id);
            }}
            tabIndex={active ? 0 : -1}
            onKeyDown={(e) => {
              const visibleTabs = tabs.filter((t) => !isLocked(t.navId));
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
          </button>
        );
      })}
    </nav>
  );
}
