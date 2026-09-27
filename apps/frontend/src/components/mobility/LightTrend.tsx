'use client';

/**
 * Mobility Compass — where activity is growing or fading (operator-approved
 * mock, 2026-09-27). NASA Black Marble yearly night light since 2012 by LGA
 * and village, the people who live there, and what staple food costs.
 *
 * A change is shown only when both of NASA's yearly composites agree; single
 * years are noisy, so the latest three years are compared with 2012-14; a
 * place that started with only faint light gets no percentage. Light is
 * activity, not income — the page says so. Displaced-people counts are IOM's
 * and licensed non-commercially, so the page links to them instead.
 */

import { useMemo, useState, type ReactNode } from 'react';
import { GeoJsonLayer, ScatterplotLayer } from '@deck.gl/layers';

import EBMap from '@/components/map/EBMap';
import HaloCard from '@/components/map/HaloCard';
import MapToolbar from '@/components/map/MapToolbar';
import ModuleSources from '@/components/common/ModuleSources';
import { DirectionsLink, GRID3_CREDIT } from '@/components/common/FieldDirections';
import { BASEMAP_STYLE, fillAlpha, type Basemap } from '@/components/map/basemaps';
import type { Tenant } from '@/data/tenants';
import { useLgaBoundaries } from '@/hooks/useLgaBoundaries';
import { useLightTrend, type LightTrendLga, type StapleSeries, type TrendVillage } from '@/hooks/useLightTrend';
import { useVillageLight, type VillagePoint } from '@/hooks/useVillageLight';

const IOM_DTM_NIGERIA = 'https://dtm.iom.int/nigeria';
const INDIGO: [number, number, number] = [47, 58, 138];
const MID: [number, number, number] = [230, 231, 234];
const UP: [number, number, number] = [217, 154, 30];
const UP2: [number, number, number] = [138, 90, 0];
const MIXED: [number, number, number] = [160, 164, 170];
const AMBER_TXT = '#b07a0e';
const INDIGO_TXT = '#2f3a8a';
const MUTED_TXT = '#56616b';
const CROPS: Record<string, string> = {
  maize: 'Maize', sorghum: 'Sorghum', millet: 'Millet', rice: 'Rice (local)', cowpea: 'Cowpea',
};

const n0 = (v: number | null | undefined) => (v == null ? '—' : Math.round(v).toLocaleString('en-US'));
const signed = (v: number) => `${v >= 0 ? '+' : '−'}${Math.abs(Math.round(v)).toLocaleString('en-US')}%`;
/** A light change: a percentage, or a multiple once light has tripled (“+1390%” reads as “15×”). */
const lightChange = (pct: number) => (pct >= 200 ? `${Math.round(1 + pct / 100)}×` : signed(pct));
const people = (v: number) => (v >= 1e6 ? `${(v / 1e6).toFixed(2)} million` : n0(v));

function mix(a: number[], b: number[], t: number): [number, number, number] {
  return [0, 1, 2].map((k) => Math.round(a[k] + (b[k] - a[k]) * t)) as [number, number, number];
}

/** Diverging colour: -1 halved (indigo) … 0 same … +1 doubled (amber) … +1.5 (deep amber). */
function lgaRgb(g: LightTrendLga): [number, number, number] {
  if (g.category === 'mixed') return MIXED;
  if (g.category === 'still_dark') return MID;
  if (g.category === 'new_light') return mix(UP, UP2, 0.6);
  const t = Math.max(-1, Math.min(1.5, Math.log2(Math.max(0.05, 1 + (g.change_pct ?? 0) / 100))));
  if (t < 0) return mix(MID, INDIGO, -t);
  if (t <= 1) return mix(MID, UP, t);
  return mix(UP, UP2, (t - 1) / 0.5);
}

function changeText(g: LightTrendLga): string {
  switch (g.category) {
    case 'mixed': return 'mixed';
    case 'new_light': return 'new light';
    case 'still_dark': return 'still dark';
    default: return g.change_pct == null ? '—' : lightChange(g.change_pct);
  }
}

function changeColour(g: LightTrendLga): string {
  if (g.category === 'dimmer') return INDIGO_TXT;
  if (g.category === 'brighter' || g.category === 'new_light') return AMBER_TXT;
  return MUTED_TXT;
}

function Spark({ values, w, h, colour, faint }: {
  values: (number | null)[]; w: number; h: number; colour: string; faint?: (number | null)[];
}) {
  const path = (vals: (number | null)[], max: number) => vals
    .map((v, i) => `${i === 0 ? 'M' : 'L'}${(2 + (i * (w - 4)) / Math.max(1, vals.length - 1)).toFixed(1)},${(h - 3 - ((v ?? 0) / max) * (h - 6)).toFixed(1)}`)
    .join(' ');
  const max = Math.max(1e-9, ...values.map((v) => v ?? 0), ...(faint ?? []).map((v) => v ?? 0));
  const last = values.length - 1;
  const lx = 2 + (last * (w - 4)) / Math.max(1, last);
  const ly = h - 3 - ((values[last] ?? 0) / max) * (h - 6);
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true" className="mcx-spark">
      {faint && <path d={path(faint, max)} fill="none" stroke={colour} strokeOpacity={0.3} strokeWidth={1.4} />}
      <path d={path(values, max)} fill="none" stroke={colour} strokeWidth={1.7} />
      <circle cx={lx} cy={ly} r={2.6} fill={colour} />
    </svg>
  );
}

function monthLabel(iso: string): string {
  return new Date(`${iso.slice(0, 10)}T12:00:00Z`).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' });
}

function possessive(stateLabel: string): string {
  if (/capital territory/i.test(stateLabel)) return "the FCT's";
  return `${stateLabel.replace(/ State$/, '')}'s`;
}

type Sel = { kind: 'lga'; lga: string } | { kind: 'village'; list: 'gone' | 'new'; i: number } | null;


export default function LightTrend({ tenant, stateLabel }: { tenant: Tenant; stateLabel: string }) {
  const trend = useLightTrend(tenant.id);
  const lgasQ = useLgaBoundaries(tenant.id);
  const [basemap, setBasemap] = useState<Basemap>('light');
  const [layersOn, setLayersOn] = useState({ change: true, gone: true, fresh: false, villages: false });
  const villageQ = useVillageLight(layersOn.villages ? tenant.id : '');
  const [sel, setSel] = useState<Sel>(null);
  const [now] = useState(() => Date.now());

  const data = trend.data;
  const lgas = useMemo(() => data?.lgas ?? [], [data]);
  const byLga = useMemo(() => new Map(lgas.map((g) => [g.lga, g])), [lgas]);
  const gone = useMemo(() => data?.villages_gone_dark ?? [], [data]);
  const fresh = useMemo(() => data?.villages_newly_lit ?? [], [data]);
  const villagePts = useMemo(() => villageQ.data?.points ?? [], [villageQ.data]);
  const goneI = useMemo(() => gone.map((v, i) => ({ v, i })), [gone]);
  const freshI = useMemo(() => fresh.map((v, i) => ({ v, i })), [fresh]);
  const first = data?.first_year ?? null;
  const last = data?.last_year ?? null;
  const span = first && last ? `${first}–${String(first + 2).slice(2)} to ${last - 2}–${String(last).slice(2)}` : '';
  const alpha = fillAlpha(basemap);
  const dark = basemap !== 'light';

  const selLga = sel?.kind === 'lga' ? sel.lga : null;
  const selVil = sel?.kind === 'village' ? `${sel.list}-${sel.i}` : null;

  const layers = useMemo(() => {
    const out: unknown[] = [];
    if (layersOn.change && lgasQ.data) {
      out.push(new GeoJsonLayer({
        id: 'mcx-change',
        data: lgasQ.data as never,
        filled: true,
        stroked: true,
        pickable: true,
        getFillColor: (f: { properties: { lga: string } }) => {
          const g = byLga.get(f.properties.lga);
          return g ? [...lgaRgb(g), alpha] : [140, 140, 140, 30];
        },
        getLineColor: (f: { properties: { lga: string } }) =>
          (f.properties.lga === selLga ? [28, 34, 40, 255] : [255, 255, 255, 170]),
        getLineWidth: (f: { properties: { lga: string } }) => (f.properties.lga === selLga ? 3 : 1),
        lineWidthUnits: 'pixels',
        onClick: (info: { object?: { properties: { lga: string } } }) => {
          const lga = info.object?.properties.lga;
          if (lga && byLga.has(lga)) setSel({ kind: 'lga', lga });
        },
        updateTriggers: { getFillColor: [byLga, alpha], getLineColor: [selLga], getLineWidth: [selLga] },
      }));
    }
    if (layersOn.villages && villagePts.length) {
      out.push(new ScatterplotLayer({
        id: 'mcx-villages',
        data: villagePts,
        getPosition: (v: VillagePoint) => [v[0], v[1]],
        // 0 unlit · 1 dim · 2 lit · 3 unknown
        getFillColor: (v: VillagePoint) => (v[2] === 2 ? [255, 196, 102, 235] : v[2] === 1 ? [255, 196, 102, 150]
          : dark ? [150, 160, 172, 70] : [60, 68, 80, 55]),
        getRadius: (v: VillagePoint) => (v[2] === 2 ? 3 : v[2] === 1 ? 2.2 : 1.3),
        radiusUnits: 'pixels',
        pickable: false,
        updateTriggers: { getFillColor: [dark] },
      }));
    }
    const pins = (id: string, list: 'gone' | 'new', rows: { v: TrendVillage; i: number }[], rgb: [number, number, number]) => {
      out.push(new ScatterplotLayer({
        id: `${id}-halo`,
        data: rows,
        getPosition: (x: { v: TrendVillage }) => [x.v.location.lon, x.v.location.lat],
        getFillColor: (x: { i: number }): [number, number, number, number] => [rgb[0], rgb[1], rgb[2], selVil === `${list}-${x.i}` ? 100 : 50],
        getRadius: (x: { i: number }) => (selVil === `${list}-${x.i}` ? 19 : 12),
        radiusUnits: 'pixels',
        pickable: false,
        updateTriggers: { getFillColor: [selVil], getRadius: [selVil] },
      }));
      out.push(new ScatterplotLayer({
        id: `${id}-core`,
        data: rows,
        getPosition: (x: { v: TrendVillage }) => [x.v.location.lon, x.v.location.lat],
        getFillColor: [rgb[0], rgb[1], rgb[2], 255],
        getLineColor: [255, 255, 255, 245],
        stroked: true,
        lineWidthMinPixels: 2,
        getRadius: 6,
        radiusUnits: 'pixels',
        pickable: true,
        onClick: (info: { object?: { i: number } }) => {
          if (info.object) setSel({ kind: 'village', list, i: info.object.i });
        },
      }));
    };
    if (layersOn.gone && goneI.length) pins('mcx-gone', 'gone', goneI, INDIGO);
    if (layersOn.fresh && freshI.length) pins('mcx-new', 'new', freshI, UP);
    return out;
  }, [layersOn, lgasQ.data, byLga, alpha, selLga, villagePts, dark, goneI, freshI, selVil]);

  // The pinned card for whatever is selected.
  let card: { lng: number; lat: number; node: ReactNode } | null = null;
  if (sel?.kind === 'lga') {
    const g = byLga.get(sel.lga);
    if (g?.location) {
      card = { lng: g.location.lon, lat: g.location.lat, node: <LgaCard g={g} span={span} onClose={() => setSel(null)} /> };
    }
  } else if (sel?.kind === 'village') {
    const v = (sel.list === 'gone' ? gone : fresh)[sel.i];
    if (v) {
      card = {
        lng: v.location.lon, lat: v.location.lat,
        node: <VillageCard v={v} kind={sel.list} first={first} onClose={() => setSel(null)} />,
      };
    }
  }

  const worst = lgas.find((g) => g.category === 'dimmer') ?? null;
  const best = [...lgas].filter((g) => g.category === 'brighter')
    .sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0))[0] ?? null;
  const rice = data?.prices.find((p) => p.crop === 'rice');
  const maize = data?.prices.find((p) => p.crop === 'maize');
  const pc = (s?: StapleSeries) => (s && s.points.length > 1
    ? 100 * (s.points[s.points.length - 1].price_ngn_per_kg / s.points[0].price_ngn_per_kg - 1) : null);
  const lastPrice = data?.prices.reduce<string | null>((m, s) => {
    const d = s.points[s.points.length - 1]?.month;
    return d && (!m || d > m) ? d : m;
  }, null) ?? null;
  const pricesStale = lastPrice ? (now - new Date(lastPrice).getTime()) / 86400000 > 200 : false;

  let headline: ReactNode = 'Reading the night-light record…';
  if (data && !data.available) headline = data.reason ?? `Night-light trends for ${stateLabel} are not measured yet.`;
  else if (data) {
    const nL = lgas.length;
    const out = worst && (worst.change_pct ?? 0) <= -80 ? ` In ${worst.lga}, the lights have almost gone out.` : '';
    headline = data.dimmer >= data.brighter
      ? `${data.dimmer} of ${possessive(stateLabel)} ${nL} LGAs are darker at night than a decade ago.${out}`
      : `${data.brighter} of ${possessive(stateLabel)} ${nL} LGAs are brighter at night than a decade ago${
        out ? ` — but in ${worst!.lga}, the lights have almost gone out.` : data.dimmer ? `; ${data.dimmer} are darker.` : '.'}`;
  }

  return (
    <section className="mcx" aria-labelledby="mcx-title">
      <div className="mcx-head">
        <div className="mcx-head-main">
          <span className="mcx-eyebrow">
            Mobility Compass · {stateLabel}{first && last ? ` · Night light ${first}–${last}` : ''}
          </span>
          <h2 id="mcx-title" className="mcx-h1">{headline}</h2>
          <p className="mcx-sub">
            Where towns and markets are growing and where they are fading, from the light NASA&rsquo;s
            satellites see at night every year since 2012 — with the people who live there and what food costs.
          </p>
          <ModuleSources sources={[
            { name: 'NASA VIIRS Black Marble', role: 'light at night, every year since 2012' },
            { name: 'Meta & CIESIN HRSL', role: 'people' },
            { name: 'GRID3', role: 'village names' },
            { name: 'FEWS NET · NBS', role: 'market prices, where published' },
          ]} />
        </div>
        <span className="mcx-chip">NASA BLACK MARBLE · YEARLY{first && last ? ` · ${first}–${last}` : ''}</span>
      </div>

      {trend.isError && <div className="fp-alert-error">Could not load the night-light record: {trend.error?.message ?? 'unknown'}</div>}

      {data?.available && (
        <div className="mcx-kpis">
          {worst ? (
            <div className="mcx-kpi">
              <span className="mcx-kpi-val mcx-kpi-val--indigo">{signed(worst.change_pct ?? 0)}</span>
              <span className="mcx-kpi-label">{worst.lga}&rsquo;s light at night, {span}</span>
              <span className="mcx-kpi-src">NASA Black Marble · both composites agree</span>
            </div>
          ) : best && (
            <div className="mcx-kpi">
              <span className="mcx-kpi-val mcx-kpi-val--amber">{lightChange(best.change_pct ?? 0)}</span>
              <span className="mcx-kpi-label">{best.lga}&rsquo;s light at night, {span}</span>
              <span className="mcx-kpi-src">NASA Black Marble · both composites agree</span>
            </div>
          )}
          <div className="mcx-kpi">
            <span className="mcx-kpi-val">{data.dimmer} of {lgas.length}</span>
            <span className="mcx-kpi-label">
              LGAs dimmer than in {first}–{String((first ?? 0) + 2).slice(2)}
              {data.dimmer ? ` — ${people(data.people_in_dimmer)} people live in them` : ''}; {data.brighter} brighter, {data.mixed} unclear
            </span>
            <span className="mcx-kpi-src">Meta &amp; CIESIN population · three-year averages</span>
          </div>
          <div className="mcx-kpi">
            <span className="mcx-kpi-val">{n0(data.gone_dark)}</span>
            <span className="mcx-kpi-label">
              villages gone dark — {n0(data.gone_dark_people)} people on the population map; {n0(data.newly_lit)} newly lit
            </span>
            <span className="mcx-kpi-src">Both NASA composites agree</span>
          </div>
          {rice && pc(rice) != null ? (
            <div className="mcx-kpi">
              <span className="mcx-kpi-val">{signed(pc(rice)!)}</span>
              <span className="mcx-kpi-label">
                price of local rice, {monthLabel(rice.points[0].month)} to {monthLabel(rice.points[rice.points.length - 1].month)}
                {maize && pc(maize) != null ? ` — maize ${signed(pc(maize)!)}` : ''}
              </span>
              <span className="mcx-kpi-src">{rice.source.startsWith('fews') ? 'FEWS NET market prices' : 'NBS zone prices'}</span>
            </div>
          ) : (
            <div className="mcx-kpi">
              <span className="mcx-kpi-val">—</span>
              <span className="mcx-kpi-label">No staple prices published for {stateLabel} yet</span>
              <span className="mcx-kpi-src">FEWS NET · NBS</span>
            </div>
          )}
        </div>
      )}

      {data?.available && (
        <div className="mcx-main">
          <div className="mcx-mapcol">
            <MapToolbar
              basemap={basemap}
              onBasemap={setBasemap}
              layers={[
                { id: 'change', label: 'Light change by LGA', dot: '#d99a1e', on: layersOn.change },
                { id: 'gone', label: 'Gone dark', dot: '#2f3a8a', on: layersOn.gone },
                { id: 'fresh', label: 'Newly lit', dot: '#d99a1e', on: layersOn.fresh },
                { id: 'villages', label: 'Villages lit now', dot: '#ffc466', on: layersOn.villages },
              ]}
              onToggle={(id) => setLayersOn((s) => ({ ...s, [id]: !s[id as keyof typeof s] }))}
            />
            <EBMap
              tenant={tenant}
              layers={layers}
              height="600px"
              zoom={6.8}
              mapStyle={BASEMAP_STYLE[basemap]}
              ariaLabel={`${stateLabel}: change in light at night by LGA, ${span}`}
              getTooltip={(o) => {
                const f = o as { properties?: { lga: string }; v?: TrendVillage };
                if (f?.v) return `${f.v.name} · ${f.v.lga ?? ''}\n${n0(f.v.people)} people · click for detail`;
                if (f?.properties?.lga) {
                  const g = byLga.get(f.properties.lga);
                  return g ? `${g.lga} · ${changeText(g)} since ${first}–${String((first ?? 0) + 2).slice(2)}\nClick for detail` : null;
                }
                return null;
              }}
              card={card}
            />
            <div className="mcx-legend">
              <span><i className="mcx-ramp" /> dimmer → brighter since {first}–{String((first ?? 0) + 2).slice(2)}</span>
              <span><i className="mcx-sq" /> NASA composites disagree</span>
              <span><i className="mcx-dot mcx-dot--indigo" /> Gone dark</span>
              {layersOn.fresh && <span><i className="mcx-dot mcx-dot--amber" /> Newly lit</span>}
            </div>
          </div>

          <div className="mcx-side">
            <h3 className="mcx-h2">Where the lights changed</h3>
            <p className="mcx-note">
              Light at night each year, {first}–{last}, and the change from {span}. &ldquo;Mixed&rdquo; means
              NASA&rsquo;s two yearly composites disagree.
            </p>
            <div className="mcx-list">
              {lgas.map((g) => (
                <button key={g.lga} type="button"
                  className={`mcx-row ${selLga === g.lga ? 'is-sel' : ''}`}
                  onClick={() => setSel({ kind: 'lga', lga: g.lga })}>
                  <span className="mcx-row-lga">{g.lga}</span>
                  <Spark values={g.near_nadir} w={110} h={26} colour={changeColour(g)} />
                  <span className="mcx-row-chg" style={{ color: changeColour(g) }}>{changeText(g)}</span>
                  <span className="mcx-row-people">{n0(g.people)} people</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {data?.available && (gone.length > 0 || fresh.length > 0) && (
        <section className="mcx-villages">
          {([['gone', 'Villages that went dark', gone, 'Lit in 2012–14, no light for the last three years'],
            ['new', 'Villages newly lit', fresh, 'Dark in 2012–14, clearly lit for the last three years']] as const).map(
            ([kind, head, rows, why]) => (
              <div key={kind} className="mcx-vcol">
                <div className="mcx-vhead">
                  <i className={`mcx-dot ${kind === 'gone' ? 'mcx-dot--indigo' : 'mcx-dot--amber'}`} />
                  <h3 className="mcx-h2">{head}</h3>
                </div>
                <span className="mcx-note">{why} — on both of NASA&rsquo;s yearly composites. Most people first.</span>
                {rows.length === 0 && <span className="mcx-note">None in {stateLabel}.</span>}
                {rows.slice(0, 6).map((v, i) => (
                  <button key={`${v.name}-${i}`} type="button" className="mcx-vrow"
                    onClick={() => {
                      setLayersOn((s) => ({ ...s, [kind === 'gone' ? 'gone' : 'fresh']: true }));
                      setSel({ kind: 'village', list: kind, i });
                    }}>
                    <span className="mcx-vrow-main">
                      <b>{v.name}</b>
                      <span>{v.lga} LGA · {kind === 'gone' ? 'dark since' : 'first lit'} {v.since_year ?? '—'}</span>
                    </span>
                    <Spark values={v.near_nadir} w={96} h={24} colour={kind === 'gone' ? INDIGO_TXT : AMBER_TXT} />
                    <span className="mcx-vrow-people">{n0(v.people)} people</span>
                  </button>
                ))}
              </div>
            ))}
        </section>
      )}

      {data && data.prices.length > 0 && (
        <section className="mcx-block">
          <div className="mcx-block-head">
            <h3 className="mcx-h2">What food costs in {possessive(stateLabel)} markets</h3>
            <span className="mcx-kpi-src">
              {data.prices[0].source.startsWith('fews') ? 'FEWS NET' : 'NBS'} · monthly
              {lastPrice ? ` · last published ${monthLabel(lastPrice)}` : ''}
            </span>
          </div>
          {pricesStale && lastPrice && (
            <p className="mcx-note">No newer prices have been published for {stateLabel} since {monthLabel(lastPrice)}.</p>
          )}
          <div className="mcx-prices">
            {data.prices.map((s) => {
              const a = s.points[0]?.price_ngn_per_kg;
              const b = s.points[s.points.length - 1]?.price_ngn_per_kg;
              const p = pc(s);
              const col = p == null ? MUTED_TXT : p >= 10 ? '#a3441f' : p <= -10 ? INDIGO_TXT : '#1c2228';
              return (
                <div key={s.crop} className="mcx-price">
                  <div className="mcx-price-top"><b>{CROPS[s.crop] ?? s.crop}</b>{p != null && <span style={{ color: col }}>{signed(p)}</span>}</div>
                  <Spark values={s.points.map((x) => x.price_ngn_per_kg)} w={196} h={40} colour={col} />
                  <span className="mcx-kpi-src">₦{n0(a)} → ₦{n0(b)} per kg</span>
                </div>
              );
            })}
          </div>
        </section>
      )}

      <section className="mcx-notes">
        <div>
          <span className="mcx-notes-label mcx-notes-label--indigo">Displaced people</span>
          <span>
            IOM counts the displaced people living in each LGA every few months. See their latest figures on
            the{' '}
            <a href={IOM_DTM_NIGERIA} target="_blank" rel="noopener noreferrer">IOM Displacement Tracking Matrix for Nigeria&nbsp;↗</a>
          </span>
        </div>
        <div>
          <span className="mcx-notes-label">How we report</span>
          <span>
            Light seen from space tracks activity, not income. It can fall because people left, a grid line or
            generator stopped, or fuel got dearer — and rise with a new connection, solar or a new market. We show
            where it changed; people on the ground say why. Single years move with cloud and viewing angle, so we
            compare three-year averages and show only changes both of NASA&rsquo;s yearly composites agree on.
            People counts come from Meta &amp; CIESIN&rsquo;s population map, which predates recent moves.
          </span>
        </div>
      </section>
      <span className="mcx-credit">{GRID3_CREDIT} · Night light: NASA Black Marble VNP46A4 · Population © Meta &amp; CIESIN, CC BY 4.0</span>
    </section>
  );
}


function LgaCard({ g, span, onClose }: { g: LightTrendLga; span: string; onClose: () => void }) {
  const big = g.category === 'mixed' ? 'Mixed signal'
    : g.category === 'new_light' ? 'New light'
      : g.category === 'still_dark' ? 'Little light, then and now'
        : lightChange(g.change_pct ?? 0);
  return (
    <HaloCard
      title={`${g.lga} LGA · light at night`}
      big={big}
      chart={(
        <div className="mcx-card-chart">
          <Spark values={g.near_nadir} faint={g.all_angle} w={300} h={54} colour={changeColour(g)} />
          <div className="mcx-card-axis"><span>{g.years[0]}</span><span>light each year</span><span>{g.years[g.years.length - 1]}</span></div>
        </div>
      )}
      rows={[
        { k: 'Change', v: `${changeText(g)} · ${span}` },
        { k: 'Lit area', v: `${g.lit_km2_start ?? '—'} → ${g.lit_km2_now ?? '—'} km²` },
        { k: 'Check', v: g.category === 'mixed' ? 'NASA’s two yearly composites disagree — treat as uncertain' : 'Both NASA composites agree' },
        { k: 'Villages', v: `${n0(g.gone_dark)} gone dark · ${n0(g.newly_lit)} newly lit` },
        { k: 'Lives here', v: `${n0(g.people)} people in ${n0(g.villages)} named villages` },
      ]}
      why="Total light seen from space each year (bold: near-nadir; faint: all-angle). Light tracks activity — markets, electricity, settlement — not income."
      onClose={onClose}
    />
  );
}


function VillageCard({ v, kind, first, onClose }: {
  v: TrendVillage; kind: 'gone' | 'new'; first: number | null; onClose: () => void;
}) {
  const avg = (xs: (number | null)[]) => {
    const ok = xs.filter((x): x is number => x != null);
    return ok.length ? ok.reduce((a, b) => a + b, 0) / ok.length : null;
  };
  const a = avg(v.near_nadir.slice(0, 3));
  const b = avg(v.near_nadir.slice(-3));
  return (
    <HaloCard
      title={`${v.name} · ${kind === 'gone' ? 'gone dark' : 'newly lit'}`}
      big={`${n0(v.people)} people`}
      chart={(
        <div className="mcx-card-chart">
          <Spark values={v.near_nadir} w={300} h={48} colour={kind === 'gone' ? INDIGO_TXT : AMBER_TXT} />
          <div className="mcx-card-axis"><span>{first ?? ''}</span><span>light each year</span><span>{first ? first + v.near_nadir.length - 1 : ''}</span></div>
        </div>
      )}
      rows={[
        { k: 'Where', v: `${v.lga ?? '—'} LGA${v.ward ? ` · ${v.ward} ward` : ''}` },
        { k: 'Light', v: `${a?.toFixed(1) ?? '—'} → ${b?.toFixed(1) ?? '—'} nW (first three years → last three)` },
        { k: kind === 'gone' ? 'Dark since' : 'First lit', v: String(v.since_year ?? '—') },
        { k: 'Location', v: <>{v.location.lat.toFixed(4)}°N {v.location.lon.toFixed(4)}°E · <DirectionsLink lat={v.location.lat} lon={v.location.lon} /></> },
      ]}
      why={kind === 'gone'
        ? 'Lit at the start, no light for the last three years on both of NASA’s yearly composites. Light can go out when people leave, when a grid line or generator stops, or when fuel gets dearer — someone on the ground can say which. People counts are from the population map, before any recent moves.'
        : 'Dark for the first three years, clearly lit now on both of NASA’s yearly composites: a new connection, solar, a new market or new settlement. Someone on the ground can say which.'}
      onClose={onClose}
    />
  );
}
