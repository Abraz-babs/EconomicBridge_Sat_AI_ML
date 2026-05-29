'use client';

import { useMemo } from 'react';

import { useTenant } from '@/context/TenantContext';
import { sourceBadge } from '@/lib/display';
import {
  formatIncome,
  useEconomicMobility,
  type CompareBand,
  type MobilityIndicatorRow,
} from '@/hooks/useEconomicMobility';

import MobilityMap from './MobilityMap';


const STATE_NAMES: Record<string, string> = {
  kebbi: 'Kebbi State', benue: 'Benue State', plateau: 'Plateau State',
  kaduna: 'Kaduna State', niger: 'Niger State', zamfara: 'Zamfara State',
  nasarawa: 'Nasarawa State', fct: 'Federal Capital Territory',
  ghana: 'Ghana', senegal: 'Senegal',
};


function fmtPop(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return n.toLocaleString();
}

function bandClass(b: CompareBand): string {
  return `mc-band mc-band--${b}`;
}


export default function MobilityCompassPanel() {
  const { activeTenantId, activeTenant, pilotTenants, setActiveTenant } = useTenant();
  const query = useEconomicMobility({ tenantId: activeTenantId });
  const stats = query.data;

  const stateLabel = STATE_NAMES[activeTenantId] ?? activeTenant.name;
  const badge = sourceBadge(stats?.sources, { loading: query.isLoading, error: query.isError });

  // Sort LGAs from cheapest to most expensive for the table render.
  const sortedByCol = useMemo<MobilityIndicatorRow[]>(
    () => [...(stats?.indicators ?? [])].sort(
      (a, b) => a.cost_of_living_index - b.cost_of_living_index,
    ),
    [stats?.indicators],
  );

  return (
    <div>
      {/* HEADER */}
      <div className="cg-header">
        <div>
          <div className="cg-title">Economic Mobility Compass</div>
          <div className="cg-subtitle">
            Per-LGA cost-of-living + income opportunity index ·
            Resettlement suitability for displaced households · World Bank Indicators
          </div>
        </div>
        <div className={`cg-mode-badge ${badge.cls}`}>{badge.label}</div>
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
          Could not load mobility indicators:{' '}
          {query.error?.message ?? 'unknown'}. Run{' '}
          <code>python -m scripts.seed_mobility_indicators</code> from{' '}
          <code>apps/api/</code> to populate seed rows.
        </div>
      )}

      {/* STATS */}
      <div className="fp-grid">
        <div className="fp-stat ok">
          <div className="fp-stat-label">LGAs Mapped</div>
          <div className="fp-stat-val">{stats?.total_lgas ?? '—'}</div>
          <div className="fp-stat-sub">in {stateLabel}</div>
        </div>
        <div className="fp-stat warn">
          <div className="fp-stat-label">Median Cost of Living</div>
          <div className="fp-stat-val">
            {stats ? stats.median_cost_of_living.toFixed(0) : '—'}
          </div>
          <div className="fp-stat-sub">100 = national average</div>
        </div>
        <div className="fp-stat ok">
          <div className="fp-stat-label">Median Household Income</div>
          <div className="fp-stat-val">
            {stats
              ? formatIncome(stats.median_household_income_ngn, stats.median_household_income_usd)
              : '—'}
          </div>
          <div className="fp-stat-sub">
            {stats?.median_household_income_ngn != null ? 'NGN (USD) per month' : 'USD per month'}
          </div>
        </div>
        <div className="fp-stat crit">
          <div className="fp-stat-label">Best for Resettlement</div>
          <div className="fp-stat-val mc-stat-val--small">
            {stats?.best_capacity_lga ?? '—'}
          </div>
          <div className="fp-stat-sub">Highest displacement capacity</div>
        </div>
      </div>

      {/* MAP */}
      <div className="fp-map">
        <div className="fp-map-header">
          <span className="fp-map-title">
            Cost-of-Living Geography — {stateLabel}
          </span>
          <span className="ev-map-meta">
            Cheapest: {stats?.cheapest_lga ?? '—'} · Most expensive:{' '}
            {stats?.most_expensive_lga ?? '—'} · Sources:{' '}
            {stats?.sources.join(', ') ?? '—'}
          </span>
        </div>
        <MobilityMap
          tenant={activeTenant}
          indicators={stats?.indicators ?? []}
        />
      </div>

      {/* COMPARE TABLE */}
      <div className="mc-table-wrap">
        <div className="cg-section-header">
          Per-LGA comparison
          <span className="ev-map-meta">cheapest first · click columns to read</span>
        </div>
        {query.isLoading && (
          <div className="fp-alert-empty">Loading indicators…</div>
        )}
        {stats && stats.indicators.length === 0 && (
          <div className="fp-alert-empty">
            No mobility data recorded for {stateLabel}. Run{' '}
            <code>python -m scripts.seed_mobility_indicators</code> to populate.
          </div>
        )}
        {sortedByCol.length > 0 && (
          <div className="mc-table-scroll">
            <table className="mc-table">
              <thead>
                <tr>
                  <th>LGA</th>
                  <th>COL idx</th>
                  <th>Band</th>
                  <th>Avg income/mo</th>
                  <th>Opportunity</th>
                  <th>Capacity</th>
                  <th>Population</th>
                </tr>
              </thead>
              <tbody>
                {sortedByCol.map((row) => (
                  <tr key={row.id}>
                    <td className="mc-lga-cell">{row.lga}</td>
                    <td>{row.cost_of_living_index.toFixed(1)}</td>
                    <td>
                      <span className={bandClass(row.cost_of_living_band)}>
                        {row.cost_of_living_band.replace('_', ' ')}
                      </span>
                    </td>
                    <td>{formatIncome(row.avg_household_income_ngn, row.avg_household_income_usd)}</td>
                    <td>
                      <ScoreBar score={row.income_opportunity_score} />
                    </td>
                    <td>
                      <ScoreBar score={row.displacement_capacity_index} />
                    </td>
                    <td>{fmtPop(row.population)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* HIGHLIGHTS */}
      <div className="fp-main-row fp-main-row--equal">
        <div className="fp-timeline">
          <div className="fp-timeline-header">Resettlement signals — {stateLabel}</div>
          <div className="fp-timeline-body">
            {stats?.best_capacity_lga && (
              <div className="fp-tl-row">
                <div className="fp-tl-dot fp-tl-ok">●</div>
                <div className="fp-tl-content">
                  <div className="fp-tl-time">
                    {stats.best_capacity_lga} · highest capacity
                  </div>
                  <div className="fp-tl-event">
                    Recommended primary destination for incoming displaced households.
                  </div>
                  <div className="fp-tl-detail">
                    Pair with the cheapest-LGA option ({stats.cheapest_lga}) for cost
                    relief when capacity LGA is also a premium-COL area.
                  </div>
                </div>
              </div>
            )}
            {stats?.best_opportunity_lga && (
              <div className="fp-tl-row">
                <div className="fp-tl-dot fp-tl-ok">●</div>
                <div className="fp-tl-content">
                  <div className="fp-tl-time">
                    {stats.best_opportunity_lga} · best income opportunity
                  </div>
                  <div className="fp-tl-event">
                    Highest formal + informal employment score in the tenant.
                  </div>
                  <div className="fp-tl-detail">
                    Surface this to working-age adults during resettlement intake.
                  </div>
                </div>
              </div>
            )}
            {stats?.most_expensive_lga && (
              <div className="fp-tl-row">
                <div className="fp-tl-dot fp-tl-crit">!</div>
                <div className="fp-tl-content">
                  <div className="fp-tl-time">
                    {stats.most_expensive_lga} · highest COL
                  </div>
                  <div className="fp-tl-event">
                    Households with limited cash buffers should avoid here unless
                    income opportunity matches.
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="fp-timeline">
          <div className="fp-timeline-header">Methodology</div>
          <div className="fp-timeline-body">
            <div className="fp-tl-row">
              <div className="fp-tl-dot fp-tl-ok">●</div>
              <div className="fp-tl-content">
                <div className="fp-tl-time">Cost-of-living index</div>
                <div className="fp-tl-event">
                  100 = national average. Anchors calibrated against NBS Selected
                  Food + Non-Food Items 2024 baseline; per-LGA spread covers
                  downtown vs outskirts variation.
                </div>
              </div>
            </div>
            <div className="fp-tl-row">
              <div className="fp-tl-dot fp-tl-ok">●</div>
              <div className="fp-tl-content">
                <div className="fp-tl-time">Opportunity + capacity scores</div>
                <div className="fp-tl-event">
                  0..1 composites: opportunity tracks formal + informal employment
                  per capita; capacity reflects housing + services slack.
                </div>
              </div>
            </div>
            <div className="fp-tl-row">
              <div className="fp-tl-dot fp-tl-ok">●</div>
              <div className="fp-tl-content">
                <div className="fp-tl-time">Live data swap-in</div>
                <div className="fp-tl-event">
                  Today rows are tagged source=seed_v1. NBS API + ECOWAS STAT
                  ingestion will write source=nbs_col_v1 / ecowas_stat_v1
                  alongside, no migration needed.
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}


function ScoreBar({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(100, Math.round(score * 100)));
  // Map 0..1 to a band the CSS can colour: low / mid / high.
  const band = score >= 0.7 ? 'high' : score >= 0.4 ? 'mid' : 'low';
  return (
    <div className="mc-scorebar" aria-label={`${pct}%`}>
      {/* Width is data-driven (0..100% from `score`) — no CSS class
         alternative without enumerating 101 classes. */}
      <div
        className={`mc-scorebar-fill mc-scorebar-fill--${band}`}
        style={{ width: `${pct}%` }}
      />
      <span className="mc-scorebar-label">{pct}</span>
    </div>
  );
}
