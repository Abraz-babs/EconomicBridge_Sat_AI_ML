'use client';

import { useMemo } from 'react';

import { useTenant } from '@/context/TenantContext';
import {
  useSkillsBridge,
  type ConnectivityBand,
  type SkillsIndicatorRow,
} from '@/hooks/useSkillsBridge';

import SkillsMap from './SkillsMap';


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

function bandClass(b: ConnectivityBand): string {
  return `sb-band sb-band--${b}`;
}

function bandLabel(b: ConnectivityBand): string {
  switch (b) {
    case 'no_signal': return 'no signal';
    case 'limited':   return 'limited';
    case 'basic':     return 'basic';
    case 'broadband': return 'broadband';
  }
}


export default function SkillsBridgePanel() {
  const { activeTenantId, activeTenant, pilotTenants, setActiveTenant } = useTenant();
  const query = useSkillsBridge({ tenantId: activeTenantId });
  const stats = query.data;

  const stateLabel = STATE_NAMES[activeTenantId] ?? activeTenant.name;
  const isSeedOnly = stats?.sources.length === 1 && stats.sources[0] === 'seed_v1';

  // Sort LGAs by learning gap (worst first) — that's the row the
  // education ministry wants to see at the top.
  const sortedByGap = useMemo<SkillsIndicatorRow[]>(
    () => [...(stats?.indicators ?? [])].sort(
      (a, b) => b.learning_gap_index - a.learning_gap_index,
    ),
    [stats?.indicators],
  );

  return (
    <div>
      {/* HEADER */}
      <div className="cg-header">
        <div>
          <div className="cg-title">SkillsBridge</div>
          <div className="cg-subtitle">
            Per-LGA education access + connectivity gap index ·
            Digital learning infrastructure prioritisation · UNICEF GIGA / ITU
          </div>
        </div>
        <div className={`cg-mode-badge ${isSeedOnly ? 'cg-mode-untuned' : 'cg-mode-trained'}`}>
          {query.isLoading
            ? 'LOADING'
            : query.isError
            ? 'API UNREACHABLE'
            : `LIVE · ${stats?.sources.join(' + ') ?? '—'}`}
        </div>
      </div>

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
          onClick={() => query.refetch()}
          disabled={query.isFetching}
        >
          {query.isFetching ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {query.isError && (
        <div className="fp-alert-error">
          Could not load skills indicators:{' '}
          {query.error?.message ?? 'unknown'}. Run{' '}
          <code>python -m scripts.seed_skills_indicators</code> from{' '}
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
          <div className="fp-stat-label">Median Internet Coverage</div>
          <div className="fp-stat-val">
            {stats ? `${stats.median_internet_coverage_pct.toFixed(0)}%` : '—'}
          </div>
          <div className="fp-stat-sub">% of population with reliable connectivity</div>
        </div>
        <div className="fp-stat ok">
          <div className="fp-stat-label">Schools Mapped</div>
          <div className="fp-stat-val">
            {stats ? fmtPop(stats.total_schools) : '—'}
          </div>
          <div className="fp-stat-sub">
            {stats ? `serving ${fmtPop(stats.total_youth_population)} youth` : 'primary + secondary'}
          </div>
        </div>
        <div className="fp-stat crit">
          <div className="fp-stat-label">Largest Learning Gap</div>
          <div className="fp-stat-val sb-stat-val--small">
            {stats?.worst_gap_lga ?? '—'}
          </div>
          <div className="fp-stat-sub">Prioritise for infrastructure investment</div>
        </div>
      </div>

      {/* MAP */}
      <div className="fp-map">
        <div className="fp-map-header">
          <span className="fp-map-title">
            Connectivity Geography — {stateLabel}
          </span>
          <span className="ev-map-meta">
            Best: {stats?.best_connectivity_lga ?? '—'} · Most underserved:{' '}
            {stats?.most_underserved_lga ?? '—'} · Sources:{' '}
            {stats?.sources.join(', ') ?? '—'}
          </span>
        </div>
        <SkillsMap
          tenant={activeTenant}
          indicators={stats?.indicators ?? []}
        />
      </div>

      {/* COMPARE TABLE */}
      <div className="sb-table-wrap">
        <div className="cg-section-header">
          Per-LGA learning gap
          <span className="ev-map-meta">worst first · click columns to read</span>
        </div>
        {query.isLoading && (
          <div className="fp-alert-empty">Loading indicators…</div>
        )}
        {stats && stats.indicators.length === 0 && (
          <div className="fp-alert-empty">
            No skills data recorded for {stateLabel}. Run{' '}
            <code>python -m scripts.seed_skills_indicators</code> to populate.
          </div>
        )}
        {sortedByGap.length > 0 && (
          <div className="sb-table-scroll">
            <table className="sb-table">
              <thead>
                <tr>
                  <th>LGA</th>
                  <th>Internet</th>
                  <th>Mobile</th>
                  <th>Connectivity</th>
                  <th>Schools / 10k</th>
                  <th>Schools</th>
                  <th>Electricity</th>
                  <th>Gap</th>
                </tr>
              </thead>
              <tbody>
                {sortedByGap.map((row) => (
                  <tr key={row.id}>
                    <td className="sb-lga-cell">{row.lga}</td>
                    <td>{row.internet_coverage_pct.toFixed(1)}%</td>
                    <td>{row.mobile_coverage_pct.toFixed(1)}%</td>
                    <td>
                      <span className={bandClass(row.connectivity_band)}>
                        {bandLabel(row.connectivity_band)}
                      </span>
                    </td>
                    <td>{row.school_density_per_10k.toFixed(2)}</td>
                    <td>{row.school_count}</td>
                    <td>
                      <ScoreBar score={row.electricity_reliability} />
                    </td>
                    <td>
                      <ScoreBar score={row.learning_gap_index} invert />
                    </td>
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
          <div className="fp-timeline-header">Investment signals — {stateLabel}</div>
          <div className="fp-timeline-body">
            {stats?.worst_gap_lga && (
              <div className="fp-tl-row">
                <div className="fp-tl-dot fp-tl-crit">!</div>
                <div className="fp-tl-content">
                  <div className="fp-tl-time">
                    {stats.worst_gap_lga} · highest learning gap
                  </div>
                  <div className="fp-tl-event">
                    Highest combined deficit across internet, schools, and grid
                    reliability. Top priority for digital-learning rollout.
                  </div>
                </div>
              </div>
            )}
            {stats?.most_underserved_lga && (
              <div className="fp-tl-row">
                <div className="fp-tl-dot fp-tl-warn">●</div>
                <div className="fp-tl-content">
                  <div className="fp-tl-time">
                    {stats.most_underserved_lga} · fewest schools per 10k
                  </div>
                  <div className="fp-tl-event">
                    School density below the GIGA benchmark. Consider mobile
                    learning units or satellite-classroom partnerships.
                  </div>
                </div>
              </div>
            )}
            {stats?.best_connectivity_lga && (
              <div className="fp-tl-row">
                <div className="fp-tl-dot fp-tl-ok">●</div>
                <div className="fp-tl-content">
                  <div className="fp-tl-time">
                    {stats.best_connectivity_lga} · strongest connectivity
                  </div>
                  <div className="fp-tl-event">
                    Use as a regional hub for digital-content distribution and
                    teacher-training broadcasts to surrounding LGAs.
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
                <div className="fp-tl-time">Connectivity bands</div>
                <div className="fp-tl-event">
                  Derived from internet coverage %: ≥ 60% broadband, 30-60%
                  basic, 10-30% limited, &lt; 10% no signal. Mobile (2G+)
                  coverage tracked separately for SMS-fallback planning.
                </div>
              </div>
            </div>
            <div className="fp-tl-row">
              <div className="fp-tl-dot fp-tl-ok">●</div>
              <div className="fp-tl-content">
                <div className="fp-tl-time">Learning gap composite</div>
                <div className="fp-tl-event">
                  0..1 score: 40% weight internet coverage, 30% school density,
                  30% grid reliability. Higher = bigger gap. Anchored to UNICEF
                  GIGA benchmarks of ~4 primary + ~1.5 secondary schools / 10k.
                </div>
              </div>
            </div>
            <div className="fp-tl-row">
              <div className="fp-tl-dot fp-tl-ok">●</div>
              <div className="fp-tl-content">
                <div className="fp-tl-time">Live data swap-in</div>
                <div className="fp-tl-event">
                  Today rows are tagged source=seed_v1. UNICEF GIGA + ITU
                  ingestion will write source=giga_v1 / itu_v1 alongside,
                  no migration needed.
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}


function ScoreBar({ score, invert }: { score: number; invert?: boolean }) {
  const pct = Math.max(0, Math.min(100, Math.round(score * 100)));
  // For invert (learning_gap_index), HIGH = bad → red. Otherwise high = good → green.
  const effective = invert ? 1 - score : score;
  const band = effective >= 0.7 ? 'high' : effective >= 0.4 ? 'mid' : 'low';
  return (
    <div className="sb-scorebar" aria-label={`${pct}%`}>
      {/* Width is data-driven (0..100% from `score`). */}
      <div
        className={`sb-scorebar-fill sb-scorebar-fill--${band}`}
        style={{ width: `${pct}%` }}
      />
      <span className="sb-scorebar-label">{pct}</span>
    </div>
  );
}
