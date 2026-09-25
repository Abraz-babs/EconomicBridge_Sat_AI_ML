'use client';

import { useTenant } from '@/context/TenantContext';
import { sourceBadge } from '@/lib/display';
import { useAidCoordination } from '@/hooks/useAidCoordination';

import AidCoverageMap from './AidCoverageMap';


const STATE_NAMES: Record<string, string> = {
  kebbi: 'Kebbi State', benue: 'Benue State', plateau: 'Plateau State',
  kaduna: 'Kaduna State', niger: 'Niger State', zamfara: 'Zamfara State',
  nasarawa: 'Nasarawa State', fct: 'Federal Capital Territory',
  ghana: 'Ghana', senegal: 'Senegal',
};


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
  const query = useAidCoordination({ tenantId: activeTenantId });
  const stats = query.data;

  const stateLabel = STATE_NAMES[activeTenantId] ?? activeTenant.name;
  const badge = sourceBadge(stats?.sources, { loading: query.isLoading, error: query.isError });

  return (
    <div>
      {/* HEADER */}
      <div className="cg-header">
        <div>
          <div className="cg-title">Aid Coordination Bridge</div>
          <div className="cg-subtitle">
            Who reports aid activity where · coverage gaps + same-sector overlap ·
            published by the organisations themselves (IATI)
          </div>
        </div>
        <div className={`cg-mode-badge ${badge.cls}`}>{badge.label}</div>
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
          Could not load coverage: {query.error?.message ?? 'unknown'}.
        </div>
      )}

      {/* STATS */}
      <div className="fp-grid">
        <div className="fp-stat ok">
          <div className="fp-stat-label">Organisations</div>
          <div className="fp-stat-val">{stats?.active_agencies ?? '—'}</div>
          <div className="fp-stat-sub">Reporting current activity in {stateLabel}</div>
        </div>
        <div className="fp-stat warn">
          <div className="fp-stat-label">LGA Coverage</div>
          <div className="fp-stat-val">{stats ? fmtPct(stats.coverage_pct) : '—'}</div>
          <div className="fp-stat-sub">
            {stats ? `${stats.covered_lgas} / ${stats.total_lgas} LGAs with a reported site` : '—'}
          </div>
        </div>
        <div className="fp-stat warn">
          <div className="fp-stat-label">Duplication Risk</div>
          <div className="fp-stat-val">{stats ? fmtPct(stats.duplication_pct) : '—'}</div>
          <div className="fp-stat-sub">LGAs where 2+ organisations work in the same sector</div>
        </div>
        <div className="fp-stat crit">
          <div className="fp-stat-label">Coverage Gaps</div>
          <div className="fp-stat-val">{stats?.gap_lgas.length ?? '—'}</div>
          <div className="fp-stat-sub">LGAs with no reported activity site</div>
        </div>
      </div>

      {/* MAP */}
      <div className="fp-map ac-map-wrap">
        <div className="fp-map-header">
          <span className="fp-map-title">Agency Geography — {stateLabel}</span>
          <span className="ev-map-meta">
            {stats?.gap_lgas.length ?? 0} gap LGAs ·
            Sources: {stats?.sources.join(', ') ?? '—'}
          </span>
        </div>
        <AidCoverageMap tenant={activeTenant} lgaPoints={stats?.lga_points ?? []} sources={stats?.sources ?? []} />
      </div>

      {/* COVERAGE MATRIX */}
      <div className="ac-matrix-wrap">
        <div className="cg-section-header">Organisation × LGA — where each reports activity</div>
        {query.isLoading && (
          <div className="fp-alert-empty">Loading matrix…</div>
        )}
        {stats && stats.matrix.length === 0 && (
          <div className="fp-alert-empty">
            No current aid activity has been reported to IATI for {stateLabel}.
          </div>
        )}
        {stats && stats.matrix.length > 0 && (
          <div className="ac-matrix-scroll">
            <table className="ac-matrix">
              <thead>
                <tr>
                  <th className="ac-agency-head">Organisation</th>
                  {stats.lga_columns.map((lga) => (
                    <th key={lga} className="ac-lga-head">{lga}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {stats.matrix.map((m) => {
                  const sector = stats.agencies.find(
                    (a) => a.agency_slug === m.agency_slug,
                  )?.sector;
                  return (
                    <tr key={m.agency_slug}>
                      <td className="ac-agency-cell">
                        <div className="ac-agency-name">{m.agency_name}</div>
                        <div className="ac-agency-sub">{sector}</div>
                      </td>
                      {m.row.map((v, idx) => (
                        <td
                          key={idx}
                          className={`ac-cell ${v === 1 ? 'ac-cell--on' : 'ac-cell--off'}`}
                          title={
                            v !== 1 ? 'None reported'
                              : stats.lga_columns[idx] === stats.statewide_label
                                ? `${stats.statewide_label} activity — no specific site published`
                                : 'Reports activity here'
                          }
                        >
                          {v === 1 ? '●' : '·'}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* GAPS + AGENCY DIRECTORY */}
      <div className="fp-main-row fp-main-row--equal">
        <div className="fp-timeline">
          <div className="fp-timeline-header">Coverage Gaps — {stateLabel}</div>
          <div className="fp-timeline-body eb-scroll">
            {!stats || stats.gap_lgas.length === 0 ? (
              <div className="fp-alert-empty">
                {stats
                  ? `Every LGA in ${stateLabel} has at least one reported activity site.`
                  : 'No data.'}
              </div>
            ) : (
              stats.gap_lgas.map((lga) => (
                <div key={lga} className="fp-tl-row">
                  <div className="fp-tl-dot fp-tl-crit">!</div>
                  <div className="fp-tl-content">
                    <div className="fp-tl-time">{lga} · no reported site</div>
                    <div className="fp-tl-event">No aid activity reported here</div>
                    <div className="fp-tl-detail">
                      Not proof of no aid — confirm with the state SEMA before planning.
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="fp-timeline">
          <div className="fp-timeline-header">Organisations in {stateLabel}</div>
          <div className="fp-timeline-body">
            {!stats || stats.agencies.length === 0 ? (
              <div className="fp-alert-empty">No organisation has reported current activity here.</div>
            ) : stats.agencies.map((a) => (
              <div key={a.agency_slug} className="fp-tl-row">
                <div className="fp-tl-dot fp-tl-ok">●</div>
                <div className="fp-tl-content">
                  <div className="fp-tl-time">{a.agency_name}</div>
                  <div className="fp-tl-event">
                    {a.sector} · {a.activities} {a.activities === 1 ? 'activity' : 'activities'}
                    {a.statewide_activities > 0 && ` · ${a.statewide_activities} ${stats.statewide_label.toLowerCase()}`}
                    {a.beneficiaries_served != null && ` · ~${fmtNum(a.beneficiaries_served)} beneficiaries`}
                  </div>
                  <div className="fp-tl-detail">
                    {a.lgas_covered.length > 0
                      ? `Sites in: ${a.lgas_covered.join(', ')}`
                      : `${stats.statewide_label} only — no specific site published`}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {stats && stats.sources.length > 0 && (
        <div className="fp-alert-attrib">
          Source: {stats.attribution ?? stats.sources.join(', ')}: activities in implementation today,
          published by each organisation. Activities pinned only to the{' '}
          {stats.statewide_label === 'Statewide' ? 'state' : 'country'} are shown as{' '}
          {stats.statewide_label.toLowerCase()}; national programmes run from Abuja are not counted in a
          state. An LGA with no reported activity is not an LGA without aid — state agencies and many
          NGOs do not publish to IATI.
        </div>
      )}
    </div>
  );
}
