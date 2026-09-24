'use client';

import { useMemo, useState } from 'react';

import { useTenant } from '@/context/TenantContext';
import { formatLatLon } from '@/lib/display';
import { useVillageLight, type UnlitVillage } from '@/hooks/useVillageLight';
import VillageLightMap, { type Season } from './VillageLightMap';

/**
 * Economic Visibility — the villages the grid does not reach.
 *
 * One practical question for a state: which of our villages show no light at
 * night, and how many people and young children live in them? Those are the
 * likeliest to be off-grid and underserved — the first stops for
 * electrification, cash-transfer enrolment, immunisation and aid.
 *
 * Every figure is measured at a REAL village (GRID3 names), from NASA VIIRS
 * night light and Meta & CIESIN HRSL population (migration 0054). It replaced
 * generated "<LGA> settlement N" points with a hashed population and a
 * "households unreached by aid" figure that had no source (2026-09-24).
 */

const STATE_NAMES: Record<string, string> = {
  kebbi: 'Kebbi State', benue: 'Benue State', plateau: 'Plateau State',
  kaduna: 'Kaduna State', niger: 'Niger State', zamfara: 'Zamfara State',
  nasarawa: 'Nasarawa State', fct: 'Federal Capital Territory',
  ghana: 'Ghana', senegal: 'Senegal',
};

const fmt = (n: number) => n.toLocaleString('en-GB');
const pct = (a: number, b: number) => (b ? `${Math.round((100 * a) / b)}%` : '—');

export default function EconomicVisibilityPanel() {
  const { activeTenantId, activeTenant, pilotTenants, setActiveTenant } = useTenant();
  const query = useVillageLight(activeTenantId);
  const data = query.data;
  const s = data?.stats ?? null;
  const [season, setSeason] = useState<Season>('dry');
  const [focus, setFocus] = useState<{ lng: number; lat: number; zoom?: number } | null>(null);
  const stateLabel = STATE_NAMES[activeTenantId] ?? activeTenant.name;
  const topLga = data?.lgas[0]?.people_unlit ?? 1;

  // Under-the-map insight cards — derived from the villages already loaded
  // for the map, so they cost no extra request.
  const insight = useMemo(() => {
    if (!data) return null;
    const unlit = data.points.filter((p) => p[2] === 0);
    const bands = [
      { label: '5,000+ people', min: 5000, max: Infinity, cls: 'ev-band--large' },
      { label: '1,000–4,999', min: 1000, max: 5000, cls: 'ev-band--mid' },
      { label: 'Under 1,000', min: 1, max: 1000, cls: 'ev-band--small' },
    ].map((b) => {
      const inBand = unlit.filter((p) => p[4] >= b.min && p[4] < b.max);
      return { ...b, villages: inBand.length, people: inBand.reduce((t, p) => t + p[4], 0) };
    });
    const sizes = unlit.map((p) => p[4]).filter((n) => n > 0).sort((a, b) => a - b);
    const lit = data.points.filter((p) => p[2] === 1 || p[2] === 2);
    return {
      bands,
      bandPeople: bands.reduce((t, b) => t + b.people, 0) || 1,
      median: sizes.length ? sizes[Math.floor(sizes.length / 2)] : 0,
      noBuildings: unlit.filter((p) => p[4] === 0).length,
      litVillages: lit.length,
      litPeople: lit.reduce((t, p) => t + p[4], 0),
    };
  }, [data]);

  const badge = query.isLoading
    ? { label: 'LOADING', cls: 'cg-mode-untuned' }
    : query.isError
      ? { label: 'API UNREACHABLE', cls: 'cg-mode-untuned' }
      : s
        ? { label: `MEASURED · ${data?.period}`, cls: 'cg-mode-trained' }
        : { label: 'NOT YET MEASURED', cls: 'cg-mode-untuned' };

  const showOnMap = (v: UnlitVillage) => {
    setFocus({ lng: v.location.lon, lat: v.location.lat, zoom: 12 });
    document.getElementById('ev-night-map')?.scrollIntoView({
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
      block: 'start',
    });
  };

  return (
    <div>
      <div className="cg-header">
        <div>
          <div className="cg-title">Economic Visibility — villages the grid does not reach</div>
          <div className="cg-subtitle">
            Every GRID3-named village, read from space at night · NASA VIIRS Black Marble ·
            Meta &amp; CIESIN HRSL population
          </div>
        </div>
        <div className={`cg-mode-badge ${badge.cls}`}>{badge.label}</div>
      </div>

      <div className="fp-tenant-bar">
        <label htmlFor="ev-tenant-select" className="fp-tenant-label">Viewing tenant</label>
        <select
          id="ev-tenant-select"
          className="fp-tenant-select"
          value={activeTenantId}
          onChange={(e) => { setFocus(null); setActiveTenant(e.target.value); }}
        >
          {pilotTenants.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
      </div>

      {query.isError && (
        <div className="fp-alert-error">Could not load village light: {query.error?.message ?? 'unknown'}.</div>
      )}
      {!query.isLoading && !query.isError && !s && (
        <div className="fp-alert-empty">
          {activeTenantId === 'ghana' || activeTenantId === 'senegal'
            ? `Village names for ${stateLabel} are not in GRID3's Nigeria register, so villages cannot be listed here yet.`
            : `${stateLabel} has not been measured yet — the village-light round runs once a year.`}
        </div>
      )}

      {s && data && (
        <>
          <div className="fp-grid">
            <div className="fp-stat ok">
              <div className="fp-stat-label">Named villages checked</div>
              <div className="fp-stat-val">{fmt(s.villages)}</div>
              <div className="fp-stat-sub">Every GRID3 village in {stateLabel}, each read from space at night</div>
            </div>
            <div className="fp-stat warn">
              <div className="fp-stat-label">No light at night</div>
              <div className="fp-stat-val">{fmt(s.unlit)}</div>
              <div className="fp-stat-sub">
                {pct(s.unlit, s.villages)} of villages, dry season · {fmt(s.unlit_both_seasons)} are dark in the wet season too
              </div>
            </div>
            <div className="fp-stat crit">
              <div className="fp-stat-label">People in unlit villages</div>
              <div className="fp-stat-val">{fmt(s.people_unlit)}</div>
              <div className="fp-stat-sub">{pct(s.people_unlit, s.people)} of people living at a named village</div>
            </div>
            <div className="fp-stat crit">
              <div className="fp-stat-label">Children under 5 in them</div>
              <div className="fp-stat-val">{fmt(s.under5_unlit)}</div>
              <div className="fp-stat-sub">For nutrition, immunisation and maternal-health outreach</div>
            </div>
          </div>

          <div className="fp-main-row">
            <div className="fp-map" id="ev-night-map">
              <div className="fp-map-header">
                <span className="fp-map-title">Night map — {stateLabel}</span>
                <div className="fp-map-controls">
                  {(['dry', 'wet'] as Season[]).map((k) => (
                    <button key={k} type="button" className={`fp-layer-btn ${season === k ? 'active' : ''}`}
                      aria-pressed={season === k} onClick={() => setSeason(k)}>
                      {k === 'dry' ? 'Dry season' : 'Wet season'}
                    </button>
                  ))}
                </div>
              </div>
              <VillageLightMap tenant={activeTenant} points={data.points} season={season} focus={focus} />
              <div className="fp-impact-footnote" style={{ padding: '9px 16px' }}>
                {season === 'dry' ? `Dry season, nights ${data.dry_window}` : `Wet season, nights ${data.wet_window}`} ·
                12-night median per village. Unlit rings grow with the number of people living there.
              </div>
              {insight && (
                <div className="ev-cards">
                  <div className="ev-card ev-card--wide">
                    <div className="ev-card-label">Unlit villages by size</div>
                    <div className="ev-bandbar" role="img"
                      aria-label={insight.bands.map((b) => `${b.label}: ${b.villages} villages, ${b.people} people`).join('; ')}>
                      {insight.bands.map((b) => (
                        <span key={b.label} className={`ev-band ${b.cls}`}
                          style={{ width: `${(100 * b.people) / insight.bandPeople}%` }} />
                      ))}
                    </div>
                    <div className="ev-bandrows">
                      {insight.bands.map((b) => (
                        <div key={b.label} className="ev-bandrow">
                          <span className={`ev-swatch ${b.cls}`} />
                          <span className="ev-bandrow-label">{b.label}</span>
                          <span className="ev-bandrow-num">{fmt(b.villages)} villages</span>
                          <span className="ev-bandrow-num">{fmt(b.people)} people</span>
                        </div>
                      ))}
                    </div>
                    <div className="ev-card-sub">
                      The largest dark communities reach the most people per trip.
                      {insight.noBuildings > 0 && ` ${fmt(insight.noBuildings)} named places show no mapped buildings nearby.`}
                    </div>
                  </div>
                  {data.lgas[0] && (
                    <div className="ev-card ev-card--alert">
                      <div className="ev-card-label">Hardest-hit LGA</div>
                      <div className="ev-card-num ev-card-num--text">{data.lgas[0].lga}</div>
                      <div className="ev-card-sub">
                        {fmt(data.lgas[0].people_unlit)} people in {fmt(data.lgas[0].unlit)} unlit villages —{' '}
                        {pct(data.lgas[0].people_unlit, s.people_unlit)} of the state&rsquo;s total
                      </div>
                    </div>
                  )}
                  <div className="ev-card">
                    <div className="ev-card-label">Typical unlit village</div>
                    <div className="ev-card-num">{fmt(insight.median)}</div>
                    <div className="ev-card-sub">people (median) — half are larger, half smaller</div>
                  </div>
                  <div className="ev-card ev-card--ok">
                    <div className="ev-card-label">Wet-season check</div>
                    <div className="ev-card-num">{pct(s.unlit_both_seasons, s.unlit)}</div>
                    <div className="ev-card-sub">of unlit villages are dark in the rains too — the reading is not cloud</div>
                  </div>
                  <div className="ev-card ev-card--warn">
                    <div className="ev-card-label">Young children</div>
                    <div className="ev-card-num">{pct(s.under5_unlit, s.people_unlit)}</div>
                    <div className="ev-card-sub">of people in unlit villages are under five — {fmt(s.under5_unlit)} children</div>
                  </div>
                  <div className="ev-card ev-card--lit">
                    <div className="ev-card-label">Already lit or dim</div>
                    <div className="ev-card-num">{fmt(insight.litVillages)}</div>
                    <div className="ev-card-sub">villages, home to {fmt(insight.litPeople)} people — where supply already reaches</div>
                  </div>
                </div>
              )}
            </div>

            <div className="fp-alerts">
              <div className="fp-alerts-header">
                Unlit villages, most people first
                <span className="fp-alert-count">{fmt(s.unlit)} UNLIT</span>
              </div>
              {data.top_unlit.map((v) => (
                <div key={`${v.name}-${v.location.lat}-${v.location.lon}`} className="fp-alert-item">
                  <div className="fp-alert-top">
                    <span className="fp-alert-location">{v.name}</span>
                    <span className="fp-sev fp-sev-crit">No light</span>
                  </div>
                  <div className="fp-alert-desc">
                    {v.ward ? `${v.ward} ward · ` : ''}{v.lga} LGA · about {fmt(v.people)} people, {fmt(v.under5)} under five
                    {v.light_class_wet === 'unlit' ? '' : ' · lit in the wet-season check'}
                  </div>
                  <div className="fp-alert-coords">
                    📍 {formatLatLon(v.location.lat, v.location.lon)} · night light {v.radiance_dry ?? '—'} nW/cm²/sr ·{' '}
                    <button type="button" onClick={() => showOnMap(v)}
                      style={{ background: 'transparent', border: 'none', padding: 0, cursor: 'pointer', font: 'inherit', color: '#2f855a', textDecoration: 'underline' }}>
                      Show on map
                    </button>{' · '}
                    <a className="fp-directions-link" target="_blank" rel="noopener noreferrer"
                      href={`https://www.google.com/maps/dir/?api=1&destination=${v.location.lat},${v.location.lon}`}>
                      Directions ↗
                    </a>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="fp-main-row fp-main-row--equal">
            <div className="fp-timeline">
              <div className="fp-timeline-header">Where to act first — LGAs by people living in unlit villages</div>
              <div className="ev-lga-table-wrap eb-scroll">
                <table className="ev-lga-table">
                  <thead>
                    <tr><th>LGA</th><th>Villages</th><th>Unlit</th><th>People in unlit villages</th><th>Children under 5</th></tr>
                  </thead>
                  <tbody>
                    {data.lgas.map((g) => (
                      <tr key={g.lga}>
                        <td>{g.lga}</td>
                        <td>{fmt(g.villages)}</td>
                        <td>{fmt(g.unlit)} · {pct(g.unlit, g.villages)}</td>
                        <td>
                          <span className="ev-lga-bar" style={{ width: `${Math.max(2, (90 * g.people_unlit) / topLga)}px` }} />
                          {fmt(g.people_unlit)}
                        </td>
                        <td>{fmt(g.under5_unlit)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <div className="fp-impact-footnote" style={{ padding: '12px 0' }}>
            <b>What this measures:</b> whether light is detectable from space at each named village at night, and
            how many people and young children live within a kilometre of it (each person counted once, at the
            nearest village). <b>What it does not:</b> household income, or a single bulb or solar lamp — &ldquo;no
            light&rdquo; means below what the satellite detects, so a field team confirms. Sources: GRID3 NGA
            Settlement Names (CC BY 4.0) · NASA VIIRS Black Marble VNP46A2 · Meta &amp; CIESIN High Resolution
            Settlement Layer (CC BY 4.0). Round {data.period}.
          </div>
        </>
      )}
    </div>
  );
}
