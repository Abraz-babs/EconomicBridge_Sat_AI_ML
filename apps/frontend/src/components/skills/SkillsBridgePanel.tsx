'use client';

/**
 * SkillsBridge — honest interim view (2026-09-26).
 *
 * Only the school counts are measured (UNICEF GIGA school locations). The
 * per-LGA internet, mobile, electricity, youth-population and learning-gap
 * figures were withdrawn: they were spread around national figures with
 * deterministic per-LGA noise (ingestion/sources/giga_itu_stats.py), so the
 * "largest learning gap" ranked noise. The rebuild is a school-level reach
 * list: every school, whether its village is dark at night, the children
 * nearby, and its connectivity. SkillsMap stays in the repo for the rebuild.
 */

import { useMemo } from 'react';

import { useTenant } from '@/context/TenantContext';
import { useSkillsBridge, type SkillsIndicatorRow } from '@/hooks/useSkillsBridge';
import ModuleSources from '@/components/common/ModuleSources';


const STATE_NAMES: Record<string, string> = {
  kebbi: 'Kebbi State', benue: 'Benue State', plateau: 'Plateau State',
  kaduna: 'Kaduna State', niger: 'Niger State', zamfara: 'Zamfara State',
  nasarawa: 'Nasarawa State', fct: 'Federal Capital Territory',
  ghana: 'Ghana', senegal: 'Senegal',
};


export default function SkillsBridgePanel() {
  const { activeTenantId, activeTenant, pilotTenants, setActiveTenant } = useTenant();
  const query = useSkillsBridge({ tenantId: activeTenantId });
  const stats = query.data;

  const stateLabel = STATE_NAMES[activeTenantId] ?? activeTenant.name;

  // Most schools first — the one per-LGA figure that is measured.
  const bySchools = useMemo<SkillsIndicatorRow[]>(
    () => [...(stats?.indicators ?? [])].sort((a, b) => b.school_count - a.school_count),
    [stats?.indicators],
  );
  const most = bySchools[0];
  const fewest = bySchools[bySchools.length - 1];
  const maxCount = most?.school_count ?? 0;

  return (
    <div>
      {/* HEADER */}
      <div className="cg-header">
        <div>
          <div className="cg-title">SkillsBridge</div>
          <div className="cg-subtitle">
            Schools mapped by UNICEF GIGA · becoming a school-by-school reach list
            for power and connectivity
          </div>
          <ModuleSources sources={[
            { name: 'UNICEF GIGA', role: 'school locations' },
          ]} />
        </div>
        <div className="cg-mode-badge cg-mode-trained">LIVE · UNICEF GIGA schools</div>
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
          Could not load school counts: {query.error?.message ?? 'unknown'}.
        </div>
      )}

      {/* STATS — measured school counts only */}
      <div className="fp-grid">
        <div className="fp-stat ok">
          <div className="fp-stat-label">Schools mapped</div>
          <div className="fp-stat-val">
            {stats ? stats.total_schools.toLocaleString('en-US') : '—'}
          </div>
          <div className="fp-stat-sub">all levels, mostly primary · {stateLabel}</div>
        </div>
        <div className="fp-stat ok">
          <div className="fp-stat-label">LGAs</div>
          <div className="fp-stat-val">{stats?.total_lgas ?? '—'}</div>
          <div className="fp-stat-sub">with schools counted</div>
        </div>
        <div className="fp-stat ok">
          <div className="fp-stat-label">Most schools</div>
          <div className="fp-stat-val sb-stat-val--small">{most?.lga ?? '—'}</div>
          <div className="fp-stat-sub">{most ? `${most.school_count} schools` : '—'}</div>
        </div>
        <div className="fp-stat warn">
          <div className="fp-stat-label">Fewest schools</div>
          <div className="fp-stat-val sb-stat-val--small">{fewest?.lga ?? '—'}</div>
          <div className="fp-stat-sub">{fewest ? `${fewest.school_count} schools` : '—'}</div>
        </div>
      </div>

      {/* SCHOOLS BY LGA */}
      <div className="sb-table-wrap">
        <div className="cg-section-header">
          Schools by LGA
          <span className="ev-map-meta">
            UNICEF GIGA school locations · each school counted in the nearest LGA
            centre (within ~50 km), so counts near borders are approximate
          </span>
        </div>
        {query.isLoading && <div className="fp-alert-empty">Loading school counts…</div>}
        {stats && bySchools.length === 0 && (
          <div className="fp-alert-empty">No schools recorded for {stateLabel} yet.</div>
        )}
        {bySchools.length > 0 && (
          <div className="sb-table-scroll">
            <table className="sb-table">
              <thead>
                <tr>
                  <th>LGA</th>
                  <th>Schools mapped</th>
                  <th aria-label="Share of the LGA with the most schools" />
                </tr>
              </thead>
              <tbody>
                {bySchools.map((row) => (
                  <tr key={row.id}>
                    <td className="sb-lga-cell">{row.lga}</td>
                    <td>{row.school_count}</td>
                    <td style={{ width: '45%' }}>
                      <div className="sb-scorebar" aria-hidden>
                        <div
                          className="sb-scorebar-fill sb-scorebar-fill--high"
                          style={{ width: `${maxCount ? Math.round((row.school_count / maxCount) * 100) : 0}%` }}
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* WHAT THIS MODULE IS BECOMING */}
      <div className="fp-main-row fp-main-row--equal">
        <div className="fp-timeline">
          <div className="fp-timeline-header">What this module is becoming</div>
          <div className="fp-timeline-body">
            <div className="fp-tl-row">
              <div className="fp-tl-dot fp-tl-ok">●</div>
              <div className="fp-tl-content">
                <div className="fp-tl-time">A school reach list</div>
                <div className="fp-tl-event">
                  Every school, with whether its village shows light at night
                  (NASA VIIRS), how many school-age children live nearby
                  (Meta &amp; CIESIN), and its connectivity — ranked to show the
                  schools to power and connect first, with directions.
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
                  The earlier internet, electricity and learning-gap figures for
                  each LGA were spread around national figures rather than
                  measured for each LGA, so they could not rank LGAs. Only the
                  school counts are shown until each figure is measured.
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
