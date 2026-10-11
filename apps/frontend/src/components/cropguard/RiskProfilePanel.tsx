'use client';

/**
 * Pre-season risk profile — CropGuard's insurer section (operator-approved mock
 * 2026-10-09, decisions 2026-10-10). Every LGA gets a flood band, a drought band
 * and a failed-rains band under one published rule, with the figures behind each
 * and the map layers they come from: farmland in the JRC river flood zones,
 * water UNOSAT saw from satellite, 35 seasons of CHIRPS rainfall and daily
 * rainfall since 1998. Insurer accounts and the operator see it; the PDF on the
 * letterhead and the CSV are super-admin only, like every export.
 */

import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react';
import { BitmapLayer, GeoJsonLayer } from '@deck.gl/layers';

import ModuleSources from '@/components/common/ModuleSources';
import EBMap from '@/components/map/EBMap';
import HaloCard from '@/components/map/HaloCard';
import MapToolbar from '@/components/map/MapToolbar';
import { BASEMAP_STYLE, fillAlpha, type Basemap } from '@/components/map/basemaps';
import { useAuth } from '@/context/AuthContext';
import type { Tenant } from '@/data/tenants';
import { useRiskProfile, type Band, type BandKind, type RiskLga } from '@/hooks/useRiskProfile';
import { downloadFile } from '@/lib/api';

type RGB = [number, number, number];

const PALETTE: Record<BandKind, Record<Band, RGB>> = {
  flood: { high: [79, 127, 176], moderate: [169, 196, 222], low: [227, 235, 242], none: [190, 190, 190] },
  drought: { high: [154, 90, 18], moderate: [220, 174, 85], low: [242, 232, 207], none: [190, 190, 190] },
  rains: { high: [155, 63, 43], moderate: [222, 154, 124], low: [246, 230, 220], none: [190, 190, 190] },
};
const KIND_LABEL: Record<BandKind, string> = { flood: 'Flood band', drought: 'Drought band', rains: 'Failed-rains band' };
const BAND_LABEL: Record<Band, string> = { high: 'High', moderate: 'Moderate', low: 'Low', none: '—' };
const ORDER: Record<Band, number> = { high: 0, moderate: 1, low: 2, none: 3 };
const OVERLAYS: { key: string; light: RGB; dark: RGB }[] = [
  { key: 'rp10_farmland', light: [29, 53, 87], dark: [156, 200, 240] },
  { key: 'flood_2024-09', light: [15, 156, 194], dark: [63, 208, 232] },
  { key: 'flood_2022-10', light: [122, 91, 196], dark: [184, 162, 230] },
];
const MONTH = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTH_LONG = ['', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
  'October', 'November', 'December'];

const hex = (c: RGB) => `#${c.map((v) => v.toString(16).padStart(2, '0')).join('')}`;
const n0 = (v: number | null | undefined) => (v == null ? '—' : Math.round(v).toLocaleString('en-GB'));
const ha = (v: number | null | undefined) =>
  (v == null ? '—' : `${(v >= 1000 ? Math.round(v / 100) * 100 : Math.round(v)).toLocaleString('en-GB')} ha`);
const pc = (v: number | null | undefined, d = 1) =>
  (v == null ? '—' : v > 0 && v < 10 ** -d ? `<${10 ** -d}%` : `${v.toFixed(d)}%`);
const span = (m: number[]) => (m.length ? `${MONTH[m[0]]}–${MONTH[m[m.length - 1]]}` : '—');
const onsetText = (mmdd: string | null | undefined) => {
  if (!mmdd) return null;
  const [m, d] = mmdd.split('-').map(Number);
  return `${d} ${MONTH_LONG[m]}`;
};
const bandOf = (l: RiskLga, k: BandKind): Band => (k === 'flood' ? l.band_flood : k === 'drought' ? l.band_drought : l.band_rains);
const years = (ys: number[] | undefined) => (ys && ys.length ? ys.join(', ') : 'none');
/** The 1-in-10-year figure as the band reads it: of farmland, or of land where little farmland is mapped. */
const zoneShare = (l: RiskLga) => (l.figures.flood.basis === 'land'
  ? `${pc(l.figures.flood.rp10_area_pct)} of land`
  : `${pc(l.figures.flood.rp10_crop_pct)} of farmland`);

function Chip({ band, kind }: { band: Band; kind?: BandKind }) {
  return (
    <span className={`rp-chip rp-chip--${band}`} title={kind ? KIND_LABEL[kind] : undefined}>
      {kind ? `${kind === 'rains' ? 'Rains' : kind === 'flood' ? 'Flood' : 'Drought'} ` : ''}{BAND_LABEL[band]}
    </span>
  );
}

/** A greyscale mask (white = inside) painted in one colour on a transparent canvas. */
function useTintedMask(uri: string | undefined, rgb: RGB): HTMLCanvasElement | null {
  const [canvas, setCanvas] = useState<HTMLCanvasElement | null>(null);
  const [r, g, b] = rgb;
  useEffect(() => {
    if (!uri) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCanvas(null);
      return;
    }
    let live = true;
    const img = new Image();
    img.onload = () => {
      if (!live) return;
      const c = document.createElement('canvas');
      c.width = img.width;
      c.height = img.height;
      const ctx = c.getContext('2d');
      if (!ctx) return;
      ctx.drawImage(img, 0, 0);
      const px = ctx.getImageData(0, 0, c.width, c.height);
      for (let i = 0; i < px.data.length; i += 4) {
        const on = px.data[i] > 127;
        px.data[i] = r;
        px.data[i + 1] = g;
        px.data[i + 2] = b;
        px.data[i + 3] = on ? 235 : 0;
      }
      ctx.putImageData(px, 0, 0);
      setCanvas(c);
    };
    img.src = uri;
    return () => { live = false; };
  }, [uri, r, g, b]);
  return canvas;
}

/** What the figures say about one LGA, in plain words (same wording as the PDF). */
function plain(l: RiskLga): string[] {
  const f = l.figures;
  const out: string[] = [];
  if (f.flood.basis === 'land') {
    const za = f.flood.rp10_area_pct ?? 0;
    const za100 = f.flood.rp100_area_pct ?? 0;
    const lead = `ESA maps little farmland in ${l.lga} (${pc(f.cropland_pct)} of the LGA; farms under trees read as tree cover), so its flood band reads its land: `;
    if (za >= 10) out.push(`${lead}${Math.round(za)}% of it lies in the zone the river model floods about once every 10 years.`);
    else if (za100 >= 3) out.push(`${lead}${Math.round(za100)}% lies in the 1-in-100-year zone and ${pc(za)} in the 1-in-10-year zone.`);
    else out.push(`${lead}almost none lies in the modelled river flood zones (${pc(za100)} in the 1-in-100-year zone).`);
  } else {
    const z = f.flood.rp10_crop_pct ?? 0;
    const z100 = f.flood.rp100_crop_pct ?? 0;
    if (z >= 10) out.push(`${Math.round(z)}% of ${l.lga}'s farmland (${ha(f.flood.rp10_crop_ha)}) lies in the zone the river model floods about once every 10 years.`);
    else if (z100 >= 3) out.push(`${Math.round(z100)}% of ${l.lga}'s farmland lies in the 1-in-100-year river flood zone, and ${pc(z)} in the 1-in-10-year zone.`);
    else out.push(`Almost none of ${l.lga}'s farmland lies in the modelled river flood zones (${pc(z100)} in the 1-in-100-year zone).`);
  }
  const maps = Object.values(f.flood.mapped ?? {});
  const seen = maps.filter((m) => (m.area_pct ?? 0) >= 1);
  if (seen.length) out.push(`Satellites saw flood water over ${seen.map((m) => `${pc(m.area_pct)} of the LGA on ${m.label}`).join(' and ')}.`);
  else if (maps.length) out.push(`${maps.length === 2 ? 'Neither' : 'No'} mapped flood put as much as 1% of the LGA under water.`);
  const r = f.rain;
  if (r) {
    const n = r.last_year - r.first_year + 1;
    const k = r.drought_seasons.length;
    out.push(`${k ? `${k} of the ${n} seasons since ${r.first_year} fell` : `No season since ${r.first_year} fell`} below 80% of normal rainfall; the driest was ${r.worst.year} at ${Math.round(r.worst.pct_of_normal ?? 0)}% of normal.`);
  }
  const rn = f.rains;
  if (rn && rn.years.length) {
    const on = onsetText(rn.onset_median);
    out.push(`Since ${rn.years[0]}, ${rn.failed_seasons.length} of ${rn.years.length} seasons had a false start, a late onset or a long dry spell after planting${on ? `; the rains usually set in around ${on}` : ''}.`);
  }
  return out;
}

function SeasonChart({ l }: { l: RiskLga }) {
  const r = l.figures.rain;
  const ys = Object.keys(r.totals).map(Number).sort((a, b) => a - b);
  if (!ys.length || !r.normal_mm) return null;
  const W = 300, H = 104, L = 26, B = 15, T = 5, R = 3;
  const vals = ys.map((y) => (100 * r.totals[String(y)]) / r.normal_mm);
  const lo = 40;
  const hi = Math.max(150, Math.ceil(Math.max(...vals) / 10) * 10);
  const y = (v: number) => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
  const bw = (W - L - R) / ys.length;
  return (
    <svg className="rp-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Season rainfall as a share of normal, ${ys[0]} to ${ys[ys.length - 1]}`}>
      {[60, 80, 100, 120, 140].filter((v) => v <= hi).map((v) => (
        <g key={v}>
          <line className="rp-chart-grid" x1={L} x2={W - R} y1={y(v)} y2={y(v)} />
          <text x={L - 4} y={y(v) + 3} textAnchor="end">{v}%</text>
        </g>
      ))}
      {ys.map((yr, i) => {
        const v = vals[i];
        const top = y(Math.max(v, lo));
        return (
          <rect key={yr} className={`rp-chart-bar${v < 80 ? ' is-dry' : ''}`} x={L + i * bw + 0.6} y={top}
            width={Math.max(0.5, bw - 1.2)} height={Math.max(0, y(lo) - top)}>
            <title>{`${yr}: ${Math.round(r.totals[String(yr)])} mm, ${Math.round(v)}% of normal`}</title>
          </rect>
        );
      })}
      <line className="rp-chart-norm" x1={L} x2={W - R} y1={y(100)} y2={y(100)} />
      <line className="rp-chart-thr" x1={L} x2={W - R} y1={y(80)} y2={y(80)} />
      {[ys[0], 2000, 2010, 2020, ys[ys.length - 1]].filter((v, i, a) => ys.includes(v) && a.indexOf(v) === i).map((yr) => (
        <text key={yr} x={L + ys.indexOf(yr) * bw + bw / 2} y={H - 3} textAnchor="middle">{yr}</text>
      ))}
    </svg>
  );
}


export default function RiskProfilePanel({ tenant, stateLabel }: { tenant: Tenant; stateLabel: string }) {
  const { isSuperAdmin } = useAuth();
  const q = useRiskProfile(tenant.id);
  const data = q.data;
  const [basemap, setBasemap] = useState<Basemap>('light');
  const [fill, setFill] = useState<BandKind>('flood');
  const [on, setOn] = useState<Record<string, boolean>>({ rp10_farmland: true, 'flood_2024-09': false, 'flood_2022-10': false });
  const [sel, setSel] = useState<string | null>(null);
  const [cardOpen, setCardOpen] = useState(false);
  const [client, setClient] = useState('');
  const [ref, setRef] = useState('');
  const [busy, setBusy] = useState<'pdf' | 'csv' | null>(null);
  const [dlError, setDlError] = useState<string | null>(null);
  useEffect(() => {
    // A selection points into this state's data — drop it when the state changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSel(null);
    setCardOpen(false);
  }, [tenant.id]);

  const dark = basemap !== 'light';
  const alpha = fillAlpha(basemap);
  const lgas = useMemo(() => data?.lgas ?? [], [data]);
  const byName = useMemo(() => new Map(lgas.map((l) => [l.lga, l])), [lgas]);
  const sorted = useMemo(() => [...lgas].sort((a, b) => {
    const k = ORDER[bandOf(a, fill)] - ORDER[bandOf(b, fill)];
    if (k) return k;
    if (fill === 'flood') return (b.figures.flood.rp10_crop_pct ?? 0) - (a.figures.flood.rp10_crop_pct ?? 0);
    if (fill === 'drought') return b.figures.rain.drought_seasons.length - a.figures.rain.drought_seasons.length || a.lga.localeCompare(b.lga);
    return (b.figures.rains?.failed_seasons.length ?? 0) - (a.figures.rains?.failed_seasons.length ?? 0) || a.lga.localeCompare(b.lga);
  }), [lgas, fill]);
  const overlayBy = useMemo(() => new Map((data?.overlays ?? []).map((o) => [o.layer, o])), [data]);
  const masks = {
    rp10_farmland: useTintedMask(overlayBy.get('rp10_farmland')?.image, dark ? OVERLAYS[0].dark : OVERLAYS[0].light),
    'flood_2024-09': useTintedMask(overlayBy.get('flood_2024-09')?.image, dark ? OVERLAYS[1].dark : OVERLAYS[1].light),
    'flood_2022-10': useTintedMask(overlayBy.get('flood_2022-10')?.image, dark ? OVERLAYS[2].dark : OVERLAYS[2].light),
  } as Record<string, HTMLCanvasElement | null>;
  const m0 = masks.rp10_farmland, m1 = masks['flood_2024-09'], m2 = masks['flood_2022-10'];
  const geo = useMemo(() => ({
    type: 'FeatureCollection',
    features: lgas.map((l) => ({ type: 'Feature', properties: { lga: l.lga }, geometry: l.figures.outline })),
  }), [lgas]);

  const detail = (sel && byName.get(sel)) || sorted[0] || null;

  const layers = useMemo(() => {
    const out: unknown[] = [];
    if (!lgas.length) return out;
    out.push(new GeoJsonLayer({
      id: 'rp-fill',
      data: geo as never,
      filled: true,
      stroked: true,
      pickable: true,
      getFillColor: (f: { properties: { lga: string } }) => {
        const l = byName.get(f.properties.lga);
        return l ? [...PALETTE[fill][bandOf(l, fill)], alpha] : [140, 140, 140, 30];
      },
      getLineColor: (f: { properties: { lga: string } }) =>
        (f.properties.lga === sel ? (dark ? [255, 255, 255, 255] : [26, 23, 20, 255]) : [255, 255, 255, 190]),
      getLineWidth: (f: { properties: { lga: string } }) => (f.properties.lga === sel ? 3 : 1),
      lineWidthUnits: 'pixels',
      onClick: (info: { object?: { properties: { lga: string } } }) => {
        const name = info.object?.properties.lga;
        if (name) { setSel(name); setCardOpen(true); }
      },
      updateTriggers: { getFillColor: [fill, alpha, byName], getLineColor: [sel, dark], getLineWidth: [sel] },
    }));
    const ovs: [string, HTMLCanvasElement | null][] = [['rp10_farmland', m0], ['flood_2024-09', m1], ['flood_2022-10', m2]];
    for (const [key, canvas] of ovs) {
      const o = overlayBy.get(key);
      if (!o || !canvas || !on[key]) continue;
      out.push(new BitmapLayer({ id: `rp-${key}`, image: canvas as never, bounds: o.bounds, pickable: false }));
    }
    return out;
  }, [lgas, geo, byName, fill, alpha, sel, dark, overlayBy, m0, m1, m2, on]);

  let card: { lng: number; lat: number; node: ReactNode } | null = null;
  if (cardOpen && sel) {
    const l = byName.get(sel);
    if (l) {
      const f = l.figures;
      const latest = Object.values(f.flood.mapped ?? {})[0];
      card = {
        lng: f.centroid[0], lat: f.centroid[1],
        node: (
          <HaloCard
            title={`${l.lga} · ${BAND_LABEL[l.band_flood]} flood · ${BAND_LABEL[l.band_drought]} drought · ${BAND_LABEL[l.band_rains]} failed rains`}
            big={`${zoneShare(l)} in the 1-in-10-year flood zone`}
            rows={[
              f.flood.basis === 'land'
                ? { k: 'Farmland mapped', v: `${pc(f.cropland_pct)} of LGA (little: band reads land)` }
                : { k: 'Farmland in zone', v: ha(f.flood.rp10_crop_ha) },
              ...(latest ? [{ k: `Water ${latest.label}`, v: `${pc(latest.area_pct)} of the LGA` }] : []),
              { k: 'Below 80% rain', v: `${f.rain.drought_seasons.length} of ${f.rain.last_year - f.rain.first_year + 1} seasons` },
              ...(f.rains?.years.length ? [{ k: 'Failed rains', v: `${f.rains.failed_seasons.length} of ${f.rains.years.length} seasons` }] : []),
              { k: 'Farmland', v: ha(f.cropland_ha) },
              ...(f.exposure ? [{ k: 'People', v: n0(f.exposure.people) }] : []),
            ]}
            why={plain(l).slice(0, 2).join(' ')}
            onClose={() => setCardOpen(false)}
          />
        ),
      };
    }
  }

  const S = data?.summary;
  const through = data?.through_season;
  const download = async (kind: 'pdf' | 'csv') => {
    setDlError(null);
    setBusy(kind);
    try {
      const stamp = new Date().toISOString().slice(0, 10);
      if (kind === 'pdf') {
        await downloadFile('/cropguard/risk-profile/report', `risk_profile_${tenant.id}_${stamp}.pdf`, {
          tenantId: tenant.id, method: 'POST', body: { prepared_for: client.trim(), reference: ref.trim() },
        });
      } else {
        await downloadFile('/cropguard/risk-profile/export.csv', `risk_profile_${tenant.id}_${stamp}.csv`, { tenantId: tenant.id });
      }
    } catch (e) {
      setDlError(e instanceof Error ? e.message : 'Download failed');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="sb-table-wrap rp" style={{ marginTop: '16px' }}>
      <div className="cg-section-header">Pre-season risk profile</div>
      <div className="cg-subtitle">
        Where floods and failed rains have reached farmland in {stateLabel}, LGA by LGA, for underwriting before
        planting. Every LGA gets a flood band, a drought band and a failed-rains band under one published rule, the
        same in every state.
      </div>
      <ModuleSources sources={[
        { name: 'JRC / Copernicus GloFAS', role: 'river flood zones, 1-in-10 and 1-in-100 years' },
        { name: 'UNOSAT · NOAA VIIRS', role: 'flood water seen from satellite' },
        { name: 'CHIRPS v3', role: `rainfall${data?.first_season ? ` ${data.first_season}–${through}` : ''}, and daily rainfall${data?.rains_first_season ? ` since ${data.rains_first_season}` : ''}` },
        { name: 'ESA WorldCover', role: 'farmland' },
        { name: 'GRID3 · Meta & CIESIN HRSL', role: 'villages and people' },
      ]} />

      {q.isLoading && <div className="rp-empty">Loading the risk profile…</div>}
      {q.isError && <div className="fp-alert-error">Could not load the risk profile: {q.error?.message ?? 'unknown error'}</div>}
      {data && !data.available && (
        <div className="rp-empty">No risk profile has been measured for {stateLabel} yet. It is measured once a year, before planting.</div>
      )}

      {data?.available && S && (
        <>
          <div className="rp-kpis">
            <div className="rp-kpi">
              <span className="rp-kpi-val">{ha(S.rp10_cropland_ha)}</span>
              <span className="rp-kpi-label">
                of farmland in the 1-in-10-year river flood zone ({pc(S.cropland_ha ? (100 * S.rp10_cropland_ha) / S.cropland_ha : null)} of {ha(S.cropland_ha)})
              </span>
            </div>
            {S.mapped[0] && (
              <div className="rp-kpi">
                <span className="rp-kpi-val">{ha(S.mapped[0].cropland_ha)}</span>
                <span className="rp-kpi-label">of farmland seen under water, {S.mapped[0].label} (UNOSAT)</span>
              </div>
            )}
            <div className="rp-kpi">
              <span className="rp-kpi-val">{S.bands.flood.high} · {S.bands.flood.moderate} · {S.bands.flood.low}</span>
              <span className="rp-kpi-label">LGAs with a High · Moderate · Low flood band</span>
            </div>
            {S.rains_failed_max != null ? (
              <div className="rp-kpi">
                <span className="rp-kpi-val">{S.rains_failed_min}–{S.rains_failed_max} of {S.rains_seasons}</span>
                <span className="rp-kpi-label">seasons per LGA with a false start, a late onset or a long dry spell</span>
              </div>
            ) : (
              <div className="rp-kpi">
                <span className="rp-kpi-val">{S.drought_seasons_min}–{S.drought_seasons_max} of {S.seasons}</span>
                <span className="rp-kpi-label">seasons per LGA below 80% of normal rainfall</span>
              </div>
            )}
          </div>

          <div className="rp-main">
            <div className="rp-mapcol">
              <MapToolbar
                basemap={basemap}
                onBasemap={setBasemap}
                layers={[
                  { id: 'flood', label: 'Flood band', dot: hex(PALETTE.flood.high), on: fill === 'flood' },
                  { id: 'drought', label: 'Drought band', dot: hex(PALETTE.drought.high), on: fill === 'drought' },
                  ...(S.rains_seasons ? [{ id: 'rains', label: 'Failed-rains band', dot: hex(PALETTE.rains.high), on: fill === 'rains' }] : []),
                  ...(data.overlays.map((o) => ({
                    id: o.layer, label: o.label,
                    dot: hex((OVERLAYS.find((x) => x.key === o.layer) ?? OVERLAYS[0]).light), on: Boolean(on[o.layer]),
                  }))),
                ]}
                onToggle={(id) => {
                  // The three bands are one choice — the map colours LGAs by one at a time.
                  if (id === 'flood' || id === 'drought' || id === 'rains') setFill(id);
                  else setOn((s) => ({ ...s, [id]: !s[id] }));
                }}
              />
              <EBMap
                tenant={tenant}
                layers={layers}
                height="560px"
                mapStyle={BASEMAP_STYLE[basemap]}
                ariaLabel={`${stateLabel} by LGA: ${KIND_LABEL[fill].toLowerCase()}`}
                getTooltip={(o) => {
                  const name = (o as { properties?: { lga: string } })?.properties?.lga;
                  const l = name ? byName.get(name) : undefined;
                  if (!l) return null;
                  const f = l.figures;
                  const line = fill === 'flood' ? `${zoneShare(l)} in the 1-in-10-year zone`
                    : fill === 'drought' ? `${f.rain.drought_seasons.length} of ${f.rain.last_year - f.rain.first_year + 1} seasons below 80% of normal`
                    : `${f.rains?.failed_seasons.length ?? '—'} of ${f.rains?.years.length ?? '—'} seasons with failed rains`;
                  return `${l.lga} · ${BAND_LABEL[bandOf(l, fill)]} ${KIND_LABEL[fill].toLowerCase()}\n${line}\nClick for detail`;
                }}
                card={card}
              />
              <div className="rp-legend">
                {(['high', 'moderate', 'low'] as Band[]).map((b) => (
                  <span key={b}><i style={{ background: hex(PALETTE[fill][b]) }} />{BAND_LABEL[b]}</span>
                ))}
                {data.overlays.filter((o) => on[o.layer]).map((o) => (
                  <span key={o.layer}><i style={{ background: hex((OVERLAYS.find((x) => x.key === o.layer) ?? OVERLAYS[0]).light) }} />{o.label}</span>
                ))}
              </div>
              <p className="rp-rule"><b>{KIND_LABEL[fill]} rule.</b> {data.rule[fill]}</p>
            </div>

            <div className="rp-side">
              <div className="rp-side-head">
                {sorted.length} LGAs · sorted by {KIND_LABEL[fill].toLowerCase()}
              </div>
              <div className="rp-list">
                {sorted.map((l) => {
                  const f = l.figures;
                  const fig = fill === 'flood'
                    ? `${zoneShare(l)} in the 1-in-10-yr zone${Object.values(f.flood.mapped ?? {})[0] ? ` · ${pc(Object.values(f.flood.mapped)[0].area_pct)} under water ${Object.values(f.flood.mapped)[0].label}` : ''}`
                    : fill === 'drought'
                      ? `${f.rain.drought_seasons.length} of ${f.rain.last_year - f.rain.first_year + 1} seasons below 80% · normal ${n0(f.rain.normal_mm)} mm (${span(f.rain.season_months)})`
                      : `${f.rains?.failed_seasons.length ?? '—'} of ${f.rains?.years.length ?? '—'} seasons · ${f.rains?.false_starts.length ?? 0} false starts · ${f.rains?.long_dry_spells.length ?? 0} long dry spells`;
                  return (
                    <button key={l.lga} type="button" className={`rp-row ${detail?.lga === l.lga ? 'is-sel' : ''}`}
                      onClick={() => { setSel(l.lga); setCardOpen(true); }}>
                      <span className="rp-row-name">{l.lga}</span>
                      <span className="rp-row-chips">
                        <Chip band={l.band_flood} kind="flood" />
                        <Chip band={l.band_drought} kind="drought" />
                        {l.band_rains !== 'none' && <Chip band={l.band_rains} kind="rains" />}
                      </span>
                      <span className="rp-row-fig">{fig}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          {detail && (
            <div className="rp-detail" aria-live="polite">
              <div className="rp-detail-head">
                <h3>{detail.lga}</h3>
                <Chip band={detail.band_flood} kind="flood" />
                <Chip band={detail.band_drought} kind="drought" />
                {detail.band_rains !== 'none' && <Chip band={detail.band_rains} kind="rains" />}
              </div>
              <p className="rp-plain">{plain(detail).join(' ')}</p>
              <div className="rp-cols">
                <div className="rp-blk">
                  <span className="rp-label">Flood</span>
                  <dl className="rp-kv">
                    {detail.figures.flood.basis === 'land' ? (
                      <>
                        <dt>Land in 1-in-10-year zone</dt><dd>{pc(detail.figures.flood.rp10_area_pct)}</dd>
                        <dt>Land in 1-in-100-year zone</dt><dd>{pc(detail.figures.flood.rp100_area_pct)}</dd>
                        <dt>Farmland mapped</dt><dd>{pc(detail.figures.cropland_pct)} of LGA · band reads land</dd>
                      </>
                    ) : (
                      <>
                        <dt>Farmland in 1-in-10-year zone</dt><dd>{pc(detail.figures.flood.rp10_crop_pct)} · {ha(detail.figures.flood.rp10_crop_ha)}</dd>
                        <dt>Farmland in 1-in-100-year zone</dt><dd>{pc(detail.figures.flood.rp100_crop_pct)} · {ha(detail.figures.flood.rp100_crop_ha)}</dd>
                        <dt>…of it deeper than 1 m</dt><dd>{pc(detail.figures.flood.rp100_deep_crop_pct)} of farmland</dd>
                      </>
                    )}
                    {Object.entries(detail.figures.flood.mapped ?? {}).map(([k, m]) => (
                      <Fragment key={k}>
                        <dt>Water seen {m.label}</dt>
                        <dd>{pc(m.area_pct)} of LGA · {ha(m.crop_ha)} · cloud hid {pc(m.cloud_pct, 0)}</dd>
                      </Fragment>
                    ))}
                  </dl>
                </div>
                <div className="rp-blk">
                  <span className="rp-label">Rainfall season · {span(detail.figures.rain.season_months)}</span>
                  <SeasonChart l={detail} />
                  <dl className="rp-kv">
                    <dt>Normal (1991–2020 median)</dt><dd>{n0(detail.figures.rain.normal_mm)} mm</dd>
                    <dt>Seasons below 80%</dt><dd>{years(detail.figures.rain.drought_seasons)}</dd>
                    {detail.figures.rains?.years.length ? (
                      <>
                        <dt>Rains usually set in</dt><dd>{onsetText(detail.figures.rains.onset_median) ?? '—'}</dd>
                        <dt>False starts</dt><dd>{years(detail.figures.rains.false_starts)}</dd>
                        <dt>Late onsets</dt><dd>{years(detail.figures.rains.late_onsets)}</dd>
                        <dt>Long dry spells</dt><dd>{years(detail.figures.rains.long_dry_spells)}</dd>
                      </>
                    ) : null}
                  </dl>
                </div>
                <div className="rp-blk">
                  <span className="rp-label">Exposure</span>
                  <dl className="rp-kv">
                    <dt>Farmland</dt><dd>{ha(detail.figures.cropland_ha)} · {pc(detail.figures.cropland_pct, 0)} of LGA</dd>
                    {detail.figures.exposure ? (
                      <>
                        <dt>Villages (GRID3)</dt><dd>{n0(detail.figures.exposure.villages)}</dd>
                        <dt>People</dt><dd>{n0(detail.figures.exposure.people)}</dd>
                        <dt>Children under five</dt><dd>{n0(detail.figures.exposure.under5)}</dd>
                      </>
                    ) : null}
                  </dl>
                  <span className="rp-label">On our disaster register</span>
                  {detail.figures.register.length ? (
                    <ul className="rp-reg">
                      {detail.figures.register.map((e, i) => (
                        <li key={i}><span>{e.date} · {e.type}</span>{e.name}</li>
                      ))}
                    </ul>
                  ) : <p className="rp-muted">No cited event recorded for this LGA yet.</p>}
                </div>
              </div>
            </div>
          )}

          <details className="rp-fold">
            <summary>All {lgas.length} LGAs, as in the PDF and CSV</summary>
            <div className="ev-lga-table-wrap rp-table-wrap">
              <table className="ev-lga-table rp-table">
                <thead>
                  <tr>
                    <th>LGA</th><th className="cv-left">Flood</th><th>In the 1-in-10-yr zone</th>
                    <th>Under water {S.mapped[0]?.label ?? ''}</th><th className="cv-left">Drought</th>
                    <th>Seasons below 80%</th><th className="cv-left">Failed rains</th><th>Failed-rain seasons</th>
                    <th>Farmland</th><th>People</th>
                  </tr>
                </thead>
                <tbody>
                  {[...lgas].sort((a, b) => ORDER[a.band_flood] - ORDER[b.band_flood]
                    || (b.figures.flood.rp10_crop_pct ?? 0) - (a.figures.flood.rp10_crop_pct ?? 0)).map((l) => {
                    const f = l.figures;
                    const m = S.mapped[0] ? f.flood.mapped?.[S.mapped[0].key] : undefined;
                    return (
                      <tr key={l.lga} onClick={() => setSel(l.lga)} className={detail?.lga === l.lga ? 'is-sel' : ''}>
                        <td>{l.lga}</td>
                        <td className="cv-left"><Chip band={l.band_flood} /></td>
                        <td>{f.flood.basis === 'land' ? zoneShare(l) : `${zoneShare(l)} · ${ha(f.flood.rp10_crop_ha)}`}</td>
                        <td>{m ? pc(m.area_pct) : '—'}</td>
                        <td className="cv-left"><Chip band={l.band_drought} /></td>
                        <td>{f.rain.drought_seasons.length} of {f.rain.last_year - f.rain.first_year + 1}</td>
                        <td className="cv-left"><Chip band={l.band_rains} /></td>
                        <td>{f.rains?.years.length ? `${f.rains.failed_seasons.length} of ${f.rains.years.length}` : '—'}</td>
                        <td>{ha(f.cropland_ha)}</td>
                        <td>{f.exposure ? n0(f.exposure.people) : '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </details>

          <details className="rp-fold">
            <summary>How we report</summary>
            <ul className="rp-how">
              <li><b>Flood zones are modelled.</b> The JRC/Copernicus GloFAS river flood maps (about 90 m) show where the larger rivers flood in a 1-in-10 and a 1-in-100-year flood. Flash floods and waterlogging are carried by the mapped floods and our disaster register.</li>
              <li><b>Mapped floods are observed.</b> UNOSAT drew them from NOAA VIIRS imagery at 375 m, new water only. Cloud can hide water, so each figure is the least that was under water; we show how much of the LGA cloud covered. UNOSAT lists the maps as not yet field-validated.</li>
              <li><b>Rainfall seasons.</b> CHIRPS v3 monthly rainfall averaged over each LGA. The season is the months that averaged at least 50 mm in 1991–2020; normal is the 1991–2020 median season total; a drought season falls below 80% of it.</li>
              <li><b>Failed rains.</b> CHIRPS v3 daily rainfall (station-blended five-day totals spread across days with NASA IMERG). The rains set in on the first day, from the start of the season, when three days bring at least 20 mm with no dry spell longer than 7 days in the next 30 (as AGRHYMET uses it). A false start is such a rain followed by a longer dry spell; a long dry spell is 10 or more days under 1 mm in the 30–90 days after; a late onset is 20 or more days after the usual date. Rainfall is averaged over the LGA, so a dry spell counts only when nearly the whole LGA stays dry; local dry spells are shorter or missed. Where a state has two rainy seasons (southern Ghana), the season figures count both and the onset and dry spells describe the first.</li>
              <li><b>Farmland and people.</b> ESA WorldCover 2021 cropland, one snapshot: fallow or grazed fields can read as grassland, and farms under trees (cocoa, oil palm) as tree cover. Where less than 5% of an LGA is mapped as farmland, its flood band reads the share of its land instead, and says so. People are the HRSL 30 m population at GRID3 villages (Nigerian states).</li>
              {S.mapped.filter((m) => m.agreement != null).length > 0 && (
                <li><b>Cross-check.</b> The flood model and the satellite maps were made independently. Ranking the LGAs by farmland in the 1-in-10-year zone and by water seen gives a rank agreement of {S.mapped.filter((m) => m.agreement != null).map((m) => `${m.agreement!.toFixed(2)} (${m.label})`).join(' and ')}, where 1.00 would be the same order.</li>
              )}
            </ul>
          </details>

          {isSuperAdmin && (
            <div className="cv-report rp-report">
              <div>
                <div className="fp-tenant-label">Prepared for</div>
                <input className="cv-input" value={client} onChange={(e) => setClient(e.target.value)}
                  placeholder="e.g. NAIC" aria-label="Prepared for" />
              </div>
              <div>
                <div className="fp-tenant-label">Reference</div>
                <input className="cv-input" value={ref} onChange={(e) => setRef(e.target.value)}
                  placeholder={`e.g. NAIC-${tenant.id.toUpperCase()}-RISK-${(through ?? 2025) + 1}`} aria-label="Reference" />
              </div>
              <button type="button" className="fp-refresh-btn" disabled={busy !== null || !client.trim() || !ref.trim()}
                onClick={() => download('pdf')}>
                {busy === 'pdf' ? 'Preparing…' : '⬇ Risk report (PDF)'}
              </button>
              <button type="button" className="fp-refresh-btn" disabled={busy !== null} onClick={() => download('csv')}>
                {busy === 'csv' ? 'Preparing…' : '⬇ All figures (CSV)'}
              </button>
              {dlError && <span className="ev-map-meta" style={{ color: 'var(--alert)' }}>{dlError}</span>}
            </div>
          )}
          <div className="rp-foot">
            Round through the {through} season{data.measured_at ? `, measured ${new Date(data.measured_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}` : ''}. Refreshed once a year before planting; earlier rounds are kept.
          </div>
        </>
      )}
    </div>
  );
}
