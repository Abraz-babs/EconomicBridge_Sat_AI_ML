'use client';

/**
 * ShockGuard's storm day — the redesigned view (operator-approved mock,
 * 2026-09-26): where extreme rain fell on one day, who lives under it, what
 * happened there before, and whether farmers were told. The "Recorded &
 * detected" layer puts the disaster register (cited) and the live detections
 * back on the map, as the earlier events map did.
 *
 * Rain is measured (NASA GPM IMERG, half-hourly, graded against each LGA's own
 * record); people and villages come from the village layer (GRID3 · VIIRS ·
 * HRSL). It reports rain and exposure, never a flood — flooding is confirmed on
 * the ground.
 */

import { useMemo, useState } from 'react';
import { GeoJsonLayer, ScatterplotLayer } from '@deck.gl/layers';

import EBMap from '@/components/map/EBMap';
import { DirectionsLink } from '@/components/common/FieldDirections';
import HaloCard from '@/components/map/HaloCard';
import MapToolbar from '@/components/map/MapToolbar';
import ModuleSources from '@/components/common/ModuleSources';
import { BASEMAP_STYLE, fillAlpha, type Basemap } from '@/components/map/basemaps';
import type { Tenant } from '@/data/tenants';
import { useLgaBoundaries } from '@/hooks/useLgaBoundaries';
import { useVillageLight } from '@/hooks/useVillageLight';
import {
  impactRainMm,
  useStormImpact,
  type ImpactRow,
  type ShockEventRow,
} from '@/hooks/useShockGuard';
import { eventLabel, hazardStyle, isRecordedEvent } from './hazard';

/** Approved wording for the vegetation drought check (2026-08 validation):
 *  weak, consistent, and never an accuracy figure. */
export const DROUGHT_SENTENCE =
  'Flagged LGAs are consistently drier than their own seasonal normal, though the relationship is weak and does not strengthen with accumulated deficit as a purely rainfall-driven signal would.';

const INSTRUMENT: Record<string, string> = {
  shockguard_scan_v1: 'Sentinel-1 radar / Sentinel-2 greenness',
  rainstorm_scan_v1: 'NASA GPM IMERG daily rainfall',
  storm_scan_v1: 'NASA GPM IMERG half-hourly rainfall',
  sentinel1_unet_v1: 'Sentinel-1 radar (U-Net)',
};

const TZ = 'Africa/Lagos';
const RAIN_RAMP: [number, number, number][] = [
  [31, 79, 124], [47, 120, 192], [93, 99, 207], [161, 94, 214],
];
const AMBER: [number, number, number] = [242, 181, 74];

function rainRgb(mm: number): [number, number, number] {
  const t = Math.max(0, Math.min(1, (mm - 20) / 85));
  const n = RAIN_RAMP.length - 1;
  const i = Math.min(Math.floor(t * n), n - 1);
  const f = t * n - i;
  const a = RAIN_RAMP[i];
  const b = RAIN_RAMP[i + 1];
  return [0, 1, 2].map((k) => Math.round(a[k] + (b[k] - a[k]) * f)) as [number, number, number];
}

const n0 = (v: number) => v.toLocaleString('en-US');

function dayLong(d: string): string {
  return new Date(`${d}T12:00:00+01:00`).toLocaleDateString('en-GB', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: TZ,
  });
}

function dayShort(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: TZ });
}

function hm(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: TZ });
}

/** Hours after local midnight of `day` (WAT is UTC+1 all year). */
function hoursInto(day: string, iso: string): number {
  return (Date.parse(iso) - Date.parse(`${day}T00:00:00+01:00`)) / 3_600_000;
}

function millions(v: number): string {
  return v >= 1_000_000 ? `${(v / 1_000_000).toFixed(2)} million` : n0(v);
}


export default function StormDayView({ tenant, stateLabel, events = [] }: {
  tenant: Tenant; stateLabel: string; events?: ShockEventRow[];
}) {
  const [day, setDay] = useState<string | null>(null);
  const impact = useStormImpact(tenant.id, day);
  const villagesQ = useVillageLight(tenant.id);
  const lgasQ = useLgaBoundaries(tenant.id);

  const [basemap, setBasemap] = useState<Basemap>('dark');
  const [layersOn, setLayersOn] = useState({ rain: true, villages: true, storms: true, record: true });
  const [selected, setSelected] = useState<string | null>(null);
  const [selEvent, setSelEvent] = useState<string | null>(null);
  const pinned = useMemo(() => events.filter((e) => e.location), [events]);
  const pickLga = (lga: string | null) => { setSelEvent(null); setSelected(lga); };

  const data = impact.data;
  const rows = useMemo(() => data?.rows ?? [], [data]);
  const shownDay = data?.day ?? null;
  const rainBy = useMemo(() => new Map(rows.map((r) => [r.lga, impactRainMm(r)])), [rows]);
  const sel: ImpactRow | null = useMemo(
    () => rows.find((r) => r.lga === selected) ?? null, [rows, selected],
  );

  const onDark = basemap !== 'light';
  const layers = useMemo(() => {
    const out: unknown[] = [];
    const alpha = fillAlpha(basemap);
    if (layersOn.rain && lgasQ.data) {
      out.push(new GeoJsonLayer({
        id: 'sg-rain',
        data: lgasQ.data as never,
        filled: true,
        stroked: true,
        pickable: true,
        getFillColor: (f: { properties: { lga: string } }) => {
          const mm = rainBy.get(f.properties.lga);
          return mm ? [...rainRgb(mm), alpha] : [0, 0, 0, 0];
        },
        getLineColor: onDark ? [255, 255, 255, 70] : [60, 70, 80, 90],
        lineWidthMinPixels: 1,
        onClick: (info: { object?: { properties: { lga: string } } }) => {
          const lga = info.object?.properties.lga;
          if (lga && rainBy.has(lga)) pickLga(lga);
        },
        updateTriggers: { getFillColor: [rainBy, alpha], getLineColor: [onDark] },
      }));
    }
    if (layersOn.villages && villagesQ.data?.points?.length) {
      out.push(new ScatterplotLayer({
        id: 'sg-villages',
        data: villagesQ.data.points,
        getPosition: (p: number[]) => [p[0], p[1]],
        getFillColor: (p: number[]) => (p[3] >= 1 && p[3] <= 2
          ? [255, 196, 102, 230]
          : onDark ? [214, 224, 234, 95] : [70, 80, 92, 110]),
        getRadius: (p: number[]) => (p[3] >= 1 && p[3] <= 2 ? 2.2 : 1.2),
        radiusUnits: 'pixels',
        pickable: false,
        updateTriggers: { getFillColor: [onDark] },
      }));
    }
    if (layersOn.storms) {
      const pins = rows.filter((r) => r.location);
      out.push(new ScatterplotLayer({
        id: 'sg-storm-halo',
        data: pins,
        getPosition: (r: ImpactRow) => [r.location!.lon, r.location!.lat],
        getFillColor: (r: ImpactRow) => [...AMBER, r.lga === selected ? 110 : 55],
        getRadius: (r: ImpactRow) => 14 + impactRainMm(r) / 5 + (r.lga === selected ? 8 : 0),
        radiusUnits: 'pixels',
        pickable: false,
        updateTriggers: { getFillColor: [selected], getRadius: [selected] },
      }));
      out.push(new ScatterplotLayer({
        id: 'sg-storm-core',
        data: pins,
        getPosition: (r: ImpactRow) => [r.location!.lon, r.location!.lat],
        getFillColor: [...AMBER, 255],
        getLineColor: [255, 255, 255, 235],
        stroked: true,
        lineWidthMinPixels: 2,
        getRadius: (r: ImpactRow) => 5 + impactRainMm(r) / 18,
        radiusUnits: 'pixels',
        pickable: true,
        onClick: (info: { object?: ImpactRow }) => {
          if (info.object) pickLga(info.object.lga);
        },
      }));
    }
    if (layersOn.record && pinned.length) {
      // Recorded disasters (cited) are hollow rings; live detections are solid.
      out.push(new ScatterplotLayer({
        id: 'sg-record-halo',
        data: pinned,
        getPosition: (e: ShockEventRow) => [e.location!.lon, e.location!.lat],
        getFillColor: (e: ShockEventRow) => [...hazardStyle(e.event_type).rgb, e.id === selEvent ? 110 : 45],
        getRadius: (e: ShockEventRow) => (e.id === selEvent ? 20 : 13),
        radiusUnits: 'pixels',
        pickable: false,
        updateTriggers: { getFillColor: [selEvent], getRadius: [selEvent] },
      }));
      out.push(new ScatterplotLayer({
        id: 'sg-record-core',
        data: pinned,
        getPosition: (e: ShockEventRow) => [e.location!.lon, e.location!.lat],
        getFillColor: (e: ShockEventRow) => (isRecordedEvent(e.source)
          ? [255, 255, 255, 235] : [...hazardStyle(e.event_type).rgb, 255]),
        getLineColor: (e: ShockEventRow) => [...hazardStyle(e.event_type).rgb, 255],
        stroked: true,
        lineWidthMinPixels: 2.5,
        getRadius: 6,
        radiusUnits: 'pixels',
        pickable: true,
        onClick: (info: { object?: ShockEventRow }) => {
          if (info.object) { setSelected(null); setSelEvent(info.object.id); }
        },
      }));
    }
    return out;
  }, [basemap, layersOn, lgasQ.data, villagesQ.data, rows, rainBy, selected, onDark, pinned, selEvent]);

  const heaviest = rows[0];
  const sharedTop = rows.filter((r) => heaviest && Math.abs(impactRainMm(r) - impactRainMm(heaviest)) < 0.05);
  const smsRow = rows.find((r) => (r.sms_recipients ?? 0) > 0);

  const evSel = selEvent ? pinned.find((e) => e.id === selEvent) ?? null : null;
  const card = evSel?.location ? {
    lng: evSel.location.lon,
    lat: evSel.location.lat,
    node: <EventCard ev={evSel} stateLabel={stateLabel} onClose={() => setSelEvent(null)} />,
  } : sel?.location ? {
    lng: sel.location.lon,
    lat: sel.location.lat,
    node: <ImpactCard row={sel} onClose={() => setSelected(null)} />,
  } : null;

  const timeline = rows.filter((r) => r.storm && shownDay)
    .sort((a, b) => Date.parse(a.storm!.started_at) - Date.parse(b.storm!.started_at));

  return (
    <section className="sgr" aria-labelledby="sgr-title">
      <div className="sgr-head">
        <div className="sgr-head-main">
          <span className="sgr-eyebrow">
            ShockGuard · {stateLabel}{shownDay ? ` · ${dayLong(shownDay)}` : ''}
          </span>
          <h2 id="sgr-title" className="sgr-h1">
            {impact.isLoading ? 'Reading the storm record…'
              : rows.length
                ? <>Extreme rain over {rows.length} LGA{rows.length === 1 ? '' : 's'}{data && data.people > 0 ? <> where {millions(data.people)} people live.</> : '.'}</>
                : <>No extreme rain recorded recently — every LGA is watched every half hour.</>}
          </h2>
          <p className="sgr-sub">
            Rain measured every half hour by NASA GPM IMERG and graded against each LGA&rsquo;s
            own record. We report the rain and who lives under it — whether a place flooded is
            confirmed on the ground.
          </p>
          <ModuleSources sources={[
            { name: 'NASA GPM IMERG', role: 'rainfall, every half hour' },
            { name: 'Meta & CIESIN HRSL', role: 'people and under-fives' },
            { name: 'GRID3 · NASA VIIRS', role: 'villages and light at night' },
            { name: 'NEMA · IOM DTM · press', role: 'recorded disasters' },
            { name: 'Copernicus Sentinel-1', role: 'radar surface-water check, experimental' },
          ]} />
        </div>
        <div className="sgr-head-side">
          <span className="sgr-chip">LIVE · NASA GPM IMERG · HALF-HOURLY</span>
          {data && data.days_available.length > 1 && (
            <label className="sgr-day">
              Storm day
              <select value={shownDay ?? ''} onChange={(e) => { setDay(e.target.value); pickLga(null); }}>
                {data.days_available.map((d) => <option key={d} value={d}>{dayLong(d)}</option>)}
              </select>
            </label>
          )}
        </div>
      </div>

      {impact.isError && (
        <div className="fp-alert-error">Could not load the storm day: {impact.error?.message ?? 'unknown'}</div>
      )}

      {rows.length > 0 && data && (
        <div className="sgr-kpis">
          <div className="sgr-kpi">
            <span className="sgr-kpi-val sgr-kpi-val--violet">{impactRainMm(heaviest).toFixed(0)} mm</span>
            <span className="sgr-kpi-label">heaviest — {sharedTop.map((r) => r.lga).join(' and ')}</span>
            <span className="sgr-kpi-src">Rain in the day · NASA GPM IMERG</span>
          </div>
          <div className="sgr-kpi">
            <span className="sgr-kpi-val">{data.people >= 1_000_000 ? `${(data.people / 1e6).toFixed(2)}M` : n0(data.people)}</span>
            <span className="sgr-kpi-label">people live in these LGAs — {n0(Math.round(data.under5 / 1000))}K under five</span>
            <span className="sgr-kpi-src">Meta &amp; CIESIN population</span>
          </div>
          <div className="sgr-kpi">
            <span className="sgr-kpi-val">{n0(data.villages)}</span>
            <span className="sgr-kpi-label">named villages under the rain, {n0(data.dark_villages)} dark at night</span>
            <span className="sgr-kpi-src">GRID3 · NASA VIIRS</span>
          </div>
          <div className="sgr-kpi">
            <span className="sgr-kpi-val">{smsRow ? n0(smsRow.sms_recipients ?? 0) : '0'}</span>
            <span className="sgr-kpi-label">
              {smsRow
                ? <>farmer leaders advised by SMS — {smsRow.lga}{smsRow.sms_sent_at ? `, ${dayShort(smsRow.sms_sent_at)}` : ''}</>
                : <>farmer leaders advised by SMS for this day</>}
            </span>
            <span className="sgr-kpi-src">Each in Hausa or English · one advisory a day</span>
          </div>
        </div>
      )}

      <div className="sgr-main">
        <div className="sgr-mapcol">
          <MapToolbar
            tone="dark"
            basemap={basemap}
            onBasemap={setBasemap}
            layers={[
              { id: 'rain', label: shownDay ? `Rain on ${dayShort(`${shownDay}T12:00:00+01:00`)}` : 'Rain', dot: '#5d63cf', on: layersOn.rain },
              { id: 'villages', label: 'Villages', dot: '#d2dee9', on: layersOn.villages },
              { id: 'storms', label: 'Storm LGAs', dot: '#f2b54a', on: layersOn.storms },
              ...(pinned.length ? [{ id: 'record', label: 'Recorded & detected', dot: '#e8edf2', on: layersOn.record }] : []),
            ]}
            onToggle={(id) => setLayersOn((s) => ({ ...s, [id]: !s[id as keyof typeof s] }))}
          />
          <EBMap
            tenant={tenant}
            layers={layers}
            height="560px"
            zoom={6.6}
            mapStyle={BASEMAP_STYLE[basemap]}
            ariaLabel={`Rain and storms over ${stateLabel}`}
            getTooltip={(o) => {
              const r = o as ImpactRow & { properties?: { lga: string } };
              if (r?.properties?.lga) {
                const mm = rainBy.get(r.properties.lga);
                return mm ? `${r.properties.lga} · ${mm.toFixed(0)} mm\nClick for detail` : null;
              }
              const ev = o as ShockEventRow;
              if (ev?.event_type && ev?.id) {
                return `${eventLabel(ev.event_type, ev.source)} · ${ev.lga ?? stateLabel}\n${isRecordedEvent(ev.source) ? 'Recorded' : 'Detected'} · click for detail`;
              }
              return r?.lga ? `${r.lga} · ${impactRainMm(r).toFixed(0)} mm\nClick for detail` : null;
            }}
            card={card}
          />
          <div className="sgr-legend">
            <span><i className="sgr-ramp" /> 25 → 105 mm in the day</span>
            <span><i className="sgr-dot sgr-dot--amber" /> Storm LGA — click for detail</span>
            <span><i className="sgr-dot sgr-dot--lit" /> Village with light at night</span>
            {layersOn.record && pinned.length > 0 && (
              <span><i className="sgr-dot sgr-dot--ring" /> Recorded disaster · <i className="sgr-dot sgr-dot--event" /> live detection</span>
            )}
          </div>
        </div>

        <div className="sgr-listcol">
          <h3 className="sgr-h2">Who was under the heaviest rain</h3>
          {impact.isLoading && <div className="fp-alert-empty">Loading…</div>}
          {rows.slice(0, 6).map((r) => (
            <button
              key={r.lga}
              type="button"
              className={`sgr-card ${selected === r.lga ? 'is-on' : ''}`}
              onClick={() => pickLga(r.lga)}
              aria-pressed={selected === r.lga}
            >
              <span className="sgr-card-lga">{r.lga}</span>
              <span className={`sgr-card-mm ${impactRainMm(r) > 80 ? 'is-violet' : ''}`}>
                {impactRainMm(r).toFixed(0)}<small> mm</small>
              </span>
              <span className="sgr-card-body">
                <span className="sgr-card-strong">
                  {r.people ? `${n0(r.people)} people · ${n0(r.under5)} under five · ${n0(r.villages)} villages, ${n0(r.dark_villages)} dark at night` : 'Village layer not measured here yet'}
                </span>
                {r.storm?.percentile_3h != null && (
                  <span>3-hour rain in the top {Math.max(1, Math.round(100 - r.storm.percentile_3h))}% of its own record ({r.storm.baseline_days} rain days)</span>
                )}
                {r.history[0] && <span>Flooded before: {r.history[0].summary}</span>}
                <span className={(r.sms_recipients ?? 0) > 0 ? 'sgr-card-sms' : ''}>
                  {(r.sms_recipients ?? 0) > 0
                    ? `Advisory sent by SMS to ${r.sms_recipients} farmer leaders${r.sms_sent_at ? ` · ${dayShort(r.sms_sent_at)}` : ''}`
                    : r.rain_day_mm != null ? 'No SMS sent for this LGA' : 'Below the daily advisory line'}
                </span>
              </span>
            </button>
          ))}
        </div>
      </div>

      {timeline.length > 0 && shownDay && (
        <div className="sgr-timeline">
          <div className="sgr-timeline-head">
            <h3 className="sgr-h2">How the storm moved</h3>
            <span className="sgr-kpi-src">{dayLong(shownDay)} · Nigeria time · white tick = peak half-hour</span>
          </div>
          <div className="sgr-tl-axis">
            {[0, 4, 8, 12, 16, 20, 24].map((h) => (
              <span key={h} style={{ left: `${(h / 24) * 100}%` }}>{String(h).padStart(2, '0')}:00</span>
            ))}
          </div>
          {timeline.map((r) => {
            const s0 = Math.max(0, hoursInto(shownDay, r.storm!.started_at));
            const s1 = Math.min(24, hoursInto(shownDay, r.storm!.ended_at));
            const pk = Math.max(0, Math.min(24, hoursInto(shownDay, r.storm!.peak_at)));
            return (
              <button key={r.lga} type="button" className="sgr-tl-row" onClick={() => pickLga(r.lga)}>
                <span className="sgr-tl-lga">{r.lga}</span>
                <span className="sgr-tl-track">
                  <span
                    className={`sgr-tl-bar ${r.storm!.total_mm > 80 ? 'is-violet' : ''}`}
                    style={{ left: `${(s0 / 24) * 100}%`, width: `${(Math.max(0.25, s1 - s0) / 24) * 100}%` }}
                  />
                  <span className="sgr-tl-peak" style={{ left: `${(pk / 24) * 100}%` }} />
                </span>
                <span className="sgr-tl-mm">{r.storm!.total_mm.toFixed(0)} mm · {hm(r.storm!.started_at)}–{hm(r.storm!.ended_at)}</span>
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}


function ImpactCard({ row, onClose }: { row: ImpactRow; onClose: () => void }) {
  const st = row.storm;
  const hist = row.history[0];
  const rowsOut = [
    { k: 'Rain in the day', v: row.rain_day_mm != null ? `${row.rain_day_mm.toFixed(1)} mm — past its own extreme` : 'Below the daily advisory line' },
    ...(st ? [{ k: 'Storm', v: `${hm(st.started_at)}–${hm(st.ended_at)} WAT · peak ${st.peak_mm_hr.toFixed(0)} mm/h · ${st.total_mm.toFixed(0)} mm` }] : []),
    ...(st?.percentile_3h != null ? [{ k: 'Rank in its record', v: `3-hour rain in the top ${Math.max(1, Math.round(100 - st.percentile_3h))}% (${st.baseline_days} rain days)` }] : []),
    { k: 'Lives here', v: row.people ? `${n0(row.people)} people · ${n0(row.under5)} under five` : 'Not measured yet' },
    { k: 'Villages', v: row.villages ? `${n0(row.villages)} named · ${n0(row.dark_villages)} dark at night` : '—' },
    { k: 'Advisory', v: (row.sms_recipients ?? 0) > 0 ? `SMS to ${row.sms_recipients} farmer leaders${row.sms_sent_at ? ` · ${dayShort(row.sms_sent_at)}` : ''}` : 'No SMS sent for this LGA' },
    ...(hist ? [{
      k: 'Flooded before',
      v: hist.source_url
        ? <>{hist.summary} — <a href={hist.source_url} target="_blank" rel="noopener noreferrer">{hist.source}</a></>
        : `${hist.summary ?? hist.event_type}${hist.source ? ` — ${hist.source}` : ''}`,
    }] : []),
  ];
  return (
    <HaloCard
      tone="dark"
      title={`${row.lga}`}
      big={`${impactRainMm(row).toFixed(0)} mm`}
      rows={rowsOut}
      why="Rain is measured from space every half hour and compared with this LGA's own record. It shows where extreme rain fell and who lives there; whether it flooded is confirmed on the ground."
      onClose={onClose}
    />
  );
}


function EventCard({ ev, stateLabel, onClose }: { ev: ShockEventRow; stateLabel: string; onClose: () => void }) {
  const recorded = isRecordedEvent(ev.source);
  const cite = ev.metrics as { source?: string; source_url?: string; event_date?: string; note?: string } | undefined;
  const when = cite?.event_date ?? ev.created_at.slice(0, 10);
  const drought = ev.event_type === 'drought' && !recorded;
  const rowsOut = [
    { k: 'What', v: ev.zone_name ?? eventLabel(ev.event_type, ev.source) },
    { k: 'When', v: new Date(`${when.slice(0, 10)}T12:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' }) },
    ...(recorded
      ? [{ k: 'Reported by', v: cite?.source_url
        ? <a href={cite.source_url} target="_blank" rel="noopener noreferrer">{cite.source ?? 'source'}</a>
        : (cite?.source ?? 'Recorded event') }]
      : [
        { k: 'Found by', v: INSTRUMENT[ev.source] ?? ev.detector_name },
        { k: 'Confidence', v: `${ev.confidence_band.toLowerCase()} · for an analyst to verify` },
      ]),
    { k: 'Severity', v: ev.severity.charAt(0).toUpperCase() + ev.severity.slice(1) },
    ...(ev.location ? [{
      k: 'Location',
      v: <>{ev.location.lat.toFixed(4)}°N {ev.location.lon.toFixed(4)}°E · <DirectionsLink lat={ev.location.lat} lon={ev.location.lon} /></>,
    }] : []),
  ];
  return (
    <HaloCard
      tone="dark"
      title={`${eventLabel(ev.event_type, ev.source)} · ${ev.lga ?? stateLabel}`}
      big={recorded ? 'Recorded disaster' : 'Live detection'}
      rows={rowsOut}
      why={recorded
        ? (cite?.note ?? 'A documented disaster from the public record, with its source — the history each storm is read against.')
        : drought
          ? `Sentinel-2 greenness in this LGA fell well below its own normal for the month. ${DROUGHT_SENTENCE}`
          : 'A reading from the daily satellite checks. It is a lead for someone on the ground to confirm, not a confirmed disaster.'}
      onClose={onClose}
    />
  );
}
