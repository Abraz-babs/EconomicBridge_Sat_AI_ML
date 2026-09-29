'use client';

/**
 * SkillsBridge's school reach list — the redesigned view (operator-approved
 * mock, 2026-09-26): every mapped school, whether any village within 2 km
 * shows light at night, and how many people and young children live in its
 * village; ranked to show the schools to power and connect first.
 *
 * Schools: GRID3 school register (CC BY 4.0). Light: NASA VIIRS Black Marble
 * at GRID3 villages. People: Meta & CIESIN HRSL. Light seen from space is not
 * a school's own supply — "no light within 2 km" is a lead for a visit.
 */

import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { GeoJsonLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers';

import EBMap from '@/components/map/EBMap';
import HaloCard from '@/components/map/HaloCard';
import MapToolbar from '@/components/map/MapToolbar';
import ModuleSources from '@/components/common/ModuleSources';
import { DirectionsLink } from '@/components/common/FieldDirections';
import { BASEMAP_STYLE, fillAlpha, type Basemap } from '@/components/map/basemaps';
import type { Tenant } from '@/data/tenants';
import { useLgaBoundaries } from '@/hooks/useLgaBoundaries';
import { useSchoolReach, type ReachLga, type ReachSchool } from '@/hooks/useSchoolReach';
import { useVillageLight, type VillagePoint } from '@/hooks/useVillageLight';

const BLUE: [number, number, number] = [37, 86, 163];
const NIGHT: [number, number, number] = [42, 49, 64];
const NIGHT_ON_DARK: [number, number, number] = [170, 180, 195];
const AMBER: [number, number, number] = [224, 162, 31];
const GREY: [number, number, number] = [154, 160, 166];
const PAGE = 25;
const HALOS = 10;

// Share of schools with no light nearby, pale to night.
function shareRgb(pct: number): [number, number, number] {
  const t = Math.max(0, Math.min(1, pct / 100));
  const a = [236, 238, 232];
  return [0, 1, 2].map((k) => Math.round(a[k] + (NIGHT[k] - a[k]) * t)) as [number, number, number];
}

const n0 = (v: number | null | undefined) => (v == null ? '—' : Math.round(v).toLocaleString('en-US'));
const thousands = (v: number) => (v >= 1e6 ? `${(v / 1e6).toFixed(2)}M` : v >= 1e4 ? `${Math.round(v / 1e3)}K` : n0(v));

const FRACTIONS: [number, string][] = [
  [90, 'Nine in ten'], [80, 'Four in five'], [75, 'Three in four'], [67, 'Two in three'],
  [60, 'Three in five'], [50, 'Half'], [40, 'Two in five'], [33, 'One in three'],
  [25, 'One in four'], [20, 'One in five'], [10, 'One in ten'],
];

function shareWords(pct: number): string {
  const best = FRACTIONS.reduce((a, b) => (Math.abs(b[0] - pct) < Math.abs(a[0] - pct) ? b : a));
  return Math.abs(best[0] - pct) <= 2.5 ? best[1] : `${Math.round(pct)}%`;
}

function possessive(stateLabel: string): string {
  if (/capital territory/i.test(stateLabel)) return "the FCT's";
  return `${stateLabel.replace(/ State$/, '')}'s`;
}

function schoolKind(s: ReachSchool): string {
  return [s.category, s.management].filter(Boolean).join(' · ');
}

type Sel = { kind: 'school'; i: number } | { kind: 'lga'; lga: string } | null;


export default function SchoolReach({ tenant, stateLabel }: { tenant: Tenant; stateLabel: string }) {
  const reach = useSchoolReach(tenant.id);
  const lgasQ = useLgaBoundaries(tenant.id);
  const [basemap, setBasemap] = useState<Basemap>('light');
  const [layersOn, setLayersOn] = useState({ schools: true, reach: true, share: false, villages: false });
  const villageQ = useVillageLight(layersOn.villages ? tenant.id : '');
  const [sel, setSel] = useState<Sel>(null);
  const [lgaFilter, setLgaFilter] = useState<string | null>(null);
  // Selection and LGA filter belong to this state's data — drop both when the
  // state changes, or the card would land on an unrelated school.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSel(null);
    setLgaFilter(null);
  }, [tenant.id]);
  const [shown, setShown] = useState(PAGE);

  const data = reach.data;
  const rows = useMemo(() => data?.rows ?? [], [data]);
  const lgas = useMemo(() => data?.lgas ?? [], [data]);
  const byLga = useMemo(() => new Map(lgas.map((g) => [g.lga, g])), [lgas]);
  const ranked = useMemo(
    () => rows.map((s, i) => ({ s, i })).filter((x) => x.s.rank != null)
      .sort((a, b) => (a.s.rank ?? 0) - (b.s.rank ?? 0)),
    [rows],
  );
  const list = useMemo(
    () => (lgaFilter ? ranked.filter((x) => x.s.lga === lgaFilter) : ranked),
    [ranked, lgaFilter],
  );
  const halos = useMemo(() => list.slice(0, HALOS).map((x, k) => ({ ...x, n: k + 1 })), [list]);
  const villagePts = useMemo(() => villageQ.data?.points ?? [], [villageQ.data]);
  const schoolPts = useMemo(() => rows.map((s, i) => ({ s, i })), [rows]);

  const dark = basemap !== 'light';
  const alpha = fillAlpha(basemap);
  const selI = sel?.kind === 'school' ? sel.i : -1;

  const layers = useMemo(() => {
    const out: unknown[] = [];
    if (layersOn.share && lgasQ.data) {
      out.push(new GeoJsonLayer({
        id: 'skr-share',
        data: lgasQ.data as never,
        filled: true,
        stroked: true,
        pickable: true,
        getFillColor: (f: { properties: { lga: string } }) => {
          const p = byLga.get(f.properties.lga)?.dark_pct;
          return p == null ? [140, 140, 140, 40] : [...shareRgb(p), alpha];
        },
        getLineColor: (f: { properties: { lga: string } }) =>
          (f.properties.lga === lgaFilter ? [...BLUE, 255] : [255, 255, 255, 190]),
        getLineWidth: (f: { properties: { lga: string } }) => (f.properties.lga === lgaFilter ? 3 : 1),
        lineWidthUnits: 'pixels',
        onClick: (info: { object?: { properties: { lga: string } } }) => {
          const lga = info.object?.properties.lga;
          if (lga) { setSel({ kind: 'lga', lga }); setLgaFilter(lga); setShown(PAGE); }
        },
        updateTriggers: { getFillColor: [byLga, alpha], getLineColor: [lgaFilter], getLineWidth: [lgaFilter] },
      }));
    }
    if (layersOn.villages && villagePts.length) {
      out.push(new ScatterplotLayer({
        id: 'skr-villages',
        data: villagePts,
        getPosition: (v: VillagePoint) => [v[0], v[1]],
        // 0 unlit · 1 dim · 2 lit · 3 unknown
        getFillColor: (v: VillagePoint) => (v[2] === 2 ? [...AMBER, 235] : v[2] === 1 ? [...AMBER, 150]
          : dark ? [120, 130, 145, 70] : [90, 98, 110, 55]),
        getRadius: (v: VillagePoint) => (v[2] === 2 ? 3.5 : v[2] === 1 ? 2.5 : 1.5),
        radiusUnits: 'pixels',
        pickable: false,
        updateTriggers: { getFillColor: [dark] },
      }));
    }
    if (layersOn.schools && rows.length) {
      out.push(new ScatterplotLayer({
        id: 'skr-schools',
        data: schoolPts,
        getPosition: (x: { s: ReachSchool }) => [x.s.location.lon, x.s.location.lat],
        getFillColor: (x: { s: ReachSchool }) => [
          ...(x.s.light === 'lit' ? AMBER : x.s.light === 'dark' ? (dark ? NIGHT_ON_DARK : NIGHT) : GREY), 235,
        ],
        getLineColor: dark ? [13, 20, 27, 200] : [255, 255, 255, 220],
        stroked: true,
        lineWidthMinPixels: 1,
        getRadius: (x: { i: number }) => (x.i === selI ? 7 : 3.5),
        radiusUnits: 'pixels',
        pickable: true,
        onClick: (info: { object?: { i: number } }) => {
          if (info.object) setSel({ kind: 'school', i: info.object.i });
        },
        updateTriggers: { getFillColor: [dark], getLineColor: [dark], getRadius: [selI] },
      }));
    }
    if (layersOn.reach && halos.length) {
      out.push(new ScatterplotLayer({
        id: 'skr-reach-halo',
        data: halos,
        getPosition: (x: { s: ReachSchool }) => [x.s.location.lon, x.s.location.lat],
        getFillColor: (x: { i: number }) => [...BLUE, x.i === selI ? 90 : 45],
        getRadius: (x: { i: number }) => (x.i === selI ? 22 : 17),
        radiusUnits: 'pixels',
        pickable: false,
        updateTriggers: { getFillColor: [selI], getRadius: [selI] },
      }));
      out.push(new ScatterplotLayer({
        id: 'skr-reach-core',
        data: halos,
        getPosition: (x: { s: ReachSchool }) => [x.s.location.lon, x.s.location.lat],
        getFillColor: [...BLUE, 255],
        getLineColor: [255, 255, 255, 245],
        stroked: true,
        lineWidthMinPixels: 2,
        getRadius: 10,
        radiusUnits: 'pixels',
        pickable: true,
        onClick: (info: { object?: { i: number } }) => {
          if (info.object) setSel({ kind: 'school', i: info.object.i });
        },
      }));
      out.push(new TextLayer({
        id: 'skr-reach-num',
        data: halos,
        getPosition: (x: { s: ReachSchool }) => [x.s.location.lon, x.s.location.lat],
        getText: (x: { n: number }) => String(x.n),
        getColor: [255, 255, 255, 255],
        getSize: 11,
        fontWeight: 600,
        fontFamily: 'system-ui, sans-serif',
        characterSet: '0123456789',
        getTextAnchor: 'middle',
        getAlignmentBaseline: 'center',
        pickable: false,
      }));
    }
    return out;
  }, [layersOn, lgasQ.data, byLga, alpha, lgaFilter, villagePts, dark, rows, schoolPts, selI, halos]);

  // The pinned card for whatever is selected.
  let card: { lng: number; lat: number; node: ReactNode } | null = null;
  if (sel?.kind === 'school' && rows[sel.i]) {
    const s = rows[sel.i];
    card = {
      lng: s.location.lon, lat: s.location.lat,
      node: <SchoolCard s={s} total={ranked.length} onClose={() => setSel(null)} />,
    };
  } else if (sel?.kind === 'lga') {
    const g = byLga.get(sel.lga);
    const inLga = rows.filter((s) => s.lga === sel.lga);
    if (g && inLga.length) {
      const lon = inLga.reduce((a, s) => a + s.location.lon, 0) / inLga.length;
      const lat = inLga.reduce((a, s) => a + s.location.lat, 0) / inLga.length;
      const onList = ranked.filter((x) => x.s.lga === sel.lga);
      card = {
        lng: lon, lat,
        node: (
          <HaloCard
            title={`${sel.lga} · schools with no light within 2 km`}
            big={g.dark_pct != null ? `${Math.round(g.dark_pct)}% of schools` : undefined}
            rows={[
              { k: 'Schools mapped', v: `${n0(g.schools)} · ${n0(g.assessed)} with a village within 2 km` },
              { k: 'No light in 2 km', v: `${n0(g.dark)} schools` },
              { k: 'Reach list', v: `${n0(onList.length)} villages · ${n0(onList.reduce((a, x) => a + (x.s.people ?? 0), 0))} people` },
            ]}
            why="The list beside the map now shows this LGA only. Light is read at the villages within 2 km of each school."
            onClose={() => setSel(null)}
          />
        ),
      };
    }
  }

  // The darkest LGA with enough schools for the share to mean something.
  const darkest = lgas.find((g) => g.assessed >= 10 && g.dark_pct != null) ?? lgas[0];
  const half = Math.ceil(lgas.length / 2);

  if (data && !data.available) {
    return (
      <section className="skr" aria-labelledby="skr-title">
        <div className="skr-head-main">
          <span className="skr-eyebrow">SkillsBridge · {stateLabel} · School reach list</span>
          <h2 id="skr-title" className="skr-h1">The school reach list is not available for {stateLabel} yet.</h2>
          <p className="skr-sub">{data.reason}</p>
        </div>
      </section>
    );
  }

  return (
    <section className="skr" aria-labelledby="skr-title">
      <div className="skr-head">
        <div className="skr-head-main">
          <span className="skr-eyebrow">SkillsBridge · {stateLabel} · School reach list</span>
          <h2 id="skr-title" className="skr-h1">
            {reach.isLoading || !data ? 'Reading the school register…'
              : data.dark_pct == null ? `${n0(data.schools)} schools mapped in ${stateLabel}.`
                : `${shareWords(data.dark_pct)} of ${possessive(stateLabel)} mapped schools have no light at night within 2 km.`}
          </h2>
          <p className="skr-sub">
            {data ? `${n0(data.schools)} schools` : 'Every school'} from the GRID3 school register, each checked
            against NASA VIIRS night light at the villages around it, and the people who live there.
          </p>
        </div>
        <div className="skr-head-side">
          <span className="skr-chip">
            GRID3 SCHOOLS · NASA VIIRS{data?.light_round ? ` ${data.light_round}` : ''} · META &amp; CIESIN
          </span>
          <ModuleSources sources={[
            { name: 'GRID3', role: 'school register with LGA names, village names' },
            { name: 'NASA VIIRS Black Marble', role: 'light at villages within 2 km' },
            { name: 'Meta & CIESIN HRSL', role: 'people and under-fives' },
          ]} />
        </div>
      </div>

      {reach.isError && <div className="fp-alert-error">Could not load the school register: {reach.error?.message ?? 'unknown'}</div>}

      {data?.available && (
        <div className="skr-kpis">
          <div className="skr-kpi">
            <span className="skr-kpi-val skr-kpi-val--blue">{n0(data.schools)}</span>
            <span className="skr-kpi-label">schools mapped — {n0(data.primary)} primary, {n0(data.secondary)} secondary</span>
            <span className="skr-kpi-src">GRID3 school register</span>
          </div>
          <div className="skr-kpi">
            <span className="skr-kpi-val">{n0(data.dark)}</span>
            <span className="skr-kpi-label">
              with no light at night within 2 km{data.dark_pct != null ? ` — ${Math.round(data.dark_pct)}%` : ''}
            </span>
            <span className="skr-kpi-src">NASA VIIRS Black Marble{data.light_round ? `, ${data.light_round} round` : ''}</span>
          </div>
          <div className="skr-kpi">
            <span className="skr-kpi-val">{thousands(data.people)}</span>
            <span className="skr-kpi-label">people in those schools&rsquo; villages — {thousands(data.under5)} under five</span>
            <span className="skr-kpi-src">Meta &amp; CIESIN population · {n0(data.dark_villages)} villages</span>
          </div>
          {darkest?.dark_pct != null && (
            <div className="skr-kpi">
              <span className="skr-kpi-val">{Math.round(darkest.dark_pct)}%</span>
              <span className="skr-kpi-label">
                of {darkest.lga}&rsquo;s {n0(darkest.assessed)} schools
                {darkest.dark === darkest.assessed ? ' — every one without light nearby' : ' have no light nearby'}
              </span>
              <span className="skr-kpi-src">The darkest LGA</span>
            </div>
          )}
        </div>
      )}

      <div className="skr-main">
        <div className="skr-mapcol">
          <MapToolbar
            basemap={basemap}
            onBasemap={setBasemap}
            layers={[
              { id: 'schools', label: 'All schools', dot: '#2a3140', on: layersOn.schools },
              { id: 'reach', label: 'Reach list', dot: '#2556a3', on: layersOn.reach },
              { id: 'share', label: 'Share by LGA', dot: '#6b7384', on: layersOn.share },
              { id: 'villages', label: 'Night light at villages', dot: '#e0a21f', on: layersOn.villages },
            ]}
            onToggle={(id) => setLayersOn((s) => ({ ...s, [id]: !s[id as keyof typeof s] }))}
          />
          <EBMap
            tenant={tenant}
            layers={layers}
            height="600px"
            zoom={6.6}
            mapStyle={BASEMAP_STYLE[basemap]}
            ariaLabel={`${stateLabel} schools, marked by whether any village within 2 km shows light at night`}
            getTooltip={(o) => {
              const f = o as { properties?: { lga: string }; s?: ReachSchool };
              if (f?.s) {
                const l = f.s.light === 'dark' ? 'no light within 2 km' : f.s.light === 'lit' ? 'light nearby' : 'not assessed';
                return `${f.s.name}\n${f.s.lga ?? ''} · ${l}\nClick for detail`;
              }
              if (f?.properties?.lga) {
                const g = byLga.get(f.properties.lga);
                return `${f.properties.lga} · ${g?.dark_pct != null ? `${Math.round(g.dark_pct)}%` : '—'} of schools with no light nearby\nClick to list them`;
              }
              return null;
            }}
            card={card}
          />
          <div className="skr-legend">
            <span><i className="skr-dot skr-dot--night" /> No light within 2 km</span>
            <span><i className="skr-dot skr-dot--amber" /> Light nearby</span>
            <span><i className="skr-dot skr-dot--grey" /> No village within 2 km</span>
            <span><i className="skr-num">1</i> Reach list</span>
            {layersOn.share && <span><i className="skr-ramp" /> 0 → 100% of schools with no light nearby</span>}
          </div>
        </div>

        <div className="skr-side">
          <div className="skr-side-head">
            <h3 className="skr-h2">Schools to power and connect first</h3>
            {lgaFilter && (
              <button type="button" className="skr-filter" onClick={() => { setLgaFilter(null); setShown(PAGE); }}>
                {lgaFilter} only · show all
              </button>
            )}
          </div>
          <p className="skr-note">
            Ranked by the people living in the school&rsquo;s village — one school per village.
            {' '}{n0(list.length)} {lgaFilter ? `in ${lgaFilter}` : 'in all'}.
          </p>
          <div className="skr-list" role="list">
            {list.slice(0, shown).map(({ s, i }, k) => (
              <div key={`${s.name}-${i}`} role="listitem" className={`skr-row ${selI === i ? 'is-sel' : ''}`}>
                <span className={`skr-rank ${k < HALOS ? 'is-halo' : ''}`}>{k + 1}</span>
                <div className="skr-row-main">
                  <button type="button" className="skr-row-name" onClick={() => setSel({ kind: 'school', i })}>{s.name}</button>
                  <span className="skr-row-body">
                    {schoolKind(s)} · {s.lga} LGA{s.village ? ` · in ${s.village}${s.ward ? ` (${s.ward} ward)` : ''}` : ''}
                  </span>
                  <span className="skr-row-meta">
                    {s.location.lat.toFixed(4)}°N {s.location.lon.toFixed(4)}°E · <DirectionsLink lat={s.location.lat} lon={s.location.lon} />
                  </span>
                </div>
                <div className="skr-row-side">
                  <span className="skr-tag">NO LIGHT WITHIN 2 KM</span>
                  <span className="skr-row-people"><span>{n0(s.people)} people</span><span>{n0(s.under5)} under five</span></span>
                </div>
              </div>
            ))}
            {list.length > shown && (
              <button type="button" className="skr-more" onClick={() => setShown((v) => v + PAGE)}>
                Show {Math.min(PAGE, list.length - shown)} more of {n0(list.length - shown)}
              </button>
            )}
          </div>
          <span className="skr-credit">Schools and village names © GRID3, CC BY 4.0 · Population © Meta &amp; CIESIN, CC BY 4.0</span>
        </div>
      </div>

      {lgas.length > 0 && (
        <section className="skr-block">
          <div className="skr-block-head">
            <h3 className="skr-h2">By LGA — schools with no light within 2 km</h3>
            <span className="skr-kpi-src">Darkest first · click an LGA to list its schools</span>
          </div>
          <div className="skr-lgas">
            {[lgas.slice(0, half), lgas.slice(half)].map((col, c) => (
              <div key={c}>
                {col.map((g) => <LgaRow key={g.lga} g={g} on={g.lga === lgaFilter} onPick={() => {
                  setLgaFilter(g.lga); setSel({ kind: 'lga', lga: g.lga }); setShown(PAGE);
                }} />)}
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="skr-notes">
        <div>
          <span className="skr-notes-label skr-notes-label--blue">Next — connectivity per school</span>
          <span>Each school&rsquo;s measured connection joins the list once UNICEF enables GIGA school-connectivity data on our key.</span>
        </div>
        <div>
          <span className="skr-notes-label">How we report</span>
          <span>
            Light is read at the villages within 2 km of each school; a school in a lit town is not counted dark.
            Light seen from space is not the school&rsquo;s own supply — a visit confirms it. Enrolment is not
            shown until a source publishes it.
          </span>
        </div>
      </section>
    </section>
  );
}


function LgaRow({ g, on, onPick }: { g: ReachLga; on: boolean; onPick: () => void }) {
  return (
    <button type="button" className={`skr-lga ${on ? 'is-on' : ''}`} onClick={onPick}>
      <span className="skr-lga-name">{g.lga}</span>
      <span className="skr-lga-count">{g.dark}/{g.assessed}</span>
      <span className="skr-lga-bar"><span style={{ width: `${g.dark_pct ?? 0}%` }} /></span>
      <span className="skr-lga-pct">{g.dark_pct != null ? `${Math.round(g.dark_pct)}%` : '—'}</span>
    </button>
  );
}


function SchoolCard({ s, total, onClose }: { s: ReachSchool; total: number; onClose: () => void }) {
  const big = s.light === 'dark' ? 'No light within 2 km' : s.light === 'lit' ? 'Light nearby' : 'Not assessed';
  const why = s.light === 'dark'
    ? 'No village within 2 km shows light the satellite can detect, so this school is among the likeliest to need solar power before a connection. Light seen from space is not the school’s own supply — a visit confirms it.'
    : s.light === 'lit'
      ? 'At least one village within 2 km shows light at night, so grid or generator power is likely close by.'
      : 'No named village lies within 2 km, so light and population were not read for this school.';
  return (
    <HaloCard
      title={s.name}
      big={big}
      rows={[
        { k: 'School', v: `${schoolKind(s) || '—'} · ${s.lga ?? '—'} LGA` },
        ...(s.village ? [{ k: 'Its village', v: `${s.village}${s.ward ? `, ${s.ward} ward` : ''} · ${s.village_km?.toFixed(2) ?? '—'} km · ${s.village_light ?? '—'}` }] : []),
        ...(s.people != null ? [{ k: 'Living there', v: `${n0(s.people)} people · ${n0(s.under5)} under five` }] : []),
        ...(s.villages_2km ? [{ k: 'Within 2 km', v: `${s.villages_2km} village${s.villages_2km === 1 ? '' : 's'}, ${s.lit_villages_2km} lit · ${n0(s.people_2km)} people, ${n0(s.under5_2km)} under five` }] : []),
        ...(s.rank != null ? [{ k: 'Reach list', v: `No. ${n0(s.rank)} of ${n0(total)}` }] : []),
        { k: 'Location', v: <>{s.location.lat.toFixed(4)}°N {s.location.lon.toFixed(4)}°E · <DirectionsLink lat={s.location.lat} lon={s.location.lon} /></> },
      ]}
      why={why}
      onClose={onClose}
    />
  );
}
