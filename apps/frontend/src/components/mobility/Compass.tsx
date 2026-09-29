'use client';

/**
 * Mobility Compass — every LGA against five measured factors (operator-approved
 * mock v7, 2026-09-28): activity from night light, this season's farming, the
 * walk to a health facility, health facilities per person, and what food and
 * fuel cost. Each factor is shown on its own; the only roll-up is a COUNT of
 * readings that point to pressure — never a score.
 *
 * Built on the night-light view it replaces (2026-09-27), which it keeps whole:
 * light change by LGA, villages gone dark and newly lit, villages lit now, the
 * staple prices, the IOM link. A change in light is shown only when both of
 * NASA's yearly composites agree; travel time is modelled and labelled so;
 * World Bank prices are model estimates and every tile says when its market
 * was last surveyed. IOM displacement counts are non-commercial: linked, not shown.
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
import { formatLocalAndUsd } from '@/lib/currency';
import { useCompass, type CompassLga, type CompassPrice, type FarVillage } from '@/hooks/useCompass';
import { useLgaBoundaries } from '@/hooks/useLgaBoundaries';
import { useLightTrend, type LightTrendLga, type StapleSeries, type TrendVillage } from '@/hooks/useLightTrend';
import { useVillageLight, type VillagePoint } from '@/hooks/useVillageLight';

type RGB = [number, number, number];

const IOM_DTM_NIGERIA = 'https://dtm.iom.int/nigeria';
const INDIGO: RGB = [47, 58, 138];
const MID: RGB = [230, 231, 234];
const UP: RGB = [217, 154, 30];
const UP2: RGB = [138, 90, 0];
const MIXED: RGB = [160, 164, 170];
const LEAF: RGB = [47, 107, 58];
const RUST: RGB = [163, 68, 31];
const INK: RGB = [28, 34, 40];
const AMBER_TXT = '#b07a0e';
const INDIGO_TXT = '#2f3a8a';
const MUTED_TXT = '#56616b';
const RUST_TXT = '#a3441f';
const LEAF_TXT = '#2f6b3a';
const ITEMS: Record<string, string> = {
  petrol: 'Petrol · 12 months', maize: 'Maize', sorghum: 'Sorghum', millet: 'Millet',
  rice: 'Rice (local)', cowpea: 'Cowpea', gari: 'Gari',
};

const n0 = (v: number | null | undefined) => (v == null ? '—' : Math.round(v).toLocaleString('en-US'));
const signed = (v: number) => `${v >= 0 ? '+' : '−'}${Math.abs(Math.round(v)).toLocaleString('en-US')}%`;
/** A light change: a percentage, or a multiple once light has tripled (“+1390%” reads as “15×”). */
const lightChange = (pct: number) => (pct >= 200 ? `${Math.round(1 + pct / 100)}×` : signed(pct));
const people = (v: number) => (v >= 1e6 ? `${(v / 1e6).toFixed(2)} million` : n0(v));
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
/** Minutes as the page says them: "45 min", "3 h". */
const duration = (min: number | null | undefined) =>
  (min == null ? '—' : min >= 120 ? `${Math.round(min / 60)} h` : `${Math.round(min)} min`);

function mix(a: number[], b: number[], t: number): RGB {
  const k = Math.max(0, Math.min(1, t));
  return [0, 1, 2].map((i) => Math.round(a[i] + (b[i] - a[i]) * k)) as RGB;
}

type LightLike = { category: string | null; change_pct: number | null };

/** Diverging colour: -1 halved (indigo) … 0 same … +1 doubled (amber) … +1.5 (deep amber). */
function lightRgb(g: LightLike): RGB {
  if (g.category === 'mixed' || g.category == null) return MIXED;
  if (g.category === 'still_dark') return MID;
  if (g.category === 'new_light') return mix(UP, UP2, 0.6);
  const t = Math.max(-1, Math.min(1.5, Math.log2(Math.max(0.05, 1 + (g.change_pct ?? 0) / 100))));
  if (t < 0) return mix(MID, INDIGO, -t);
  if (t <= 1) return mix(MID, UP, t);
  return mix(UP, UP2, (t - 1) / 0.5);
}

function seasonRgb(pct: number | null): RGB | null {
  if (pct == null) return null;
  return pct < 0 ? mix(RUST, MID, (pct + 10) / 10) : mix(MID, LEAF, pct / 40);
}

function walkRgb(share: number | null): RGB | null {
  return share == null ? null : mix(MID, RUST, share / 0.9);
}

function changeText(g: LightLike): string {
  switch (g.category) {
    case 'mixed': return 'mixed';
    case 'new_light': return 'new light';
    case 'still_dark': return 'still dark';
    case null: return '—';
    default: return g.change_pct == null ? '—' : lightChange(g.change_pct);
  }
}

function changeColour(g: LightLike): string {
  if (g.category === 'dimmer') return INDIGO_TXT;
  if (g.category === 'brighter' || g.category === 'new_light') return AMBER_TXT;
  return MUTED_TXT;
}

function farmColour(v: number | null): string {
  if (v == null) return MUTED_TXT;
  return v < 0 ? RUST_TXT : v >= 5 ? LEAF_TXT : MUTED_TXT;
}

function Spark({ values, w, h, colour, faint }: {
  values: (number | null)[]; w: number; h: number; colour: string; faint?: (number | null)[];
}) {
  if (values.length < 2) return <svg width={w} height={h} aria-hidden="true" className="mcx-spark" />;
  const path = (vals: (number | null)[], lo: number, hi: number) => vals
    .map((v, i) => `${i === 0 ? 'M' : 'L'}${(2 + (i * (w - 4)) / Math.max(1, vals.length - 1)).toFixed(1)},${(h - 3 - (((v ?? lo) - lo) / (hi - lo || 1)) * (h - 6)).toFixed(1)}`)
    .join(' ');
  const all = [...values, ...(faint ?? [])].filter((v): v is number => v != null);
  const hi = Math.max(1e-9, ...all);
  const lo = Math.min(0, ...all);
  const last = values.length - 1;
  const lx = 2 + (last * (w - 4)) / Math.max(1, last);
  const ly = h - 3 - (((values[last] ?? lo) - lo) / (hi - lo || 1)) * (h - 6);
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true" className="mcx-spark">
      {faint && <path d={path(faint, lo, hi)} fill="none" stroke={colour} strokeOpacity={0.3} strokeWidth={1.4} />}
      <path d={path(values, lo, hi)} fill="none" stroke={colour} strokeWidth={1.7} />
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

function andJoin(names: string[]): string {
  return names.length <= 1 ? (names[0] ?? '') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

function priceChange(p: { points: { price_ngn: number }[] }): number | null {
  return p.points.length > 1 ? 100 * (p.points[p.points.length - 1].price_ngn / p.points[0].price_ngn - 1) : null;
}

/** Where a price comes from and how current it is, in one line. */
function priceSource(p: CompassPrice): string {
  if (p.modelled) {
    const surveyed = p.last_surveyed ? `last surveyed ${monthLabel(p.last_surveyed)}` : 'never surveyed here';
    return `${p.place} · World Bank estimate · ${surveyed}`;
  }
  const last = p.points[p.points.length - 1]?.month;
  return `${p.place} · ${p.publisher}${p.stale && last ? ` · last published ${monthLabel(last)}` : ''}`;
}

type Fill = 'light' | 'season' | 'walk';
type Sel =
  | { kind: 'lga'; lga: string }
  | { kind: 'village'; list: 'gone' | 'new'; i: number }
  | { kind: 'far'; i: number }
  | null;


export default function Compass({ tenant, stateLabel }: { tenant: Tenant; stateLabel: string }) {
  const trend = useLightTrend(tenant.id);
  const compassQ = useCompass(tenant.id);
  const lgasQ = useLgaBoundaries(tenant.id);
  const [basemap, setBasemap] = useState<Basemap>('light');
  const [fill, setFill] = useState<Fill | null>('light');
  const [layersOn, setLayersOn] = useState({ lga: true, gone: true, fresh: false, far: false, villages: false });
  const villageQ = useVillageLight(layersOn.villages ? tenant.id : '');
  const [sel, setSel] = useState<Sel>(null);
  // A selection points into this state's data — drop it when the state changes.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSel(null);
  }, [tenant.id]);
  const [now] = useState(() => Date.now());

  const data = trend.data;
  const cp = compassQ.data;
  const lights = useMemo(() => data?.lgas ?? [], [data]);
  const lightBy = useMemo(() => new Map(lights.map((g) => [g.lga, g])), [lights]);
  const rows = useMemo(() => cp?.lgas ?? [], [cp]);
  const rowBy = useMemo(() => new Map(rows.map((r) => [r.lga, r])), [rows]);
  const gone = useMemo(() => data?.villages_gone_dark ?? [], [data]);
  const fresh = useMemo(() => data?.villages_newly_lit ?? [], [data]);
  const far = useMemo(() => cp?.far_from_care ?? [], [cp]);
  const villagePts = useMemo(() => villageQ.data?.points ?? [], [villageQ.data]);
  const goneI = useMemo(() => gone.map((v, i) => ({ v, i })), [gone]);
  const freshI = useMemo(() => fresh.map((v, i) => ({ v, i })), [fresh]);
  const farI = useMemo(() => far.slice(0, 12).map((v, i) => ({ v, i })), [far]);
  const lgaPins = useMemo(() => rows.filter((r) => r.location), [rows]);
  const first = data?.first_year ?? null;
  const last = data?.last_year ?? null;
  const base = first ? `${first}–${String(first + 2).slice(2)}` : '';
  const span = first && last ? `${base} to ${last - 2}–${String(last).slice(2)}` : '';
  const prev = cp?.previous_year ?? null;
  const alpha = fillAlpha(basemap);
  const dark = basemap !== 'light';
  const compassOn = Boolean(cp?.available);

  const selLga = sel?.kind === 'lga' ? sel.lga : null;
  const selKey = sel && sel.kind !== 'lga' ? (sel.kind === 'far' ? `far-${sel.i}` : `${sel.list}-${sel.i}`) : null;

  const layers = useMemo(() => {
    const out: unknown[] = [];
    if (fill && lgasQ.data) {
      out.push(new GeoJsonLayer({
        id: 'mcx-fill',
        data: lgasQ.data as never,
        filled: true,
        stroked: true,
        pickable: true,
        getFillColor: (f: { properties: { lga: string } }) => {
          const name = f.properties.lga;
          let rgb: RGB | null = null;
          if (fill === 'light') {
            const g = lightBy.get(name);
            rgb = g ? lightRgb(g) : null;
          } else if (fill === 'season') {
            rgb = seasonRgb(rowBy.get(name)?.season_pct ?? null);
          } else {
            rgb = walkRgb(rowBy.get(name)?.over_hour_walk_share ?? null);
          }
          return rgb ? [...rgb, alpha] : [140, 140, 140, 30];
        },
        getLineColor: (f: { properties: { lga: string } }) =>
          (f.properties.lga === selLga ? [28, 34, 40, 255] : [255, 255, 255, 170]),
        getLineWidth: (f: { properties: { lga: string } }) => (f.properties.lga === selLga ? 3 : 1),
        lineWidthUnits: 'pixels',
        onClick: (info: { object?: { properties: { lga: string } } }) => {
          const lga = info.object?.properties.lga;
          if (lga && (rowBy.has(lga) || lightBy.has(lga))) setSel({ kind: 'lga', lga });
        },
        updateTriggers: { getFillColor: [fill, lightBy, rowBy, alpha], getLineColor: [selLga], getLineWidth: [selLga] },
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
    if (layersOn.lga && lgaPins.length) {
      out.push(new ScatterplotLayer({
        id: 'mcx-lga-halo',
        data: lgaPins,
        getPosition: (r: CompassLga) => [r.location!.lon, r.location!.lat],
        getFillColor: (r: CompassLga): [number, number, number, number] =>
          [...(r.signals.length ? RUST : INK), r.lga === selLga ? 90 : 38] as [number, number, number, number],
        getRadius: (r: CompassLga) => 9 + 3 * r.signals.length + (r.lga === selLga ? 6 : 0),
        radiusUnits: 'pixels',
        pickable: false,
        updateTriggers: { getFillColor: [selLga], getRadius: [selLga] },
      }));
      out.push(new ScatterplotLayer({
        id: 'mcx-lga-core',
        data: lgaPins,
        getPosition: (r: CompassLga) => [r.location!.lon, r.location!.lat],
        getFillColor: (r: CompassLga): [number, number, number] => (r.signals.length ? RUST : INK),
        getLineColor: [255, 255, 255, 245],
        stroked: true,
        lineWidthMinPixels: 2,
        getRadius: (r: CompassLga) => 4 + r.signals.length,
        radiusUnits: 'pixels',
        pickable: true,
        onClick: (info: { object?: CompassLga }) => {
          if (info.object) setSel({ kind: 'lga', lga: info.object.lga });
        },
      }));
    }
    const pins = <T extends { location: { lon: number; lat: number } }>(
      id: string, key: string, list: { v: T; i: number }[], rgb: RGB, onPick: (i: number) => void,
    ) => {
      out.push(new ScatterplotLayer({
        id: `${id}-halo`,
        data: list,
        getPosition: (x: { v: T }) => [x.v.location.lon, x.v.location.lat],
        getFillColor: (x: { i: number }): [number, number, number, number] =>
          [rgb[0], rgb[1], rgb[2], selKey === `${key}-${x.i}` ? 100 : 50],
        getRadius: (x: { i: number }) => (selKey === `${key}-${x.i}` ? 19 : 12),
        radiusUnits: 'pixels',
        pickable: false,
        updateTriggers: { getFillColor: [selKey], getRadius: [selKey] },
      }));
      out.push(new ScatterplotLayer({
        id: `${id}-core`,
        data: list,
        getPosition: (x: { v: T }) => [x.v.location.lon, x.v.location.lat],
        getFillColor: [rgb[0], rgb[1], rgb[2], 255],
        getLineColor: [255, 255, 255, 245],
        stroked: true,
        lineWidthMinPixels: 2,
        getRadius: 6,
        radiusUnits: 'pixels',
        pickable: true,
        onClick: (info: { object?: { i: number } }) => {
          if (info.object) onPick(info.object.i);
        },
      }));
    };
    if (layersOn.gone && goneI.length) pins('mcx-gone', 'gone', goneI, INDIGO, (i) => setSel({ kind: 'village', list: 'gone', i }));
    if (layersOn.fresh && freshI.length) pins('mcx-new', 'new', freshI, UP, (i) => setSel({ kind: 'village', list: 'new', i }));
    if (layersOn.far && farI.length) pins('mcx-far', 'far', farI, RUST, (i) => setSel({ kind: 'far', i }));
    return out;
  }, [fill, layersOn, lgasQ.data, lightBy, rowBy, alpha, selLga, villagePts, dark, lgaPins, goneI, freshI, farI, selKey]);

  // The pinned card for whatever is selected.
  let card: { lng: number; lat: number; node: ReactNode } | null = null;
  if (sel?.kind === 'lga') {
    const r = rowBy.get(sel.lga);
    const g = lightBy.get(sel.lga);
    const loc = r?.location ?? g?.location;
    if (loc) {
      card = {
        lng: loc.lon, lat: loc.lat,
        node: r
          ? <LgaCompassCard r={r} g={g} base={base} prev={prev} since={cp?.season_since ?? null}
              release={cp?.facilities_release ?? null} onClose={() => setSel(null)} />
          : <LgaLightCard g={g!} span={span} onClose={() => setSel(null)} />,
      };
    }
  } else if (sel?.kind === 'village') {
    const v = (sel.list === 'gone' ? gone : fresh)[sel.i];
    if (v) {
      card = {
        lng: v.location.lon, lat: v.location.lat,
        node: <VillageCard v={v} kind={sel.list} first={first} onClose={() => setSel(null)} />,
      };
    }
  } else if (sel?.kind === 'far') {
    const v = far[sel.i];
    if (v) card = { lng: v.location.lon, lat: v.location.lat, node: <FarCard v={v} onClose={() => setSel(null)} /> };
  }

  // ── headline and figures ────────────────────────────────────────────
  const worst = lights.find((g) => g.category === 'dimmer') ?? null;
  const best = [...lights].filter((g) => g.category === 'brighter')
    .sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0))[0] ?? null;
  const compassPrices = cp?.prices ?? [];
  const foods = compassPrices.filter((p) => p.item !== 'petrol');
  const headlineFood = foods.find((p) => !p.stale && p.points.length > 1) ?? null;
  const legacyPrices: StapleSeries[] = compassPrices.length ? [] : (data?.prices ?? []);
  const lastPrice = legacyPrices.reduce<string | null>((m, s) => {
    const d = s.points[s.points.length - 1]?.month;
    return d && (!m || d > m) ? d : m;
  }, null);
  const pricesStale = lastPrice ? (now - new Date(lastPrice).getTime()) / 86400000 > 200 : false;

  let headline: ReactNode = 'Reading the compass…';
  if (data && !data.available && !compassOn) headline = cp?.reason ?? data.reason ?? `The compass for ${stateLabel} is not measured yet.`;
  else if (compassOn || data?.available) {
    const all3 = rows.filter((r) => r.signals.length === 3);
    const two = rows.filter((r) => r.signals.length === 2);
    const nL = lights.length || rows.length;
    if (all3.length) {
      const farming = [...new Set(all3.flatMap((r) => r.signals).filter((s) => s.startsWith('farming')))]
        .map((s) => s.split(' ')[1]).join(' or ');
      const most = all3.every((r) => (r.over_hour_walk_share ?? 0) > 0.5);
      headline = `In ${andJoin(all3.map((r) => r.lga))}, every signal points the same way: lights fading, farming ${farming}, and ${most ? 'most people' : 'half or more of the people'} over an hour's walk from a health facility.`;
    } else if (two.length) {
      const say: Record<string, string> = {
        'activity fading': 'lights fading', 'farming behind': 'farming behind last season',
        'farming flat': 'farming flat on last season', 'far from care': 'half or more of the people over an hour’s walk from care',
      };
      const common = two[0].signals.filter((s) => two.every((r) => r.signals.includes(s)));
      headline = common.length === 2
        ? `In ${andJoin(two.map((r) => r.lga))}, two signals point the same way: ${andJoin(common.map((s) => say[s] ?? s))}.`
        : `${plural(two.length, 'LGA')} in ${stateLabel.replace(/ State$/, '')} show two of three pressure signals — ${andJoin(two.map((r) => r.lga))}.`;
    } else if (data?.available) {
      const out = worst && (worst.change_pct ?? 0) <= -80 ? ` In ${worst.lga}, the lights have almost gone out.` : '';
      headline = data.dimmer >= data.brighter
        ? `${data.dimmer} of ${possessive(stateLabel)} ${nL} LGAs are darker at night than a decade ago.${out}`
        : `${data.brighter} of ${possessive(stateLabel)} ${nL} LGAs are brighter at night than a decade ago${
          out ? ` — but in ${worst!.lga}, the lights have almost gone out.` : data.dimmer ? `; ${data.dimmer} are darker.` : '.'}`;
    } else {
      headline = `No LGA in ${stateLabel.replace(/ State$/, '')} shows two pressure signals together.`;
    }
  }

  const overShare = cp && cp.people ? cp.over_hour_walk_people / cp.people : null;
  const factorCount = [
    lights.length > 0, cp?.season_state_pct != null || rows.some((r) => r.season_pct != null),
    cp?.access_measured, cp?.facilities_release != null, compassPrices.length > 0,
  ].filter(Boolean).length;
  const facNote = cp?.facilities_unlocated
    ? ` GRID3 lists ${n0(cp.facilities_unlocated)} more of ${possessive(stateLabel)} facilities without a location; they are not in the LGA counts.`
    : '';
  const tableSorted = rows.length ? rows : [];

  return (
    <section className="mcx" aria-labelledby="mcx-title">
      <div className="mcx-head">
        <div className="mcx-head-main">
          <span className="mcx-eyebrow">
            Mobility Compass · {stateLabel} · Livelihoods, services and prices
          </span>
          <h2 id="mcx-title" className="mcx-h1">{headline}</h2>
          <p className="mcx-sub">
            Five measured factors for every LGA — activity from night light, this season&rsquo;s farming, the
            walk to a health facility, health facilities per person, and what food and fuel cost — side by
            side, never blended into a score.
          </p>
        </div>
        <div className="mcx-head-side">
          <span className="mcx-chip">
            {factorCount} FACTORS · MEASURED{first ? ` · ${first}–${cp?.season_year ?? last}` : ''}
          </span>
          <ModuleSources sources={[
            { name: 'NASA VIIRS Black Marble', role: 'light at night, every year since 2012' },
            { name: 'Copernicus Sentinel-2', role: 'farmland greenness this season' },
            { name: 'Data for Children Collaborative', role: 'travel time to care, modelled' },
            { name: 'GRID3', role: 'villages and health facilities' },
            { name: 'Meta & CIESIN HRSL', role: 'people' },
            { name: 'World Bank · FEWS NET · NBS', role: 'food and fuel prices' },
            { name: 'NASA GPM IMERG', role: 'storms this season' },
          ]} />
        </div>
      </div>

      {trend.isError && <div className="fp-alert-error">Could not load the night-light record: {trend.error?.message ?? 'unknown'}</div>}
      {compassQ.isError && <div className="fp-alert-error">Could not load the compass: {compassQ.error?.message ?? 'unknown'}</div>}

      {(compassOn || data?.available) && (
        <div className="mcx-kpis">
          {cp?.access_measured && overShare != null ? (
            <div className="mcx-kpi">
              <span className="mcx-kpi-val mcx-kpi-val--indigo">{Math.round(100 * overShare)}%</span>
              <span className="mcx-kpi-label">
                of {possessive(stateLabel)} people live more than an hour&rsquo;s walk from a health facility — {people(cp.over_hour_walk_people)}
              </span>
              <span className="mcx-kpi-src">Data for Children travel time (modelled) · GRID3 villages</span>
            </div>
          ) : worst ? (
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
          {data?.available && (
            <div className="mcx-kpi">
              <span className="mcx-kpi-val">{data.dimmer} of {lights.length}</span>
              <span className="mcx-kpi-label">
                LGAs darker at night than in {base}
                {data.dimmer ? ` — ${people(data.people_in_dimmer)} people live in them` : ''}; {data.brighter} brighter, {data.mixed} unclear
                {' '}· {n0(data.gone_dark)} villages gone dark
              </span>
              <span className="mcx-kpi-src">NASA Black Marble · both composites agree</span>
            </div>
          )}
          {cp?.season_state_pct != null && (
            <div className="mcx-kpi">
              <span className="mcx-kpi-val" style={{ color: farmColour(cp.season_state_pct) }}>{signed(cp.season_state_pct)}</span>
              <span className="mcx-kpi-label">
                farmland greenness vs the {prev} rains, same ground, statewide
              </span>
              <span className="mcx-kpi-src">Copernicus Sentinel-2</span>
            </div>
          )}
          {headlineFood && priceChange(headlineFood) != null ? (
            <div className="mcx-kpi">
              <span className="mcx-kpi-val">{signed(priceChange(headlineFood)!)}</span>
              <span className="mcx-kpi-label">
                {ITEMS[headlineFood.item] ?? headlineFood.item}, {monthLabel(headlineFood.points[0].month)} to {monthLabel(headlineFood.points[headlineFood.points.length - 1].month)} —
                ₦{n0(headlineFood.points[headlineFood.points.length - 1].price_ngn)} a kg
              </span>
              <span className="mcx-kpi-src">{priceSource(headlineFood)}</span>
            </div>
          ) : cp?.income_usd_month != null ? (
            <div className="mcx-kpi">
              <span className="mcx-kpi-val">{formatLocalAndUsd(cp.income_usd_month, tenant.country)}</span>
              <span className="mcx-kpi-label">typical household income a month — a state-level estimate</span>
              <span className="mcx-kpi-src">World Bank income scaled to the NBS living-standards survey</span>
            </div>
          ) : null}
        </div>
      )}

      {(compassOn || data?.available) && (
        <div className="mcx-main">
          <div className="mcx-mapcol">
            <MapToolbar
              basemap={basemap}
              onBasemap={setBasemap}
              layers={[
                { id: 'light', label: 'Light change', dot: '#d99a1e', on: fill === 'light' },
                ...(prev ? [{ id: 'season', label: `Farming vs ${prev}`, dot: LEAF_TXT, on: fill === 'season' }] : []),
                ...(cp?.access_measured ? [{ id: 'walk', label: 'Over an hour to care', dot: '#c77b5c', on: fill === 'walk' }] : []),
                ...(compassOn ? [{ id: 'lga', label: 'LGA compass', dot: '#1c2228', on: layersOn.lga }] : []),
                { id: 'gone', label: 'Gone dark', dot: '#2f3a8a', on: layersOn.gone },
                { id: 'fresh', label: 'Newly lit', dot: '#d99a1e', on: layersOn.fresh },
                ...(far.length ? [{ id: 'far', label: 'Far from care', dot: RUST_TXT, on: layersOn.far }] : []),
                { id: 'villages', label: 'Villages lit now', dot: '#ffc466', on: layersOn.villages },
              ]}
              onToggle={(id) => {
                // The three fills are one choice — a map can colour LGAs by one factor at a time.
                if (id === 'light' || id === 'season' || id === 'walk') {
                  setFill((f) => (f === id ? null : id));
                } else {
                  setLayersOn((s) => ({ ...s, [id]: !s[id as keyof typeof s] }));
                }
              }}
            />
            <EBMap
              tenant={tenant}
              layers={layers}
              height="620px"
              zoom={6.8}
              mapStyle={BASEMAP_STYLE[basemap]}
              ariaLabel={`${stateLabel} by LGA: change in light at night, this season's farming and the walk to a health facility`}
              getTooltip={(o) => {
                const f = o as { properties?: { lga: string }; v?: TrendVillage | FarVillage; lga?: string; signals?: string[] };
                if (f?.v && 'walk_min' in f.v) return `${f.v.name} · ${f.v.lga ?? ''}\n${duration(f.v.walk_min)} walk to care · click for detail`;
                if (f?.v) return `${f.v.name} · ${f.v.lga ?? ''}\n${n0(f.v.people)} people · click for detail`;
                if (f?.signals && f.lga) return `${f.lga} · ${plural(f.signals.length, 'signal')}\nClick for the compass`;
                if (f?.properties?.lga) {
                  const name = f.properties.lga;
                  const r = rowBy.get(name);
                  const g = lightBy.get(name);
                  if (fill === 'season' && r) return `${name} · farming ${r.season_pct == null ? 'not compared' : signed(r.season_pct)} vs ${prev}\nClick for detail`;
                  if (fill === 'walk' && r) return `${name} · ${r.over_hour_walk_share == null ? '—' : `${Math.round(100 * r.over_hour_walk_share)}%`} over an hour's walk from care\nClick for detail`;
                  return g ? `${name} · ${changeText(g)} since ${base}\nClick for detail` : null;
                }
                return null;
              }}
              card={card}
            />
            <div className="mcx-legend">
              {fill === 'light' && <span><i className="mcx-ramp" /> dimmer → brighter since {base}</span>}
              {fill === 'light' && <span><i className="mcx-sq" /> NASA composites disagree</span>}
              {fill === 'season' && <span><i className="mcx-ramp mcx-ramp--farm" /> behind → ahead of {prev}, same ground</span>}
              {fill === 'walk' && <span><i className="mcx-ramp mcx-ramp--walk" /> share of people over an hour&rsquo;s walk from care</span>}
              {layersOn.lga && compassOn && <span><i className="mcx-dot mcx-dot--rust" /> LGA with pressure signals — click for the compass</span>}
              <span><i className="mcx-dot mcx-dot--indigo" /> Gone dark</span>
              {layersOn.fresh && <span><i className="mcx-dot mcx-dot--amber" /> Newly lit</span>}
              {layersOn.far && <span><i className="mcx-dot mcx-dot--rust" /> Far from care</span>}
            </div>
          </div>

          <div className="mcx-side">
            {compassOn ? (
              <>
                <h3 className="mcx-h2">The compass — every LGA, every factor</h3>
                <p className="mcx-note">
                  Each column is measured separately. Signals are a count of readings that point to pressure, not a score.
                </p>
                <div className="mcx-ctable">
                  <div className="mcx-crow mcx-crow--head">
                    <span>LGA</span>
                    <span>Light since<br />{base}</span>
                    <span className="is-num">Farming<br />vs {prev ?? '—'}</span>
                    <span className="is-num">Over 1 h<br />to care</span>
                    <span className="is-num">Facilities<br />per 10k</span>
                    <span>Signals</span>
                  </div>
                  <div className="mcx-cbody">
                    {tableSorted.map((r) => {
                      const g = lightBy.get(r.lga);
                      const lg: LightLike = { category: r.light_category, change_pct: r.light_change_pct };
                      const share = r.over_hour_walk_share;
                      const hot = share != null && share >= 0.5;
                      const label = `${plural(r.signals.length, 'signal')}${r.signals.length ? `: ${r.signals.join(', ')}` : ''}`;
                      return (
                        <button key={r.lga} type="button"
                          className={`mcx-crow ${selLga === r.lga ? 'is-sel' : ''}`}
                          onClick={() => setSel({ kind: 'lga', lga: r.lga })}>
                          <span className="mcx-row-lga">{r.lga}</span>
                          <span className="mcx-clight">
                            {g && <Spark values={g.near_nadir} w={56} h={20} colour={changeColour(lg)} />}
                            <b style={{ color: changeColour(lg) }}>{changeText(lg)}</b>
                          </span>
                          <span className="mcx-cnum" style={{ color: farmColour(r.season_pct) }}>
                            {r.season_pct == null ? '—' : signed(r.season_pct)}
                          </span>
                          <span className="mcx-ccare">
                            <i><i style={{ width: `${Math.round(100 * (share ?? 0))}%`, background: hot ? RUST_TXT : '#8a939b' }} /></i>
                            <b style={{ color: hot ? RUST_TXT : undefined }}>{share == null ? '—' : `${Math.round(100 * share)}%`}</b>
                          </span>
                          <span className="mcx-cnum mcx-cmono">
                            {r.facilities_per_10k == null ? '—' : r.facilities_per_10k.toFixed(1)}
                          </span>
                          <span className="mcx-csig" aria-label={label} title={label}>
                            {[0, 1, 2].map((k) => <i key={k} className={k < r.signals.length ? 'is-on' : ''} />)}
                            <b className={r.signals.length ? 'is-on' : ''}>{r.signals.length}</b>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
                {/* A small state's table stops half way down the map: fill the rest
                    with the storm factor, per LGA (until now only in the pop-up). */}
                {rows.length <= 10 && rows.some((r) => r.storms > 0 || r.advisories > 0) && (
                  <div className="mcx-storms">
                    <span className="mcx-notes-label">Storms and farmer SMS advisories{cp?.season_since ? ` since ${new Date(`${cp.season_since}T12:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'long' })}` : ' this season'}</span>
                    {[...rows].sort((a, b) => b.storms - a.storms || a.lga.localeCompare(b.lga)).map((r) => (
                      <button key={r.lga} type="button" className="mcx-storm-row" onClick={() => setSel({ kind: 'lga', lga: r.lga })}>
                        <span>{r.lga}</span>
                        <span className="mcx-storm-bar"><i style={{ width: `${Math.min(100, (100 * r.storms) / Math.max(1, ...rows.map((x) => x.storms)))}%` }} /></span>
                        <span>{r.storms} storm{r.storms === 1 ? '' : 's'}</span>
                        <span>{r.advisories ? `${r.advisories} SMS` : '—'}</span>
                      </button>
                    ))}
                  </div>
                )}
                <span className="mcx-kpi-src mcx-cfoot">
                  Most signals first, then by change in light, darkest first.
                  {cp?.facilities_release ? ` Facilities: GRID3 ${cp.facilities_release}.` : ' Facilities: not in the GRID3 register for this state.'}
                  {facNote}
                </span>
              </>
            ) : (
              <>
                <h3 className="mcx-h2">Where the lights changed</h3>
                <p className="mcx-note">
                  Light at night each year, {first}–{last}, and the change from {span}. &ldquo;Mixed&rdquo; means
                  NASA&rsquo;s two yearly composites disagree.
                </p>
                <div className="mcx-list">
                  {lights.map((g) => (
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
              </>
            )}
          </div>
        </div>
      )}

      {(compassPrices.length > 0 || cp?.income_usd_month != null) && (
        <section className="mcx-block">
          <div className="mcx-block-head">
            <h3 className="mcx-h2">What it costs to live and to move</h3>
            <span className="mcx-kpi-src">Monthly · naira</span>
          </div>
          <div className="mcx-prices">
            {compassPrices.map((p) => {
              const a = p.points[0]?.price_ngn;
              const b = p.points[p.points.length - 1]?.price_ngn;
              const pc = priceChange(p);
              const col = pc == null ? MUTED_TXT : pc >= 10 ? RUST_TXT : pc <= -10 ? INDIGO_TXT : '#1c2228';
              return (
                <div key={p.item} className="mcx-price">
                  <div className="mcx-price-top"><b>{ITEMS[p.item] ?? p.item}</b>{pc != null && <span style={{ color: col }}>{signed(pc)}</span>}</div>
                  <Spark values={p.points.map((x) => x.price_ngn)} w={196} h={40} colour={col} />
                  <span className="mcx-kpi-src">₦{n0(a)} → ₦{n0(b)} per {p.unit}</span>
                  <span className="mcx-price-src">{priceSource(p)}</span>
                </div>
              );
            })}
            {cp?.income_usd_month != null && (
              <div className="mcx-price">
                <div className="mcx-price-top"><b>Household income</b><span style={{ color: MUTED_TXT }}>estimate</span></div>
                <span className="mcx-price-big">{formatLocalAndUsd(cp.income_usd_month, tenant.country)}</span>
                <span className="mcx-kpi-src">a month, typical household</span>
                <span className="mcx-price-src">State level · World Bank income scaled to the NBS living-standards survey</span>
              </div>
            )}
          </div>
          {compassPrices.length > 0 && (
            <span className="mcx-kpi-src">
              World Bank prices are its model&rsquo;s monthly estimates, built from market surveys; each tile says when
              its market was last surveyed. Petrol is shown for the last 12 months only: no market in the World
              Bank&rsquo;s Nigeria file has had petrol surveyed since January 2023, and its earlier estimates run well below
              pump prices.
            </span>
          )}
        </section>
      )}

      {legacyPrices.length > 0 && (
        <section className="mcx-block">
          <div className="mcx-block-head">
            <h3 className="mcx-h2">What food costs in {possessive(stateLabel)} markets</h3>
            <span className="mcx-kpi-src">
              {legacyPrices[0].source.startsWith('fews') ? 'FEWS NET' : 'NBS'} · monthly
              {lastPrice ? ` · last published ${monthLabel(lastPrice)}` : ''}
            </span>
          </div>
          {pricesStale && lastPrice && (
            <p className="mcx-note">No newer prices have been published for {stateLabel} since {monthLabel(lastPrice)}.</p>
          )}
          <div className="mcx-prices">
            {legacyPrices.map((s) => {
              const a = s.points[0]?.price_ngn_per_kg;
              const b = s.points[s.points.length - 1]?.price_ngn_per_kg;
              const p = s.points.length > 1 ? 100 * (b / a - 1) : null;
              const col = p == null ? MUTED_TXT : p >= 10 ? RUST_TXT : p <= -10 ? INDIGO_TXT : '#1c2228';
              return (
                <div key={s.crop} className="mcx-price">
                  <div className="mcx-price-top"><b>{ITEMS[s.crop] ?? s.crop}</b>{p != null && <span style={{ color: col }}>{signed(p)}</span>}</div>
                  <Spark values={s.points.map((x) => x.price_ngn_per_kg)} w={196} h={40} colour={col} />
                  <span className="mcx-kpi-src">₦{n0(a)} → ₦{n0(b)} per kg</span>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {(gone.length > 0 || fresh.length > 0 || far.length > 0) && (
        <section className={`mcx-villages ${far.length && gone.length ? 'mcx-villages--3' : ''}`}>
          {gone.length > 0 && (
          <VillageColumn
            head="Villages that went dark" dot="mcx-dot--indigo"
            why={`Lit in ${base}, no light for the last three years on both of NASA’s yearly composites — ${n0(data?.gone_dark)} villages in all. Most people first.`}
            empty={`None in ${stateLabel}.`}
            items={gone.slice(0, 12).map((v, i) => ({
              key: `g-${i}`, name: v.name, sub: `${v.lga} LGA · dark since ${v.since_year ?? '—'}`,
              right: `${n0(v.people)} people`,
              spark: <Spark values={v.near_nadir} w={96} h={24} colour={INDIGO_TXT} />,
              onClick: () => { setLayersOn((s) => ({ ...s, gone: true })); setSel({ kind: 'village', list: 'gone', i }); },
            }))}
          />
          )}
          {far.length > 0 && (
            <VillageColumn
              head="Farthest from care" dot="mcx-dot--rust"
              why="Modelled walking time to the nearest health facility, on roads, tracks and open ground. Villages of 300 people or more; longest first. The longest times often mark places with no mapped roads — somewhere to check, not a measured journey."
              empty=""
              items={far.slice(0, 12).map((v, i) => ({
                key: `f-${i}`, name: v.name,
                sub: `${v.lga} LGA · ${duration(v.walk_min)} walk · ${duration(v.drive_min)} with transport`,
                right: `${n0(v.people)} people`,
                onClick: () => { setLayersOn((s) => ({ ...s, far: true })); setSel({ kind: 'far', i }); },
              }))}
            />
          )}
          <VillageColumn
            head="Villages newly lit" dot="mcx-dot--amber"
            why={`Dark in ${base}, clearly lit for the last three years on both of NASA’s yearly composites — ${n0(data?.newly_lit)} villages in all. Most people first.`}
            empty={`None in ${stateLabel}.`}
            items={fresh.slice(0, 12).map((v, i) => ({
              key: `n-${i}`, name: v.name, sub: `${v.lga} LGA · first lit ${v.since_year ?? '—'}`,
              right: `${n0(v.people)} people`,
              spark: <Spark values={v.near_nadir} w={96} h={24} colour={AMBER_TXT} />,
              onClick: () => { setLayersOn((s) => ({ ...s, fresh: true })); setSel({ kind: 'village', list: 'new', i }); },
            }))}
          />
        </section>
      )}
      {gone.length === 0 && (far.length > 0 || fresh.length > 0) && data?.available && (
        <span className="mcx-kpi-src">No village in {stateLabel} went dark: none lit in {base} has been dark for the last three years on both of NASA&rsquo;s yearly composites.</span>
      )}

      <section className="mcx-notes mcx-notes--3">
        <div>
          <span className="mcx-notes-label mcx-notes-label--indigo">Displaced people</span>
          <span>
            IOM counts the displaced people living in each LGA every few months. See their latest figures on
            the{' '}
            <a href={IOM_DTM_NIGERIA} target="_blank" rel="noopener noreferrer">IOM Displacement Tracking Matrix for Nigeria&nbsp;↗</a>
          </span>
        </div>
        <div>
          <span className="mcx-notes-label">How the signals work</span>
          <span>
            Activity fading: light down at least 10% on both of NASA&rsquo;s composites. Farming flat or behind:
            farmland greenness less than 5% above last season on the same ground. Far from care: half or more of
            the people live over an hour&rsquo;s walk from a health facility. A factor not measured never counts.
          </span>
        </div>
        <div>
          <span className="mcx-notes-label">How we report</span>
          <span>
            Light and farmland are measured from space; travel time is modelled on roads, tracks and terrain (Data
            for Children Collaborative, 2024); World Bank prices are model estimates built from market surveys.
            Light tracks activity, not income — it can fall because people left, a grid line or generator stopped,
            or fuel got dearer. We compare three-year averages and show only changes both of NASA&rsquo;s composites
            agree on. People counts come from Meta &amp; CIESIN&rsquo;s population map, which predates recent moves.
            We show where pressure is gathering; people on the ground say why.
          </span>
        </div>
      </section>
      <span className="mcx-credit">
        {GRID3_CREDIT} · Night light: NASA Black Marble VNP46A4 · Population © Meta &amp; CIESIN, CC BY 4.0 · Travel time ©
        Data for Children Collaborative, CC BY 4.0 · Health facilities: GRID3 Nigeria{cp?.facilities_release ? ` ${cp.facilities_release}` : ''},
        CC BY 4.0 · Prices: World Bank Real Time Prices, CC BY 4.0; FEWS NET
      </span>
    </section>
  );
}


function VillageColumn({ head, dot, why, empty, items }: {
  head: string; dot: string; why: string; empty: string;
  items: { key: string; name: string; sub: string; right: string; spark?: ReactNode; onClick: () => void }[];
}) {
  return (
    <div className="mcx-vcol">
      <div className="mcx-vhead">
        <i className={`mcx-dot ${dot}`} />
        <h3 className="mcx-h2">{head}</h3>
      </div>
      <span className="mcx-note">{why}</span>
      {items.length === 0 && empty && <span className="mcx-note">{empty}</span>}
      {/* Up to twelve, scrolling in an even box, so the three columns match. */}
      {items.length > 0 && (
        <div className="mcx-vlist">
          {items.map((it) => (
            <button key={it.key} type="button" className={`mcx-vrow ${it.spark ? '' : 'mcx-vrow--nospark'}`} onClick={it.onClick}>
              <span className="mcx-vrow-main"><b>{it.name}</b><span>{it.sub}</span></span>
              {it.spark}
              <span className="mcx-vrow-people">{it.right}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}


function LgaCompassCard({ r, g, base, prev, since, release, onClose }: {
  r: CompassLga; g: LightTrendLga | undefined; base: string; prev: number | null;
  since: string | null; release: string | null; onClose: () => void;
}) {
  const lg: LightLike = { category: r.light_category, change_pct: r.light_change_pct };
  const sinceTxt = since ? `since ${new Date(`${since}T12:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'long' })}` : 'this season';
  return (
    <HaloCard
      title={`${r.lga} LGA · the compass`}
      big={r.signals.length ? `${r.signals.length} of 3 pressure signals` : 'No pressure signals'}
      chart={g ? (
        <div className="mcx-card-chart">
          <Spark values={g.near_nadir} faint={g.all_angle} w={300} h={54} colour={changeColour(lg)} />
          <div className="mcx-card-axis"><span>{g.years[0]}</span><span>light each year</span><span>{g.years[g.years.length - 1]}</span></div>
        </div>
      ) : undefined}
      rows={[
        { k: 'Activity', v: `${changeText(lg)} light at night since ${base}${g?.gone_dark ? ` · ${n0(g.gone_dark)} villages gone dark` : ''}` },
        { k: 'Farming', v: r.season_pct == null ? 'Not compared — cloud hid too much of one season' : `${signed(r.season_pct)} farmland greenness vs ${prev}, same ground` },
        { k: 'Care', v: r.over_hour_walk_share == null ? 'Travel time not measured here yet'
          : `${Math.round(100 * r.over_hour_walk_share)}% live over an hour's walk from a health facility · median ${duration(r.walk_median_min)} walk, ${duration(r.drive_median_min)} with transport` },
        { k: 'Facilities', v: r.facilities == null ? 'Not in the GRID3 register for this state'
          : `${n0(r.facilities)} health facilities${r.facilities_per_10k != null ? ` · ${r.facilities_per_10k.toFixed(1)} per 10,000 people` : ''} (GRID3 ${release})` },
        { k: 'This season', v: `${plural(r.storms, 'storm')}, ${plural(r.advisories, 'extreme-rain day')} ${sinceTxt}` },
        { k: 'Lives here', v: `${n0(r.people)} people` },
        ...(r.signals.length ? [{ k: 'Signals', v: r.signals.join(' · ') }] : []),
      ]}
      why="Each line is measured separately — light from NASA, farmland from Sentinel-2, travel time modelled on roads and terrain. The signals are a count of those readings, not a score; they show where pressure on livelihoods and services is gathering."
      onClose={onClose}
    />
  );
}


function LgaLightCard({ g, span, onClose }: { g: LightTrendLga; span: string; onClose: () => void }) {
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


function FarCard({ v, onClose }: { v: FarVillage; onClose: () => void }) {
  return (
    <HaloCard
      title={`${v.name} · far from care`}
      big={`${duration(v.walk_min)} walk`}
      rows={[
        { k: 'Where', v: `${v.lga ?? '—'} LGA${v.ward ? ` · ${v.ward} ward` : ''}` },
        { k: 'With transport', v: `${duration(v.drive_min)} to the nearest health facility` },
        { k: 'Lives here', v: `${n0(v.people)} people` },
        { k: 'Location', v: <>{v.location.lat.toFixed(4)}°N {v.location.lon.toFixed(4)}°E · <DirectionsLink lat={v.location.lat} lon={v.location.lon} /></> },
      ]}
      why="Modelled time to the nearest health facility, walking on roads, tracks and open ground (Data for Children Collaborative, 2024). Very long times often mean no roads are mapped here, so confirm on the ground. A first stop for mobile clinics and outreach."
      onClose={onClose}
    />
  );
}
