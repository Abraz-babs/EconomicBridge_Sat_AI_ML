'use client';

/**
 * CropGuard's season watch — the redesigned view (operator-approved mock,
 * 2026-09-26): this rainy season against the last, LGA by LGA, over the ground
 * both seasons could see; where to send officers first; the patches that
 * stopped growing, each pinned to its nearest village; three seasons per LGA.
 *
 * Copernicus Sentinel-2 greenness on every farmland pixel (farmland = crops +
 * rangeland on the Esri land-cover map). Greenness is a lead for an officer to
 * check, not a diagnosis.
 */

import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { GeoJsonLayer, ScatterplotLayer } from '@deck.gl/layers';

import EBMap from '@/components/map/EBMap';
import HaloCard from '@/components/map/HaloCard';
import MapToolbar from '@/components/map/MapToolbar';
import ModuleSources from '@/components/common/ModuleSources';
import { DirectionsLink, GRID3_CREDIT } from '@/components/common/FieldDirections';
import { BASEMAP_STYLE, fillAlpha, type Basemap } from '@/components/map/basemaps';
import type { Tenant } from '@/data/tenants';
import { useCropHealth, type CropHealthRow } from '@/hooks/useCropHealth';
import { useCropSeason, type CropSeasonLga, type CropSeasonPatch } from '@/hooks/useCropSeason';
import { useLgaBoundaries } from '@/hooks/useLgaBoundaries';

const TZ = 'Africa/Lagos';
const SEASON_RAMP: [number, number, number][] = [
  [230, 220, 170], [169, 196, 111], [79, 138, 69], [31, 90, 46],
];
const RUST: [number, number, number] = [181, 71, 31];
const HEALTH_RGB: Record<string, [number, number, number]> = {
  healthy: [47, 107, 58], moderate: [143, 179, 86], stressed: [213, 154, 42],
  poor: [176, 70, 43], bare: [138, 143, 148],
};

function seasonRgb(pct: number): [number, number, number] {
  const t = Math.max(0, Math.min(1, pct / 90));
  const n = SEASON_RAMP.length - 1;
  const i = Math.min(Math.floor(t * n), n - 1);
  const f = t * n - i;
  const a = SEASON_RAMP[i];
  const b = SEASON_RAMP[i + 1];
  return [0, 1, 2].map((k) => Math.round(a[k] + (b[k] - a[k]) * f)) as [number, number, number];
}

const n0 = (v: number) => Math.round(v).toLocaleString('en-US');
const pct = (v: number | null) => (v == null ? '—' : `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(1)}%`);

function dayLong(d: string): string {
  return new Date(`${d.slice(0, 10)}T12:00:00+01:00`).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'long', timeZone: TZ,
  });
}

function dayShort(d: string): string {
  return new Date(`${d.slice(0, 10)}T12:00:00+01:00`).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', timeZone: TZ,
  });
}

function placeLine(p: CropSeasonPatch): string | null {
  const np = p.nearest_place;
  if (!np) return null;
  const dir = np.direction ? ` ${np.direction}` : '';
  return `${np.distance_km.toFixed(1)} km${dir} of ${np.name}${np.ward ? ` (${np.ward} ward)` : ''}`;
}

type Sel = { kind: 'patch'; i: number } | { kind: 'lga'; lga: string } | null;


export default function SeasonWatch({ tenant, stateLabel }: { tenant: Tenant; stateLabel: string }) {
  const season = useCropSeason(tenant.id);
  const health = useCropHealth(tenant.id);
  const lgasQ = useLgaBoundaries(tenant.id);

  const [basemap, setBasemap] = useState<Basemap>('satellite');
  const [layersOn, setLayersOn] = useState({ season: true, patches: true, health: false });
  const [sel, setSel] = useState<Sel>(null);
  // A selection points into this state's data — drop it when the state changes,
  // or the card would land on an unrelated place in the next state.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSel(null);
  }, [tenant.id]);

  const data = season.data;
  const lgas = useMemo(() => data?.lgas ?? [], [data]);
  const patches = useMemo(() => data?.patches ?? [], [data]);
  const byLga = useMemo(() => new Map(lgas.map((r) => [r.lga, r])), [lgas]);
  const healthRows = useMemo(() => health.data ?? [], [health.data]);
  const healthBy = useMemo(() => new Map(healthRows.map((h) => [h.lga, h])), [healthRows]);
  const y = data?.season_year ?? null;
  const prev = data?.previous_year ?? null;
  const years = data?.years ?? [];
  const lastPass = healthRows.reduce<string | null>(
    (m, h) => (h.ndvi_date && (!m || h.ndvi_date > m) ? h.ndvi_date : m), null,
  );

  const alpha = fillAlpha(basemap);
  const layers = useMemo(() => {
    const out: unknown[] = [];
    if (layersOn.season && lgasQ.data) {
      out.push(new GeoJsonLayer({
        id: 'cg-season',
        data: lgasQ.data as never,
        filled: true,
        stroked: true,
        pickable: true,
        getFillColor: (f: { properties: { lga: string } }) => {
          const v = byLga.get(f.properties.lga)?.like_for_like_pct;
          return v == null ? [140, 140, 140, 40] : [...seasonRgb(v), alpha];
        },
        getLineColor: [255, 255, 255, 170],
        lineWidthMinPixels: 1,
        onClick: (info: { object?: { properties: { lga: string } } }) => {
          const lga = info.object?.properties.lga;
          if (lga) setSel({ kind: 'lga', lga });
        },
        updateTriggers: { getFillColor: [byLga, alpha] },
      }));
    }
    if (layersOn.health && healthRows.length) {
      out.push(new ScatterplotLayer({
        id: 'cg-health',
        data: healthRows,
        getPosition: (h: CropHealthRow) => [h.lon, h.lat],
        getFillColor: (h: CropHealthRow) => [...(HEALTH_RGB[h.health] ?? [138, 143, 148]), 255],
        getLineColor: [255, 255, 255, 240],
        stroked: true,
        lineWidthMinPixels: 2,
        getRadius: (h: CropHealthRow) => (sel?.kind === 'lga' && sel.lga === h.lga ? 10 : 7),
        radiusUnits: 'pixels',
        pickable: true,
        onClick: (info: { object?: CropHealthRow }) => {
          if (info.object) setSel({ kind: 'lga', lga: info.object.lga });
        },
        updateTriggers: { getRadius: [sel] },
      }));
    }
    if (layersOn.patches && patches.length) {
      const pins = patches.map((p, i) => ({ p, i })).filter((x) => x.p.location);
      out.push(new ScatterplotLayer({
        id: 'cg-patch-halo',
        data: pins,
        getPosition: (x: { p: CropSeasonPatch }) => [x.p.location!.lon, x.p.location!.lat],
        getFillColor: (x: { i: number }) => [...RUST, sel?.kind === 'patch' && sel.i === x.i ? 110 : 55],
        getRadius: (x: { i: number }) => (sel?.kind === 'patch' && sel.i === x.i ? 20 : 13),
        radiusUnits: 'pixels',
        pickable: false,
        updateTriggers: { getFillColor: [sel], getRadius: [sel] },
      }));
      out.push(new ScatterplotLayer({
        id: 'cg-patch-core',
        data: pins,
        getPosition: (x: { p: CropSeasonPatch }) => [x.p.location!.lon, x.p.location!.lat],
        getFillColor: [...RUST, 255],
        getLineColor: [255, 255, 255, 245],
        stroked: true,
        lineWidthMinPixels: 2,
        getRadius: 6,
        radiusUnits: 'pixels',
        pickable: true,
        onClick: (info: { object?: { i: number } }) => {
          if (info.object) setSel({ kind: 'patch', i: info.object.i });
        },
      }));
    }
    return out;
  }, [layersOn, lgasQ.data, byLga, alpha, healthRows, patches, sel]);

  // The pinned card for whatever is selected.
  let card: { lng: number; lat: number; node: ReactNode } | null = null;
  if (sel?.kind === 'patch' && patches[sel.i]?.location) {
    const p = patches[sel.i];
    card = {
      lng: p.location!.lon, lat: p.location!.lat,
      node: <PatchCard p={p} lga={p.lga ? byLga.get(p.lga) : undefined} year={y} onClose={() => setSel(null)} />,
    };
  } else if (sel?.kind === 'lga') {
    const row = byLga.get(sel.lga);
    const h = healthBy.get(sel.lga);
    const at = h ? { lng: h.lon, lat: h.lat } : row?.location ? { lng: row.location.lon, lat: row.location.lat } : null;
    if (at && (row || h)) {
      card = {
        ...at,
        node: <LgaCard lga={sel.lga} row={row} h={h} years={years} prev={prev} onClose={() => setSel(null)} />,
      };
    }
  }

  const comparable = lgas.filter((r) => r.like_for_like_pct != null);
  const behind = comparable.filter((r) => (r.like_for_like_pct ?? 0) < 0);
  const seen = lgas.map((r) => r.seen_pct).filter((v): v is number => v != null);
  const lookFirst = comparable.slice(0, 5);
  const healthCounts = healthRows.reduce<Record<string, number>>((m, h) => ({ ...m, [h.health]: (m[h.health] ?? 0) + 1 }), {});
  // A row exists once the sweep visited an LGA, but a reading is real only when
  // NDVI came back — so coverage is stated, not implied (as the old crop-health panel did).
  const withReading = healthRows.filter((h) => h.ndvi != null).length;

  return (
    <section className="swt" aria-labelledby="swt-title">
      <div className="swt-head">
        <div className="swt-head-main">
          <span className="swt-eyebrow">
            CropGuard · {stateLabel}{y ? ` · ${y} rains` : ''}{data?.window_end ? ` to ${dayLong(data.window_end)}` : ''}
          </span>
          <h2 id="swt-title" className="swt-h1">
            {season.isLoading ? 'Reading the season…'
              : !comparable.length ? <>Season measurements for {stateLabel} are not available yet.</>
                : behind.length === 0
                  ? <>A greener season across {stateLabel} — all {comparable.length} LGAs are ahead of last year on the same ground.</>
                  : <>{behind.length} of {comparable.length} LGAs are behind last season on the same ground.</>}
          </h2>
          <p className="swt-sub">
            Every farmland pixel from Copernicus Sentinel-2: this season&rsquo;s peak greenness
            against the {prev ?? 'previous'} rains, over the ground both seasons could see through cloud.
          </p>
          <ModuleSources sources={[
            { name: 'Copernicus Sentinel-2', role: 'crop health and season change, every farmland pixel' },
            { name: 'Copernicus Sentinel-1', role: 'radar, Farm Check' },
            { name: 'Esri land cover (2023)', role: 'which ground is farmland' },
            { name: 'GRID3', role: 'nearest village names' },
            { name: 'FEWS NET · NBS', role: 'market prices, where published' },
            { name: 'EconomicBridge leaf model', role: 'leaf-photo check, tested on lab images' },
          ]} />
        </div>
        <span className="swt-chip">LIVE · SENTINEL-2{lastPass ? ` · LAST PASS ${dayShort(lastPass).toUpperCase()}` : ''}</span>
      </div>

      {season.isError && <div className="fp-alert-error">Could not load the season: {season.error?.message ?? 'unknown'}</div>}

      {comparable.length > 0 && data && (
        <div className="swt-kpis">
          <div className="swt-kpi">
            <span className="swt-kpi-val swt-kpi-val--leaf">{(data.farmland_ha / 1e6).toFixed(2)}M ha</span>
            <span className="swt-kpi-label">of farmland greened this season — crops and rangeland</span>
            <span className="swt-kpi-src">Sentinel-2 · Esri land cover (2023)</span>
          </div>
          <div className="swt-kpi">
            <span className="swt-kpi-val">{pct(data.like_for_like_pct)}</span>
            <span className="swt-kpi-label">vs the {prev} rains, like-for-like, statewide</span>
            <span className="swt-kpi-src">Same ground, both seasons</span>
          </div>
          <div className="swt-kpi">
            <span className="swt-kpi-val">{n0(data.stopped_growing)}</span>
            <span className="swt-kpi-label">patches that stopped growing — each pinned to the nearest village</span>
            <span className="swt-kpi-src">{data.stopped_rangeland} rangeland · {data.stopped_crops} crops</span>
          </div>
          <div className="swt-kpi">
            <span className="swt-kpi-val">{seen.length ? `${Math.min(...seen)}–${Math.max(...seen)}%` : '—'}</span>
            <span className="swt-kpi-label">of each LGA seen clearly enough to compare</span>
            <span className="swt-kpi-src">Cloud gaps shown, never filled</span>
          </div>
        </div>
      )}

      <div className="swt-main">
        <div className="swt-mapcol">
          <MapToolbar
            basemap={basemap}
            onBasemap={setBasemap}
            layers={[
              { id: 'season', label: prev ? `Season change vs ${prev}` : 'Season change', dot: '#4f8a45', on: layersOn.season },
              { id: 'patches', label: 'Stopped growing', dot: '#b5471f', on: layersOn.patches },
              { id: 'health', label: 'Crop health now', dot: '#8fb356', on: layersOn.health },
            ]}
            onToggle={(id) => setLayersOn((s) => ({ ...s, [id]: !s[id as keyof typeof s] }))}
          />
          <EBMap
            tenant={tenant}
            layers={layers}
            height="600px"
            zoom={6.6}
            mapStyle={BASEMAP_STYLE[basemap]}
            ariaLabel={`Season change across ${stateLabel}`}
            getTooltip={(o) => {
              const f = o as { properties?: { lga: string }; p?: CropSeasonPatch; lga?: string; ndvi?: number };
              if (f?.properties?.lga) {
                const r = byLga.get(f.properties.lga);
                return `${f.properties.lga} · ${pct(r?.like_for_like_pct ?? null)} vs ${prev}\nClick for detail`;
              }
              if (f?.p) return `${f.p.lga} · stopped growing · ${f.p.area_ha?.toFixed(1)} ha\nClick for detail`;
              if (f?.lga && f.ndvi != null) return `${f.lga} · NDVI ${f.ndvi.toFixed(2)}\nClick for detail`;
              return null;
            }}
            card={card}
          />
          <div className="swt-legend">
            <span><i className="swt-ramp" /> +5% → +89% vs {prev}, same ground</span>
            <span><i className="swt-dot swt-dot--rust" /> Stopped growing — click for detail</span>
            {layersOn.health && (
              <span>
                Crop health: {Object.entries(healthCounts).map(([k, v]) => `${k.replace('_', ' ')} ${v}`).join(' · ')}
                {' '}— {withReading} of {healthRows.length} LGAs with a current reading
              </span>
            )}
          </div>
        </div>

        <div className="swt-side">
          <section className="swt-block">
            <h3 className="swt-h2">Where to send officers first</h3>
            <p className="swt-note">The LGAs gaining least on last season, with the patches inside them that stopped growing.</p>
            {lookFirst.map((r) => {
              const h = healthBy.get(r.lga);
              return (
                <button key={r.lga} type="button" className="swt-look" onClick={() => setSel({ kind: 'lga', lga: r.lga })}>
                  <span className="swt-look-lga">{r.lga}</span>
                  <span className={`swt-look-pct ${(r.like_for_like_pct ?? 0) < 8 ? 'is-low' : ''}`}>{pct(r.like_for_like_pct)}</span>
                  <span className="swt-look-body">
                    {r.stopped_growing === 0 ? 'No patch stopped growing'
                      : `${r.stopped_growing} patch${r.stopped_growing === 1 ? '' : 'es'} stopped growing`}
                    {y && r.farmland_ha[String(y)] != null ? ` · ${n0(r.farmland_ha[String(y)])} ha farmland` : ''}
                  </span>
                  <span className="swt-look-ndvi">{h?.ndvi != null ? `NDVI ${h.ndvi.toFixed(2)} · ${h.ndvi_date ? dayShort(h.ndvi_date) : ''}` : ''}</span>
                </button>
              );
            })}
          </section>
          <section className="swt-block">
            <h3 className="swt-h2">Patches that stopped growing</h3>
            {patches.slice(0, 4).map((p, i) => (
              <div key={`${p.lga}-${i}`} className="swt-patch">
                <div className="swt-patch-top">
                  <button type="button" className="swt-patch-title" onClick={() => setSel({ kind: 'patch', i })}>
                    {p.lga} · {p.kind === 'crops' ? 'Crops' : p.kind === 'rangeland' ? 'Rangeland' : 'Farmland'}, {p.area_ha?.toFixed(1)} ha
                  </button>
                  <span className="swt-tag">STOPPED GROWING</span>
                </div>
                <span className="swt-patch-body">
                  Green in the earlier rains, bare in {y} — greenness {p.peak_before?.toFixed(2)} → {p.peak_now?.toFixed(2)}.
                  {placeLine(p) ? ` ${placeLine(p)}.` : ''}
                </span>
                {p.location && (
                  <span className="swt-patch-meta">
                    {p.location.lat.toFixed(4)}°N {p.location.lon.toFixed(4)}°E · <DirectionsLink lat={p.location.lat} lon={p.location.lon} />
                  </span>
                )}
              </div>
            ))}
            {patches.some((p) => p.nearest_place) && <span className="swt-credit">{GRID3_CREDIT}</span>}
          </section>
        </div>
      </div>

      {years.length > 1 && (
        <section className="swt-block">
          <div className="swt-mult-head">
            <h3 className="swt-h2">{years.length === 3 ? 'Three' : years.length} rainy seasons, same LGA</h3>
            <span className="swt-kpi-src">Farmland that greened each season · {years.join(' · ')}</span>
          </div>
          <div className="swt-mult">
            {[...lgas].sort((a, b) => a.lga.localeCompare(b.lga)).map((r) => {
              const vals = years.map((yy) => r.farmland_ha[String(yy)] ?? 0);
              const mx = Math.max(1, ...vals);
              return (
                <button key={r.lga} type="button" className="swt-mult-cell" onClick={() => setSel({ kind: 'lga', lga: r.lga })}>
                  <span className="swt-mult-top"><b>{r.lga}</b><span>{pct(r.like_for_like_pct)}</span></span>
                  <span className="swt-mult-bars" aria-label={`${r.lga}: ${years.map((yy, k) => `${yy} ${n0(vals[k])} ha`).join(', ')}`}>
                    {vals.map((v, k) => (
                      <span key={years[k]} className="swt-mult-bar-wrap">
                        <span className={`swt-mult-bar ${k === vals.length - 1 ? 'is-now' : ''}`} style={{ height: `${Math.max(4, Math.round((v / mx) * 56))}px` }} />
                        <span className="swt-mult-year">’{String(years[k]).slice(2)}</span>
                      </span>
                    ))}
                  </span>
                </button>
              );
            })}
          </div>
        </section>
      )}
    </section>
  );
}


function PatchCard(props: { p: CropSeasonPatch; lga?: CropSeasonLga; year: number | null; onClose: () => void }) {
  const { p, lga, year, onClose } = props;
  const np = p.nearest_place;
  return (
    <HaloCard
      title={`${p.lga ?? ''} · ${p.kind === 'crops' ? 'Crops' : p.kind === 'rangeland' ? 'Rangeland' : 'Farmland'} stopped growing`}
      big={p.area_ha != null ? `${p.area_ha.toFixed(1)} ha` : undefined}
      rows={[
        { k: 'Peak greenness', v: `${p.peak_before?.toFixed(2) ?? '—'} → ${p.peak_now?.toFixed(2) ?? '—'} (earlier rains → ${year ?? 'now'})` },
        ...(np ? [{ k: 'Nearest village', v: `${np.name}${np.ward ? `, ${np.ward} ward` : ''} · ${np.distance_km.toFixed(1)} km` }] : []),
        ...(lga ? [{ k: 'LGA this season', v: `${pct(lga.like_for_like_pct)} vs last season, like-for-like` }] : []),
        ...(p.detected_at ? [{ k: 'Detected', v: `${dayShort(p.detected_at)} · Sentinel-2, every pixel` }] : []),
        ...(p.location ? [{ k: 'Location', v: <>{p.location.lat.toFixed(4)}°N {p.location.lon.toFixed(4)}°E · <DirectionsLink lat={p.location.lat} lon={p.location.lon} /></> }] : []),
      ]}
      why="Green through the earlier rains, bare through this one. It may have been cleared, built on or left fallow — an officer should look. Detections like this were right 64% of the time on a random sample."
      onClose={onClose}
    />
  );
}


function LgaCard(props: {
  lga: string; row?: CropSeasonLga; h?: CropHealthRow; years: number[]; prev: number | null; onClose: () => void;
}) {
  const { lga, row, h, years, prev, onClose } = props;
  return (
    <HaloCard
      title={`${lga} · season and crop health`}
      big={row?.like_for_like_pct != null ? `${pct(row.like_for_like_pct)} vs ${prev}` : h?.ndvi != null ? `NDVI ${h.ndvi.toFixed(2)}` : undefined}
      rows={[
        ...(row ? [{ k: 'Farmland greened', v: years.map((yy) => `${yy} ${n0(row.farmland_ha[String(yy)] ?? 0)}`).join(' · ') + ' ha' }] : []),
        ...(row?.seen_pct != null ? [{ k: 'Seen through cloud', v: `${row.seen_pct}% of the LGA` }] : []),
        ...(row ? [{ k: 'Stopped growing', v: `${row.stopped_growing} patch${row.stopped_growing === 1 ? '' : 'es'}` }] : []),
        ...(h ? [{ k: 'Crop health now', v: `${h.health.replace('_', ' ')} · NDVI ${h.ndvi?.toFixed(2) ?? '—'}${h.ndvi_date ? ` · pass ${dayShort(h.ndvi_date)}` : ''}` }] : []),
      ]}
      why={`${h?.verdict ? `${h.verdict} ` : ''}A reading for the whole LGA, not one field — use Farm Check below for a single field.`}
      onClose={onClose}
    />
  );
}
