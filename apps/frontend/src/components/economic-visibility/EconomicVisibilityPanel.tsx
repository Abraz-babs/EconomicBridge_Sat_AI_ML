'use client';

import { useMemo } from 'react';

import { useTenant } from '@/context/TenantContext';
import { povertyStatsFor, type PovertyVillage } from '@/data/povertySeed';
import PovertyMap from './PovertyMap';


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

  const stats = useMemo(
    () => povertyStatsFor(activeTenantId, activeTenant.centroid),
    [activeTenantId, activeTenant.centroid],
  );

  const ranked = useMemo(
    () => [...stats.villages].sort((a, b) => b.poverty_score - a.poverty_score),
    [stats.villages],
  );

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
        <div className="cg-mode-badge cg-mode-untuned">DEV · seed data</div>
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
      </div>

      {/* STATS */}
      <div className="fp-grid">
        <div className="fp-stat warn">
          <div className="fp-stat-label">Villages Identified</div>
          <div className="fp-stat-val">{stats.villages_identified}</div>
          <div className="fp-stat-sub">From satellite nightlight + WorldPop clustering</div>
        </div>
        <div className="fp-stat crit">
          <div className="fp-stat-label">Population Estimated</div>
          <div className="fp-stat-val">{fmtNum(stats.population_estimated)}</div>
          <div className="fp-stat-sub">Across identified vulnerable settlements</div>
        </div>
        <div className="fp-stat crit">
          <div className="fp-stat-label">Households Unreached</div>
          <div className="fp-stat-val">{fmtNum(stats.hh_unreached)}</div>
          <div className="fp-stat-sub">Not covered by current aid programs</div>
        </div>
        <div className="fp-stat ok">
          <div className="fp-stat-label">DHS Verification</div>
          <div className="fp-stat-val">{fmtPct(stats.verification_pct)}</div>
          <div className="fp-stat-sub">Villages with cross-validated survey data</div>
        </div>
      </div>

      {/* MAP + RANKING */}
      <div className="fp-main-row">
        <div className="fp-map">
          <div className="fp-map-header">
            <span className="fp-map-title">
              Poverty Intensity — {stats.state_label}
            </span>
            <span className="ev-map-meta">
              {stats.villages.length} settlements ·
              Sources: VIIRS · WorldPop · DHS · Landsat 9
            </span>
          </div>
          <PovertyMap tenant={activeTenant} villages={stats.villages} />
        </div>

        <div className="fp-alerts">
          <div className="fp-alerts-header">
            Vulnerability Ranking — {stats.state_label}
            <span className="fp-alert-count">{ranked.length} VILLAGES</span>
          </div>
          {ranked.map((v, idx) => (
            <VillageRow key={v.id} village={v} rank={idx + 1} />
          ))}
        </div>

        <div className="fp-timeline">
          <div className="fp-timeline-header">Aid-Delivery Priority — {stats.state_label}</div>
          <div className="fp-timeline-body">
            <div className="fp-impact-row fp-impact-row--bordered">
              <div>
                <div className="fp-impact-label">Coverage Gap</div>
                <div className="fp-impact-val">{fmtPct(100 - stats.coverage_pct)}</div>
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
                  Poverty score {(ranked[0]?.poverty_score ?? 0).toFixed(2)} · ~{fmtNum(ranked[0]?.population ?? 0)} pop.
                </div>
              </div>
              <div>
                <div className="fp-impact-label">Verification Rate</div>
                <div className="fp-impact-val fp-impact-val--small">
                  {fmtPct(stats.verification_pct)}
                </div>
                <div className="fp-impact-desc">
                  Sample-validated via DHS survey joins
                </div>
              </div>
            </div>
            <div className="fp-impact-footnote">
              Data sources: <code>VIIRS Nightlight</code>, <code>WorldPop</code>, <code>DHS Survey</code>, <code>Landsat 9</code>.
              Real ingestion lands in a follow-up slice; current rendering is deterministic seed data
              hashed from the tenant slug so each state shows a stable example.
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
          #{rank} · {village.lga} — {village.name}
        </span>
        <span className={`fp-sev ${severity}`}>
          {village.poverty_score >= 0.80 ? 'Critical' : village.poverty_score >= 0.65 ? 'High' : 'Medium'}
        </span>
      </div>
      <div className="fp-alert-desc">
        Estimated population {fmtNum(village.population)}.{' '}
        {village.hh_unreached > 0 && <>~{fmtNum(village.hh_unreached)} households unreached by current aid. </>}
        {village.has_dhs_data ? 'DHS survey data on file.' : 'No ground-truth data — high uncertainty.'}
      </div>
      <div className="fp-alert-meta">
        <span>Nightlight dimness: {(village.nightlight_dimness * 100).toFixed(0)}%</span>
        <span>Poverty score: {village.poverty_score.toFixed(2)}</span>
      </div>
      <div className="fp-alert-coords">
        📍 {village.lat.toFixed(4)}°N, {village.lon.toFixed(4)}°E
      </div>
    </div>
  );
}
