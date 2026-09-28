'use client';

/**
 * Mobility Compass — every LGA against five measured factors (operator-approved
 * mock v7, built 2026-09-28): activity from NASA night light since 2012, this
 * season's farming, the walk to a health facility, health facilities per
 * person, and food and fuel prices — plus the villages gone dark, newly lit
 * and farthest from care. It grew out of the night-light view (2026-09-27).
 *
 * It replaces the honest interim view of state-level estimates. The earlier
 * per-LGA cost-of-living, income, opportunity and capacity figures were spread
 * from one state anchor with deterministic noise (withdrawn 2026-09-26), and
 * the displacement design built on IOM DTM counts was dropped because those
 * are licensed for non-commercial use only — the page links to IOM instead.
 * MobilityMap stays in the repo, unused.
 */

import { useQueryClient } from '@tanstack/react-query';

import { useTenant } from '@/context/TenantContext';
import Compass from './Compass';


const STATE_NAMES: Record<string, string> = {
  kebbi: 'Kebbi State', benue: 'Benue State', plateau: 'Plateau State',
  kaduna: 'Kaduna State', niger: 'Niger State', zamfara: 'Zamfara State',
  nasarawa: 'Nasarawa State', fct: 'Federal Capital Territory',
  ghana: 'Ghana', senegal: 'Senegal',
};


export default function MobilityCompassPanel() {
  const { activeTenantId, activeTenant, pilotTenants, setActiveTenant } = useTenant();
  const queryClient = useQueryClient();
  const stateLabel = STATE_NAMES[activeTenantId] ?? activeTenant.name;

  return (
    <div>
      {/* TENANT SELECTOR */}
      <div className="fp-tenant-bar">
        <label htmlFor="mc-tenant-select" className="fp-tenant-label">
          Viewing tenant
        </label>
        <select
          id="mc-tenant-select"
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
          onClick={() => {
            queryClient.invalidateQueries({ queryKey: ['light-trend', activeTenantId] });
            queryClient.invalidateQueries({ queryKey: ['mobility-compass', activeTenantId] });
          }}
        >
          Refresh
        </button>
      </div>

      <Compass tenant={activeTenant} stateLabel={stateLabel} />
    </div>
  );
}
