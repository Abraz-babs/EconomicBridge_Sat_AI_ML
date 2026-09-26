'use client';

/**
 * Mobility Compass — honest interim view (2026-09-26).
 *
 * The per-LGA cost-of-living, income, opportunity, capacity and population
 * figures were withdrawn: they were spread from one state-level anchor with
 * deterministic per-LGA noise (ingestion/sources/worldbank.py
 * compose_mobility_indicators), not measured for each LGA — so "best for
 * resettlement" named an LGA by noise. Until the module is rebuilt on measured
 * data (IOM DTM displacement by LGA, night-light activity trend, published
 * prices), it shows only what holds at state level, labelled as an estimate.
 * MobilityMap stays in the repo for the rebuild.
 */

import { useTenant } from '@/context/TenantContext';
import { localCurrencyFor } from '@/lib/currency';
import { formatIncome, useEconomicMobility } from '@/hooks/useEconomicMobility';
import ModuleSources from '@/components/common/ModuleSources';


const STATE_NAMES: Record<string, string> = {
  kebbi: 'Kebbi State', benue: 'Benue State', plateau: 'Plateau State',
  kaduna: 'Kaduna State', niger: 'Niger State', zamfara: 'Zamfara State',
  nasarawa: 'Nasarawa State', fct: 'Federal Capital Territory',
  ghana: 'Ghana', senegal: 'Senegal',
};


export default function MobilityCompassPanel() {
  const { activeTenantId, activeTenant, pilotTenants, setActiveTenant } = useTenant();
  const query = useEconomicMobility({ tenantId: activeTenantId });
  const stats = query.data;

  const stateLabel = STATE_NAMES[activeTenantId] ?? activeTenant.name;
  const currency = localCurrencyFor(activeTenant.country);

  return (
    <div>
      {/* HEADER */}
      <div className="cg-header">
        <div>
          <div className="cg-title">Economic Mobility Compass</div>
          <div className="cg-subtitle">
            Livelihoods and displacement · being rebuilt on measured data, LGA by LGA
          </div>
          <ModuleSources sources={[
            { name: 'World Bank', role: 'national income' },
            { name: 'NBS living-standards survey', role: 'scaled to the state' },
          ]} />
        </div>
        <div className="cg-mode-badge cg-mode-untuned">ESTIMATE · state level</div>
      </div>

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
          onClick={() => query.refetch()}
          disabled={query.isFetching}
        >
          {query.isFetching ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {query.isError && (
        <div className="fp-alert-error">
          Could not load the income estimate: {query.error?.message ?? 'unknown'}.
        </div>
      )}

      {/* STATS — only what holds at state level */}
      <div className="fp-grid">
        <div className="fp-stat ok">
          <div className="fp-stat-label">LGAs</div>
          <div className="fp-stat-val">{stats?.total_lgas ?? '—'}</div>
          <div className="fp-stat-sub">in {stateLabel}</div>
        </div>
        <div className="fp-stat ok">
          <div className="fp-stat-label">Household income (estimate)</div>
          <div className="fp-stat-val">
            {stats ? formatIncome(stats.median_household_income_usd, activeTenant.country) : '—'}
          </div>
          <div className="fp-stat-sub">
            {currency ? `${currency.code} (USD) per month` : 'USD per month'} · state
            level · World Bank income scaled to the NBS living-standards survey
          </div>
        </div>
      </div>

      {/* WHAT THIS MODULE IS BECOMING */}
      <div className="fp-main-row fp-main-row--equal">
        <div className="fp-timeline">
          <div className="fp-timeline-header">What this module is becoming</div>
          <div className="fp-timeline-body">
            <div className="fp-tl-row">
              <div className="fp-tl-dot fp-tl-ok">●</div>
              <div className="fp-tl-content">
                <div className="fp-tl-time">Displacement, by LGA</div>
                <div className="fp-tl-event">
                  People displaced, from the International Organization for
                  Migration&rsquo;s tracking rounds — published by LGA for six of
                  our eight states — set against each LGA&rsquo;s measured
                  population to show where host communities are under pressure.
                </div>
              </div>
            </div>
            <div className="fp-tl-row">
              <div className="fp-tl-dot fp-tl-ok">●</div>
              <div className="fp-tl-content">
                <div className="fp-tl-time">Economic activity from night light</div>
                <div className="fp-tl-event">
                  Whether each LGA&rsquo;s towns are growing or fading, from NASA
                  night-light records since 2012.
                </div>
              </div>
            </div>
            <div className="fp-tl-row">
              <div className="fp-tl-dot fp-tl-ok">●</div>
              <div className="fp-tl-content">
                <div className="fp-tl-time">Prices and access</div>
                <div className="fp-tl-event">
                  Food prices where a public source publishes them, and travel
                  time from each village to the nearest town and market.
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="fp-timeline">
          <div className="fp-timeline-header">Why the LGA scores were withdrawn</div>
          <div className="fp-timeline-body">
            <div className="fp-tl-row">
              <div className="fp-tl-dot fp-tl-warn">●</div>
              <div className="fp-tl-content">
                <div className="fp-tl-time">Spread, not measured</div>
                <div className="fp-tl-event">
                  The earlier cost-of-living, income, opportunity and
                  resettlement scores for each LGA were spread from a single
                  state figure rather than measured for each LGA. A ranking of
                  LGAs — or a place to resettle families — cannot rest on that,
                  so they are not shown until each LGA has its own measurement.
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
