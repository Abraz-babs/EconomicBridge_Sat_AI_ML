'use client';

/**
 * SkillsBridge — the school reach list (built 2026-09-27 from the
 * operator-approved mock): every GRID3 school, whether any village within
 * 2 km shows light at night, and the people living there.
 *
 * It replaces the interim view of UNICEF GIGA school counts per LGA. Those
 * assigned each school to the nearest LGA centre within ~50 km, so border
 * LGAs were inflated (Augie 329 against GRID3's 77); the per-LGA internet,
 * electricity and learning-gap scores were withdrawn on 2026-09-26 because
 * they were spread around national figures, not measured. SkillsMap stays in
 * the repo for per-school connectivity once GIGA enables it on our key.
 */

import { useQueryClient } from '@tanstack/react-query';

import { useTenant } from '@/context/TenantContext';
import SchoolReach from './SchoolReach';


const STATE_NAMES: Record<string, string> = {
  kebbi: 'Kebbi State', benue: 'Benue State', plateau: 'Plateau State',
  kaduna: 'Kaduna State', niger: 'Niger State', zamfara: 'Zamfara State',
  nasarawa: 'Nasarawa State', fct: 'Federal Capital Territory',
  ghana: 'Ghana', senegal: 'Senegal',
};


export default function SkillsBridgePanel() {
  const { activeTenantId, activeTenant, pilotTenants, setActiveTenant } = useTenant();
  const queryClient = useQueryClient();
  const stateLabel = STATE_NAMES[activeTenantId] ?? activeTenant.name;

  return (
    <div>
      {/* TENANT SELECTOR */}
      <div className="fp-tenant-bar">
        <label htmlFor="sb-tenant-select" className="fp-tenant-label">
          Viewing tenant
        </label>
        <select
          id="sb-tenant-select"
          className="fp-tenant-select"
          value={activeTenantId}
          onChange={(e) => setActiveTenant(e.target.value)}
        >
          {pilotTenants.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
        <button
          type="button"
          className="fp-refresh-btn"
          onClick={() => queryClient.invalidateQueries({ queryKey: ['school-reach', activeTenantId] })}
        >
          Refresh
        </button>
      </div>

      <SchoolReach tenant={activeTenant} stateLabel={stateLabel} />
    </div>
  );
}
