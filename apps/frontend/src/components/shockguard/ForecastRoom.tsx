'use client';

/**
 * ShockGuard's forecast side (operator-approved mock, 2026-11-17): the next 15
 * days for every LGA, from ECMWF open data. It sits BESIDE the storm day — the
 * room opens on the storm day as before, and this is one switch away.
 *
 * Close to ECMWF's charts where they are good (banded rain, a run/valid stamp,
 * stepping through days, an outlook per place) and our own everywhere else:
 * LGA averages, the physics and AI models side by side, a plain chance ladder
 * instead of box plots, the storm room's design. A forecast, not a measurement.
 */

import { useMemo, useState, type ReactNode } from 'react';
import { GeoJsonLayer, PolygonLayer, ScatterplotLayer } from '@deck.gl/layers';

import EBMap from '@/components/map/EBMap';
import HaloCard from '@/components/map/HaloCard';
import MapToolbar from '@/components/map/MapToolbar';
import ModuleSources from '@/components/common/ModuleSources';
import { BASEMAP_STYLE, fillAlpha, type Basemap } from '@/components/map/basemaps';
import type { Tenant } from '@/data/tenants';
import { useForecast, useForecastCells, useForecastOutlines, type ForecastArea, type ForecastCells } from '@/hooks/useForecast';
import type { LgaFeature } from '@/hooks/useLgaBoundaries';
import ForecastList from './ForecastList';
import ForecastOutlook from './ForecastOutlook';
import ForecastRibbon from './ForecastRibbon';
import {
  AGREE_COLS, band, CHANCE, CHANCE_DAYS, dayMonth, dayName, headline, HEAT, hexRgb, isWet, LAYERS, layerColour,
  layerValue, longDay, maxAt, maxOf, mm, RAIN, readingHours, sum, summary, TEMP_DAYS, TOTAL_DAYS,
  type DaySel, type LayerId, type Scale,
} from './forecastModel';

const UNIT: Record<string, string> = { ghana: 'district', senegal: 'department' };
const HALOS = 3;
const AMBER_RGB: [number, number, number] = [242, 181, 74];

function cellPolygons(c: ForecastCells, layer: LayerId, day: DaySel): { polygon: number[][]; colour: string }[] {
  const grids = layer === 'aifs' ? c.rain_aifs_mm : layer === 'p10' ? c.chance_10mm : c.rain_ifs_mm;
  if (!grids?.length || c.lat0 === null || c.lon0 === null) return [];
  if (layer === 'p10' && day >= CHANCE_DAYS) return [];
  const h = c.res / 2;
  const out: { polygon: number[][]; colour: string }[] = [];
  for (let k = 0; k < c.n_rows * c.n_cols; k += 1) {
    const v = day >= 0 ? grids[day]?.[k] ?? 0
      : layer === 'p10' ? Math.max(...grids.map((g) => g[k] ?? 0)) : grids.slice(0, TOTAL_DAYS).reduce((s, g) => s + (g[k] ?? 0), 0);
    const colour = band(layer === 'p10' ? CHANCE : RAIN, v);
    if (!colour) continue;
    const lat = c.lat0 - Math.floor(k / c.n_cols) * c.res;
    const lon = c.lon0 + (k % c.n_cols) * c.res;
    out.push({ colour, polygon: [[lon - h, lat + h], [lon + h, lat + h], [lon + h, lat - h], [lon - h, lat - h]] });
  }
  return out;
}

function Bands({ s, unit }: { s: Scale; unit: string }) {
  return (
    <span className="fc-bands">
      {s.cuts.map((cut, i) => (
        <span key={cut} className="fc-band"><i style={{ background: s.cols[i] }} /><span>{cut}{i === 0 ? ` ${unit}` : ''}</span></span>
      ))}
    </span>
  );
}

export default function ForecastRoom({ tenant, stateLabel, headerExtra }: {
  tenant: Tenant; stateLabel: string; headerExtra?: ReactNode;
}) {
  const q = useForecast(tenant.id);
  const [layer, setLayer] = useState<LayerId>('ifs');
  const [day, setDay] = useState<DaySel>(-1);
  const [basemap, setBasemap] = useState<Basemap>('dark');
  const [cellsOn, setCellsOn] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const outlines = useForecastOutlines(tenant.id);
  const cellsQ = useForecastCells(tenant.id, cellsOn);

  const data = q.data;
  const areas = useMemo(() => data?.areas ?? [], [data]);
  const days = data?.days ?? [];
  const todayIso = new Date().toISOString().slice(0, 10);
  const unit = UNIT[tenant.id] ?? 'LGA';
  const hours = readingHours(tenant.id);
  const byLga = useMemo(() => new Map(areas.map((a) => [a.lga, a])), [areas]);
  const defaultLga = useMemo(() => {
    const wet = areas.filter(isWet);
    const pool = wet.length ? wet : areas;
    if (!pool.length) return null;
    const score = (a: ForecastArea) => (wet.length ? sum(a.rain_ifs_mm, TOTAL_DAYS) : maxOf(a.temp_afternoon_c));
    return pool.reduce((b, a) => (score(a) > score(b) ? a : b)).lga;
  }, [areas]);
  const selectedLga = picked && byLga.has(picked) ? picked : defaultLga;
  const selected = selectedLga ? byLga.get(selectedLga) ?? null : null;
  const [cardOpen, setCardOpen] = useState(false);
  const select = (lga: string) => { setPicked(lga); setCardOpen(true); };

  const cellsUsable = (layer === 'ifs' || layer === 'aifs' || layer === 'p10');
  const cellPolys = useMemo(
    () => (cellsOn && cellsUsable && cellsQ.data ? cellPolygons(cellsQ.data, layer, day) : []),
    [cellsOn, cellsUsable, cellsQ.data, layer, day],
  );

  const mapLayers = useMemo(() => {
    const out: unknown[] = [];
    const alpha = fillAlpha(basemap) * (cellPolys.length ? 0.35 : 1);
    const onDark = basemap !== 'light';
    if (outlines.data) {
      out.push(new GeoJsonLayer({
        id: 'fc-areas',
        data: outlines.data as never,
        filled: true,
        stroked: true,
        pickable: true,
        getFillColor: (f: { properties: { lga: string } }) => {
          const a = byLga.get(f.properties.lga);
          const c = a ? layerColour(a, layer, day) : null;
          return c ? [...hexRgb(c), alpha] : [0, 0, 0, 0];
        },
        getLineColor: onDark ? [232, 238, 243, 90] : [40, 44, 52, 110],
        lineWidthMinPixels: 1,
        onClick: (info: { object?: { properties: { lga: string } } }) => {
          const lga = info.object?.properties.lga;
          if (lga && byLga.has(lga)) select(lga);
        },
        updateTriggers: { getFillColor: [byLga, layer, day, alpha], getLineColor: [onDark] },
      }));
    }
    if (cellPolys.length) {
      out.push(new PolygonLayer({
        id: 'fc-cells',
        data: cellPolys,
        getPolygon: (d: { polygon: number[][] }) => d.polygon,
        getFillColor: (d: { colour: string }) => [...hexRgb(d.colour), 225],
        getLineColor: [13, 20, 27, 140],
        lineWidthMinPixels: 0.5,
        pickable: false,
      }));
    }
    const sel = outlines.data?.find((f) => f.properties.lga === selectedLga);
    if (sel) {
      out.push(new GeoJsonLayer({
        id: 'fc-selected', data: [sel] as never, filled: false, stroked: true,
        getLineColor: [...AMBER_RGB, 255], lineWidthMinPixels: 2.5, pickable: false,
      }));
    }
    const ranked = areas
      .map((a) => ({ a, v: layerValue(a, layer, day) }))
      .filter((x): x is { a: ForecastArea; v: number } => x.v !== null && x.a.location !== null)
      .filter((x) => (layer === 'ifs' || layer === 'aifs' ? x.v >= 1 : layer === 'p10' ? x.v >= 5 : layer === 'heat'))
      .sort((x, y) => y.v - x.v)
      .slice(0, HALOS)
      .map((x) => x.a);
    const haloRgb = (a: ForecastArea): [number, number, number] => hexRgb(layerColour(a, layer, day) ?? '#f2b54a');
    out.push(new ScatterplotLayer({
      id: 'fc-halo', data: ranked, pickable: false, radiusUnits: 'pixels',
      getPosition: (a: ForecastArea) => [a.location!.lon, a.location!.lat],
      getFillColor: (a: ForecastArea) => [...haloRgb(a), a.lga === selectedLga ? 110 : 55],
      getRadius: (a: ForecastArea) => (a.lga === selectedLga ? 22 : 15),
      updateTriggers: { getFillColor: [layer, day, selectedLga], getRadius: [selectedLga] },
    }));
    out.push(new ScatterplotLayer({
      id: 'fc-halo-core', data: ranked, pickable: true, radiusUnits: 'pixels', stroked: true,
      getPosition: (a: ForecastArea) => [a.location!.lon, a.location!.lat],
      getFillColor: (a: ForecastArea) => [...haloRgb(a), 255],
      getLineColor: [255, 255, 255, 235], lineWidthMinPixels: 2,
      getRadius: (a: ForecastArea) => (a.lga === selectedLga ? 7 : 5.5),
      onClick: (info: { object?: ForecastArea }) => { if (info.object) select(info.object.lga); },
      updateTriggers: { getFillColor: [layer, day], getRadius: [selectedLga] },
    }));
    return out;
  }, [outlines.data, byLga, layer, day, basemap, cellPolys, selectedLga, areas]);

  const unavailable = areas.length > 0 && areas.every((a) => layerValue(a, layer, day) === null);
  const allDry = !unavailable && (layer === 'ifs' || layer === 'aifs' || layer === 'agree')
    && areas.every((a) => (layer === 'agree' ? (layerValue(a, layer, day) ?? 0) === 0 : (layerValue(a, layer, day) ?? 0) < 1));
  const when = day < 0 ? 'in the next 10 days' : dayName(days[day], todayIso);
  const notice = !areas.length ? null : unavailable ? (
    <span className="fc-na">
      {layer === 'p10' ? 'Ensemble chances run to day 10 — pick an earlier day.'
        : layer === 'heat' ? 'Temperature is read for the first 6 days — pick an earlier day.'
          : 'This model was not available for this run.'}
    </span>
  ) : allDry ? (
    <span className="fc-na">
      Dry {when === 'today' ? 'today' : when}: no {unit} in {stateLabel} expects 1 mm.{' '}
      <button type="button" className="fc-na-btn" onClick={() => { setLayer('heat'); if (day >= TEMP_DAYS) setDay(-1); }}>Show afternoon heat</button>
    </span>
  ) : null;

  const runLabel = data?.run_at ? `${longDay(data.run_at.slice(0, 10))}, 00 UTC` : '';
  const runShort = data?.run_at ? `${dayMonth(data.run_at.slice(0, 10))} 00 UTC` : '';
  const layerLabel = LAYERS.find((l) => l.id === layer)?.label ?? '';
  const valid = day < 0
    ? (layer === 'heat' ? `${dayMonth(days[0] ?? todayIso)}–${dayMonth(days[TEMP_DAYS - 1] ?? todayIso)} (+0–144 h)` : `${dayMonth(days[0] ?? todayIso)}–${dayMonth(days[TOTAL_DAYS - 1] ?? todayIso)} (+0–240 h)`)
    : `${dayName(days[day], todayIso)} (+${day * 24}–${day * 24 + 24} h)`;

  return (
    <section className="sgr" aria-labelledby="fc-title">
      <div className="sgr-head">
        <div className="sgr-head-main">
          <span className="sgr-eyebrow">ShockGuard · Forecast · {stateLabel}</span>
          <h2 id="fc-title" className="sgr-h1">
            {q.isLoading ? 'Reading the forecast…'
              : areas.length ? headline(stateLabel, unit, areas)
                : 'No forecast stored yet for this state.'}
          </h2>
          <p className="sgr-sub">
            ECMWF forecast{runLabel ? ` from the run of ${runLabel}` : ''}, averaged over each {unit}. ECMWF&rsquo;s physics
            model and its AI model are shown side by side, with chances from its ensemble. A forecast, not a measurement:
            what actually fell is on the storm day.
          </p>
        </div>
        <div className="sgr-head-side">
          {headerExtra}
          <span className="sgr-chip">FORECAST · ECMWF · 00 UTC RUN</span>
          <ModuleSources sources={[
            { name: 'ECMWF IFS', role: 'physics model' },
            { name: 'ECMWF AIFS', role: 'AI model' },
            { name: 'ECMWF ENS', role: 'ensemble chances' },
            { name: 'geoBoundaries', role: 'outlines' },
          ]} />
        </div>
      </div>

      {q.isError && <div className="fp-alert-error">Could not load the forecast: {q.error?.message ?? 'unknown'}</div>}
      {data && data.feed.last_status === 'failed' && (
        <div className="fp-alert-notice">
          The latest forecast read failed{data.feed.last_error ? `: ${data.feed.last_error}` : ''}.
          {data.run_at ? ` Showing the run of ${runLabel}.` : ''}
        </div>
      )}
      {data && !areas.length && !q.isLoading && (
        <div className="fp-alert-notice">The forecast is read every day at 09:15 UTC; the first run for {stateLabel} appears here after it lands.</div>
      )}

      {areas.length > 0 && data && (
        <>
          <Kpis areas={areas} days={days} todayIso={todayIso} unit={unit} afternoon={hours.afternoon} />
          <ForecastRibbon areas={areas} days={days} todayIso={todayIso} layer={layer} day={day}
            onDay={setDay} playing={playing} onPlaying={setPlaying} unit={unit} />

          <div className="sgr-main">
            <div className="sgr-mapcol">
              <MapToolbar
                tone="dark"
                basemap={basemap}
                onBasemap={setBasemap}
                layers={[
                  ...LAYERS.map((l) => ({ id: l.id, label: l.label, dot: l.dot, on: layer === l.id })),
                  { id: 'cells', label: cellsUsable ? '28 km cells' : '28 km cells (rain layers)', dot: '#8ea3b5', on: cellsOn && cellsUsable },
                ]}
                onToggle={(id) => { if (id === 'cells') setCellsOn((v) => !v); else setLayer(id as LayerId); }}
              />
              <EBMap
                tenant={tenant}
                layers={mapLayers}
                height="560px"
                mapStyle={BASEMAP_STYLE[basemap]}
                ariaLabel={`Forecast for ${stateLabel}`}
                // The notice rides in the top-right box with the stamp: the
                // bottom-left corner belongs to the Mapbox logo, which must stay visible.
                overlay={<div className="fc-stamp"><b>{layerLabel}</b><span>Run {runShort} · valid {valid}</span>{notice}</div>}
                getTooltip={(o) => {
                  const lga = (o as LgaFeature)?.properties?.lga ?? (o as ForecastArea)?.lga;
                  const a = lga ? byLga.get(lga) : undefined;
                  return a ? `${a.lga} · ${tooltipValue(a, layer, day)}\nClick for detail` : null;
                }}
                card={cardOpen && selected?.location ? {
                  lng: selected.location.lon, lat: selected.location.lat,
                  node: <AreaCard a={selected} days={days} todayIso={todayIso} layer={layer} day={day}
                    stateLabel={stateLabel} unit={unit} tenantId={tenant.id} onClose={() => setCardOpen(false)} />,
                } : null}
              />
              <div className="sgr-legend">
                {layer === 'ifs' || layer === 'aifs' ? <><Bands s={RAIN} unit="mm" /><span>{day < 0 ? 'rain over the next 10 days' : 'rain in the day'} · under 1 mm = dry, left clear</span></>
                  : layer === 'p10' ? <><Bands s={CHANCE} unit="%" /><span>share of ECMWF&rsquo;s ensemble forecasts giving 10 mm+ in the day</span></>
                    : layer === 'heat' ? <><Bands s={HEAT} unit="°C" /><span>afternoon temperature at 2 m ({hours.afternoon}) · first 6 days</span></>
                      : <>
                        <span><i className="fc-swatch" style={{ background: AGREE_COLS[3] }} /> both models: rain</span>
                        <span><i className="fc-swatch" style={{ background: AGREE_COLS[1] }} /> physics model only</span>
                        <span><i className="fc-swatch" style={{ background: AGREE_COLS[2] }} /> AI model only</span>
                        <span>clear = both dry (under 1 mm)</span>
                      </>}
                <span>· click any {unit} for its detail</span>
              </div>
              <p className="fc-attrib">{data.attribution}</p>
            </div>
            <ForecastList areas={areas} days={days} todayIso={todayIso} selected={selectedLga}
              onSelect={select} unit={unit} tenantId={tenant.id} />
          </div>

          {selected && <ForecastOutlook area={selected} days={days} todayIso={todayIso} tenantId={tenant.id} stateLabel={stateLabel} />}

          <div className="fc-how">
            <div>
              <h3 className="sgr-h2">How we report</h3>
              <ul>
                <li>This is a forecast, not a measurement. ECMWF&rsquo;s 0.25° grid cells (about 28 km) are averaged over each {unit} by the share of its area each cell covers; the card also gives the wettest single cell.</li>
                <li>Two models side by side: IFS is ECMWF&rsquo;s physics model, AIFS its machine-learning model. Where they disagree, both are shown rather than one picked.</li>
                <li>A chance is the share of ECMWF&rsquo;s ensemble forecasts giving at least that much rain in the day, averaged across the {unit}. Chances run to day 10; days 11–15 come from one run and have lower skill.</li>
                <li>Days run midnight to midnight UTC (1 am to 1 am in Nigeria). Temperatures are read at 15:00 and 06:00 UTC ({hours.afternoon} and {hours.dawn} local). Nothing here sends an alert or an SMS.</li>
              </ul>
            </div>
            <div>
              <h3 className="sgr-h2">Source and licence</h3>
              <ul>
                <li>{data.attribution}</li>
                <li>Read daily from data.ecmwf.int/forecasts, 00 UTC run.</li>
              </ul>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function tooltipValue(a: ForecastArea, layer: LayerId, day: DaySel): string {
  const v = layerValue(a, layer, day);
  if (v === null) return 'not available this day';
  if (layer === 'ifs' || layer === 'aifs') return `${v < 1 ? 'dry · ' : ''}${mm(v)} mm${day < 0 ? ' over 10 days' : ''}`;
  if (layer === 'p10') return `${v}% chance of 10 mm+${day < 0 ? ' (best day)' : ''}`;
  if (layer === 'heat') return `${Math.round(v)} °C afternoon${day < 0 ? ' (hottest)' : ''}`;
  return ['both models dry', 'only the physics model has rain', 'only the AI model has rain', 'both models have rain'][v];
}

function Kpis({ areas, days, todayIso, unit, afternoon }: {
  areas: ForecastArea[]; days: string[]; todayIso: string; unit: string; afternoon: string;
}) {
  const wet = areas.filter(isWet);
  const wettest = areas.reduce((b, a) => (sum(a.rain_ifs_mm, TOTAL_DAYS) > sum(b.rain_ifs_mm, TOTAL_DAYS) ? a : b));
  const wettestMm = sum(wettest.rain_ifs_mm, TOTAL_DAYS);
  const aiMax = areas.some((a) => a.rain_aifs_mm) ? Math.max(...areas.map((a) => sum(a.rain_aifs_mm, TOTAL_DAYS))) : null;
  const withP = areas.filter((a) => a.chance_1mm);
  const bestP = withP.length ? withP.reduce((b, a) => (maxOf(a.chance_1mm) > maxOf(b.chance_1mm) ? a : b)) : null;
  const withT = areas.filter((a) => a.temp_afternoon_c && a.temp_dawn_c);
  const hottest = withT.length ? withT.reduce((b, a) => (maxOf(a.temp_afternoon_c) > maxOf(b.temp_afternoon_c) ? a : b)) : null;
  const coldest = withT.length ? withT.reduce((b, a) => (Math.min(...a.temp_dawn_c!) < Math.min(...b.temp_dawn_c!) ? a : b)) : null;
  return (
    <div className="sgr-kpis">
      <div className="sgr-kpi">
        <span className="sgr-kpi-val fc-val--rain">{wet.length} of {areas.length}</span>
        <span className="sgr-kpi-label">{unit}s with at least one day of 1 mm or more in the next 10 days</span>
        <span className="sgr-kpi-src">ECMWF IFS · area average</span>
      </div>
      <div className="sgr-kpi">
        <span className="sgr-kpi-val fc-val--rain">{mm(wettestMm)} mm</span>
        <span className="sgr-kpi-label">
          {wettestMm >= 1 ? `wettest 10 days — ${wettest.lga}`
            : wettestMm >= 0.05 ? `most rain in any ${unit} over 10 days — ${wettest.lga}, a trace`
              : `rain forecast in any ${unit} over the next 10 days`}
        </span>
        <span className="sgr-kpi-src">ECMWF IFS{aiMax !== null ? ` · AIFS gives ${mm(aiMax)} mm at most` : ' · AIFS not available'}</span>
      </div>
      <div className="sgr-kpi">
        <span className="sgr-kpi-val fc-val--teal">{bestP ? `${maxOf(bestP.chance_1mm)}%` : '—'}</span>
        <span className="sgr-kpi-label">
          {!bestP ? 'ensemble chances not available for this run'
            : maxOf(bestP.chance_1mm) > 0 ? `best chance of a wet day — ${bestP.lga}, ${dayName(days[maxAt(bestP.chance_1mm, CHANCE_DAYS)], todayIso)}`
              : 'chance of a wet day anywhere: no ensemble forecast gives 1 mm'}
        </span>
        <span className="sgr-kpi-src">ECMWF ENS · ensemble chance · 1 mm+</span>
      </div>
      <div className="sgr-kpi">
        <span className="sgr-kpi-val fc-val--heat">{hottest ? `${Math.round(maxOf(hottest.temp_afternoon_c))} °C` : '—'}</span>
        <span className="sgr-kpi-label">
          {hottest && coldest
            ? `hottest ${afternoon} — ${hottest.lga}, ${dayName(days[maxAt(hottest.temp_afternoon_c, TEMP_DAYS)], todayIso)}; coldest dawn ${Math.round(Math.min(...coldest.temp_dawn_c!))} °C in ${coldest.lga}`
            : 'temperature not available for this run'}
        </span>
        <span className="sgr-kpi-src">ECMWF IFS · 2 m temperature · 6 days</span>
      </div>
    </div>
  );
}

function AreaCard({ a, days, todayIso, layer, day, stateLabel, unit, tenantId, onClose }: {
  a: ForecastArea; days: string[]; todayIso: string; layer: LayerId; day: DaySel;
  stateLabel: string; unit: string; tenantId: string; onClose: () => void;
}) {
  const hours = readingHours(tenantId);
  const v = layerValue(a, layer, day);
  const when = day < 0 ? '' : ` · ${dayName(days[day], todayIso)}`;
  const big = layer === 'heat' ? (v === null ? '—' : `${Math.round(v)} °C${day < 0 ? ' hottest afternoon' : ' afternoon'}${when}`)
    : layer === 'p10' ? (v === null ? '—' : `${v}% chance of 10 mm+${when}`)
      : `${mm(layerValue(a, layer === 'aifs' ? 'aifs' : 'ifs', day) ?? 0)} mm${day < 0 ? ' next 10 days' : when}`;
  const wd = maxAt(a.rain_ifs_mm, TOTAL_DAYS);
  const p1 = a.chance_1mm;
  const p10 = a.chance_10mm;
  const rows = [
    { k: 'Physics (IFS)', v: `${mm(sum(a.rain_ifs_mm, TOTAL_DAYS))} mm over 10 days` },
    { k: 'AI model (AIFS)', v: a.rain_aifs_mm ? `${mm(sum(a.rain_aifs_mm, TOTAL_DAYS))} mm over 10 days` : 'not available for this run' },
    { k: 'Wettest day', v: (a.rain_ifs_mm[wd] ?? 0) >= 0.05 ? `${dayName(days[wd], todayIso)} · ${mm(a.rain_ifs_mm[wd])} mm (wettest cell ${mm(a.rain_ifs_max_mm[wd] ?? 0)} mm)` : 'none: no rain forecast' },
    { k: 'Chance of a wet day', v: !p1 ? 'not available' : maxOf(p1) > 0 ? `up to ${maxOf(p1)}% · ${dayName(days[maxAt(p1, CHANCE_DAYS)], todayIso)}` : '0%: no ensemble forecast gives 1 mm' },
    { k: 'Chance of 10 mm+', v: !p10 ? 'not available' : maxOf(p10) > 0 ? `up to ${maxOf(p10)}% · ${dayName(days[maxAt(p10, CHANCE_DAYS)], todayIso)}` : '0% on every day' },
    ...(a.temp_afternoon_c && a.temp_dawn_c ? [{ k: 'Afternoon / dawn', v: `${Math.round(maxOf(a.temp_afternoon_c))} °C at ${hours.afternoon} · ${Math.round(Math.min(...a.temp_dawn_c))} °C at ${hours.dawn}` }] : []),
    { k: 'Forecast cells', v: `${a.cells} × 28 km cell${a.cells === 1 ? '' : 's'} cover this ${unit}` },
  ];
  return (
    <HaloCard
      tone="dark"
      title={`${a.lga} · ${stateLabel}`}
      big={big}
      rows={rows}
      why={summary(a, days, todayIso)}
      onClose={onClose}
      actions={
        <button type="button" className="fc-card-act" onClick={() => document.getElementById('fc-outlook')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}>
          See the 15-day outlook ↓
        </button>
      }
    />
  );
}
