'use client';

import { useMemo } from 'react';

import { useTenant } from '@/context/TenantContext';
import { formatLatLon, sourceBadge } from '@/lib/display';
import {
  usePovertyVillages,
  type PovertyVillage,
} from '@/hooks/usePovertyVillages';
import PovertyMap from './PovertyMap';


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


export default function EconomicVisibilityPanel() {
  const { activeTenantId, activeTenant, pilotTenants, setActiveTenant } = useTenant();

  const query = usePovertyVillages({ tenantId: activeTenantId });
  const stats = query.data;

  const ranked = useMemo<PovertyVillage[]>(
    () => [...(stats?.villages ?? [])].sort(
      (a, b) => b.poverty_score - a.poverty_score,
    ),
    [stats?.villages],
  );
  const stateLabel = STATE_NAMES[activeTenantId] ?? activeTenant.name;
  const isSeedOnly = stats?.sources.length === 1 && stats.sources[0] === 'seed_v1';
  const badge = sourceBadge(stats?.sources, { loading: query.isLoading, error: query.isError });

  return (
    <div>
      {/* HEADER */}
      <div className="cg-header">
        <div>
          <div className="cg-title">Poverty Mapping — Economic Visibility</div>
          <div className="cg-subtitle">
            Satellite-derived poverty intensity for villages missed by traditional census ·
            VIIRS Nightlight + WorldPop + DHS validation
          </div>
        </div>
        <div className={`cg-mode-badge ${badge.cls}`}>{badge.label}</div>
      </div>

      {/* TENANT SELECTOR */}
      <div className="fp-tenant-bar">
        <label htmlFor="ev-tenant-select" className="fp-tenant-label">Viewing tenant</label>
        <select
          id="ev-tenant-select"
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
          Could not load poverty data: {query.error?.message ?? 'unknown'}.{' '}
          Run <code>python -m scripts.seed_poverty_villages</code> from{' '}
          <code>apps/api/</code> to populate seed rows.
        </div>
      )}

      {/* STATS */}
      <div className="fp-grid">
        <div className="fp-stat warn">
          <div className="fp-stat-label">Villages Identified</div>
          <div className="fp-stat-val">{stats?.villages_identified ?? '—'}</div>
          <div className="fp-stat-sub">From satellite nightlight + WorldPop clustering</div>
        </div>
        <div className="fp-stat crit">
          <div className="fp-stat-label">Population Estimated</div>
          <div className="fp-stat-val">
            {stats ? fmtNum(stats.population_estimated) : '—'}
          </div>
          <div className="fp-stat-sub">Across identified vulnerable settlements</div>
        </div>
        <div className="fp-stat crit">
          <div className="fp-stat-label">Households Unreached</div>
          <div className="fp-stat-val">
            {stats ? fmtNum(stats.households_unreached) : '—'}
          </div>
          <div className="fp-stat-sub">Not covered by current aid programs</div>
        </div>
        <div className="fp-stat ok">
          <div className="fp-stat-label">DHS Verification</div>
          <div className="fp-stat-val">
            {stats ? fmtPct(stats.verification_pct) : '—'}
          </div>
          <div className="fp-stat-sub">Villages with cross-validated survey data</div>
        </div>
      </div>

      {/* Phase B (Slice 09) — real WorldPop COG pixel reads. Banner sits
         between the stat grid and the map so it reads as a provenance
         note rather than a 5th stat tile that would overflow fp-grid. */}
      {stats && stats.villages_identified > 0 && (
        <div className="ev-raster-banner">
          <span className="ev-raster-banner__chip">
            Phase B · WorldPop COG sampling
          </span>
          <span>
            <strong>
              {stats.raster_sampled_villages} / {stats.villages_identified}
            </strong>{' '}
            villages enriched with real WorldPop pixel reads
          </span>
        </div>
      )}

      {/* MAP + RANKING */}
      <div className="fp-main-row">
        <div className="fp-map">
          <div className="fp-map-header">
            <span className="fp-map-title">
              Poverty Intensity — {stateLabel}
            </span>
            <span className="ev-map-meta">
              {stats?.villages.length ?? 0} settlements ·
              Sources: {stats?.sources.join(', ') ?? '—'}
            </span>
          </div>
          <PovertyMap tenant={activeTenant} villages={stats?.villages ?? []} />
        </div>

        <div className="fp-alerts">
          <div className="fp-alerts-header">
            Vulnerability Ranking — {stateLabel}
            <span className="fp-alert-count">{ranked.length} VILLAGES</span>
          </div>
          {query.isLoading && (
            <div className="fp-alert-empty">Loading villages…</div>
          )}
          {!query.isLoading && !query.isError && ranked.length === 0 && (
            <div className="fp-alert-empty">
              No villages recorded for {stateLabel}. Run{' '}
              <code>python -m scripts.seed_poverty_villages</code> from{' '}
              <code>apps/api/</code> to populate sample data.
            </div>
          )}
          {ranked.map((v, idx) => (
            <VillageRow key={v.id} village={v} rank={idx + 1} />
          ))}
        </div>
      </div>

      {/* AID PRIORITY */}
      <div className="fp-main-row fp-main-row--equal">
        <div className="fp-timeline">
          <div className="fp-timeline-header">Aid-Delivery Priority — {stateLabel}</div>
          <div className="fp-timeline-body">
            <div className="fp-impact-row fp-impact-row--bordered">
              <div>
                <div className="fp-impact-label">Coverage Gap</div>
                <div className="fp-impact-val">
                  {stats ? fmtPct(100 - stats.coverage_pct) : '—'}
                </div>
                <div className="fp-impact-desc">
                  Pop. not reached by NGO / gov programs
                </div>
              </div>
              <div>
                <div className="fp-impact-label">Hottest Village</div>
                <div className="fp-impact-val fp-impact-val--small">
                  {ranked[0]?.lga ?? '—'}
                </div>
                <div className="fp-impact-desc">
                  {ranked[0]
                    ? <>Poverty score {ranked[0].poverty_score.toFixed(2)} · ~{fmtNum(ranked[0].population)} pop.</>
                    : 'No data'}
                </div>
              </div>
              <div>
                <div className="fp-impact-label">Verification Rate</div>
                <div className="fp-impact-val fp-impact-val--small">
                  {stats ? fmtPct(stats.verification_pct) : '—'}
                </div>
                <div className="fp-impact-desc">
                  Sample-validated via DHS survey joins
                </div>
              </div>
            </div>
            <div className="fp-impact-footnote">
              {isSeedOnly ? (
                <>
                  Data sources: <code>seed_v1</code> only. Real VIIRS Nightlight
                  + WorldPop + DHS ingestion lands in a follow-up slice; the
                  schema + endpoint contract stay unchanged when it flips.
                </>
              ) : (
                <>
                  Data sources: {(stats?.sources ?? []).map((s, i) => (
                    <span key={s}><code>{s}</code>{i < (stats?.sources.length ?? 1) - 1 ? ', ' : ''}</span>
                  ))}.
                  AI: poverty score = VIIRS dimness × 0.6 + DHS adjustment × 0.4.
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}


function VillageRow({ village, rank }: { village: PovertyVillage; rank: number }) {
  const severity = village.poverty_score >= 0.80
    ? 'fp-sev-crit'
    : village.poverty_score >= 0.65 ? 'fp-sev-high' : 'fp-sev-med';
  return (
    <div className="fp-alert-item">
      <div className="fp-alert-top">
        <span className="fp-alert-location">
          #{rank} · {village.lga} — {village.settlement_name}
        </span>
        <span className={`fp-sev ${severity}`}>
          {village.poverty_score >= 0.80 ? 'Critical' : village.poverty_score >= 0.65 ? 'High' : 'Medium'}
        </span>
      </div>
      <div className="fp-alert-desc">
        Estimated population {fmtNum(village.population)}.{' '}
        {village.households_unreached > 0 && (
          <>~{fmtNum(village.households_unreached)} households unreached by current aid. </>
        )}
        {village.has_dhs_data ? 'DHS survey data on file.' : 'No ground-truth data — high uncertainty.'}
      </div>
      <div className="fp-alert-meta">
        <span>Nightlight dimness: {(village.nightlight_dimness * 100).toFixed(0)}%</span>
        <span>Poverty score: {village.poverty_score.toFixed(2)}</span>
        <span>Source: {village.source}</span>
        {village.latest_worldpop_sample !== null && (
          <span title="Real per-pixel WorldPop 2020 sample from the COG sweep">
            WorldPop pixel: {fmtNum(Math.round(village.latest_worldpop_sample))}
          </span>
        )}
      </div>
      <div className="fp-alert-coords">
        📍 {formatLatLon(village.location.lat, village.location.lon)}
        {' · '}
        {village.lga} LGA
      </div>
    </div>
  );
}
