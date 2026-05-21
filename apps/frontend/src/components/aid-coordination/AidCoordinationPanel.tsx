'use client';

import { useMemo } from 'react';

import { useTenant } from '@/context/TenantContext';
import { coordinationStatsFor } from '@/data/aidCoordinationSeed';
import AidCoverageMap from './AidCoverageMap';


function fmtNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return n.toLocaleString();
}

function fmtPct(n: number): string {
  return `${n.toFixed(0)}%`;
}


export default function AidCoordinationPanel() {
  const { activeTenantId, activeTenant, pilotTenants, setActiveTenant } = useTenant();
  const stats = useMemo(
    () => coordinationStatsFor(activeTenantId, activeTenant.centroid),
    [activeTenantId, activeTenant.centroid],
  );

  return (
    <div>
      {/* HEADER */}
      <div className="cg-header">
        <div>
          <div className="cg-title">Aid Coordination Bridge</div>
          <div className="cg-subtitle">
            Multi-tenant operational layer · WFP SCOPE + UNHCR proGres + NEMA integration ·
            duplication detection + gap analysis
          </div>
        </div>
        <div className="cg-mode-badge cg-mode-untuned">DEV · seed data</div>
      </div>

      {/* TENANT SELECTOR */}
      <div className="fp-tenant-bar">
        <label htmlFor="ac-tenant-select" className="fp-tenant-label">Viewing tenant</label>
        <select
          id="ac-tenant-select"
          className="fp-tenant-select"
          value={activeTenantId}
          onChange={(e) => setActiveTenant(e.target.value)}
        >
          {pilotTenants.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
      </div>

      {/* STATS */}
      <div className="fp-grid">
        <div className="fp-stat ok">
          <div className="fp-stat-label">Active Agencies</div>
          <div className="fp-stat-val">{stats.active_agencies}</div>
          <div className="fp-stat-sub">Operating in {stats.state_label}</div>
        </div>
        <div className="fp-stat warn">
          <div className="fp-stat-label">LGA Coverage</div>
          <div className="fp-stat-val">{fmtPct(stats.coverage_pct)}</div>
          <div className="fp-stat-sub">
            {stats.covered_lgas} / {stats.total_lgas} LGAs reached by any agency
          </div>
        </div>
        <div className="fp-stat warn">
          <div className="fp-stat-label">Duplication Risk</div>
          <div className="fp-stat-val">{fmtPct(stats.duplication_pct)}</div>
          <div className="fp-stat-sub">LGAs with 2+ agencies in same sector</div>
        </div>
        <div className="fp-stat crit">
          <div className="fp-stat-label">Coverage Gaps</div>
          <div className="fp-stat-val">{stats.gap_lgas.length}</div>
          <div className="fp-stat-sub">LGAs with zero agency presence</div>
        </div>
      </div>

      {/* MAP — agency coverage geography */}
      <div className="fp-map ac-map-wrap">
        <div className="fp-map-header">
          <span className="fp-map-title">
            Agency Geography — {stats.state_label}
          </span>
          <span className="ev-map-meta">
            {stats.gap_lgas.length} gap LGAs ·
            Sources: WFP SCOPE · UNHCR proGres · NEMA · State SEMA
          </span>
        </div>
        <AidCoverageMap tenant={activeTenant} lgaPoints={stats.lga_points} />
      </div>

      {/* COVERAGE MATRIX */}
      <div className="ac-matrix-wrap">
        <div className="cg-section-header">Agency × LGA coverage matrix</div>
        <div className="ac-matrix-scroll">
          <table className="ac-matrix">
            <thead>
              <tr>
                <th className="ac-agency-head">Agency</th>
                {stats.lga_columns.map((lga) => (
                  <th key={lga} className="ac-lga-head">{lga}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {stats.matrix.map((m) => (
                <tr key={m.agency_id}>
                  <td className="ac-agency-cell">
                    <div className="ac-agency-name">{m.agency_name}</div>
                    <div className="ac-agency-sub">
                      {stats.agencies.find(a => a.agency_id === m.agency_id)?.sector}
                    </div>
                  </td>
                  {m.row.map((v, idx) => (
                    <td
                      key={idx}
                      className={`ac-cell ${v === 1 ? 'ac-cell--on' : 'ac-cell--off'}`}
                      title={v === 1 ? 'Active in this LGA' : 'No presence'}
                    >
                      {v === 1 ? '●' : '·'}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* GAP ANALYSIS + AGENCY LIST */}
      <div className="fp-main-row fp-main-row--equal">
        <div className="fp-timeline">
          <div className="fp-timeline-header">Coverage Gaps — {stats.state_label}</div>
          <div className="fp-timeline-body">
            {stats.gap_lgas.length === 0 ? (
              <div className="fp-alert-empty">
                Every LGA in {stats.state_label} has at least one agency present.
              </div>
            ) : (
              stats.gap_lgas.map((lga) => (
                <div key={lga} className="fp-tl-row">
                  <div className="fp-tl-dot fp-tl-crit">!</div>
                  <div className="fp-tl-content">
                    <div className="fp-tl-time">{lga} · 0 agencies</div>
                    <div className="fp-tl-event">No active aid presence</div>
                    <div className="fp-tl-detail">
                      Likely uncoordinated need — refer to NEMA + state SEMA for follow-up.
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="fp-timeline">
          <div className="fp-timeline-header">Agencies in {stats.state_label}</div>
          <div className="fp-timeline-body">
            {stats.agencies.map((a) => (
              <div key={a.agency_id} className="fp-tl-row">
                <div className="fp-tl-dot fp-tl-ok">●</div>
                <div className="fp-tl-content">
                  <div className="fp-tl-time">{a.agency_name}</div>
                  <div className="fp-tl-event">
                    {a.sector} · {a.lgas_covered.length} LGAs · ~{fmtNum(a.beneficiaries_served)} beneficiaries
                  </div>
                  <div className="fp-tl-detail">
                    Covers: {a.lgas_covered.join(', ')}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
