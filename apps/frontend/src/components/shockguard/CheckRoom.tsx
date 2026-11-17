'use client';

/**
 * ShockGuard's forecast check (2026-11-17): every day, the rain ECMWF forecast
 * for each LGA set against the rain NASA's IMERG satellites measured there.
 * The storm room's third view — it still opens on the storm day, the forecast
 * is untouched, and this reads both without changing either.
 *
 * The forecast side's design: a ribbon of checked days, a map of where the
 * forecast and the satellites agreed, the disagreements beside it, and a
 * scorecard by how far ahead the forecast was made. Both sides are estimates,
 * so it reports how often they agree — never an "accuracy".
 */

import { useMemo, useState, type ReactNode } from 'react';
import { GeoJsonLayer, ScatterplotLayer } from '@deck.gl/layers';

import EBMap from '@/components/map/EBMap';
import MapToolbar from '@/components/map/MapToolbar';
import ModuleSources from '@/components/common/ModuleSources';
import { BASEMAP_STYLE, fillAlpha, type Basemap } from '@/components/map/basemaps';
import type { Tenant } from '@/data/tenants';
import { useForecastOutlines } from '@/hooks/useForecast';
import { useForecastCheck, useForecastCheckDay, type CheckDayArea, type CheckModel } from '@/hooks/useForecastCheck';
import type { LgaFeature } from '@/hooks/useLgaBoundaries';
import { CheckDayCard, CheckKpis, CheckSeasonCard } from './CheckCards';
import { CheckDayList, CheckRecordList } from './CheckList';
import CheckRibbon from './CheckRibbon';
import CheckScorecard from './CheckScorecard';
import {
  AGREE, agreed, forecastAt, headline, leadChip, leadLabel, lgaCounts, MIN_RAIN_DAYS, MODEL_SHORT, OUTCOME_COL,
  OUTCOME_TEXT, outcome, pctText, unitFor, type DayLayer,
} from './checkModel';
import { band, dayMonth, hexRgb, longDay, mm, RAIN } from './forecastModel';

const HALOS = 3;
const AMBER_RGB: [number, number, number] = [242, 181, 74];
const UNSCORED: [number, number, number, number] = [142, 163, 181, 38];
const LAYERS: { id: DayLayer | 'record'; label: string; dot: string }[] = [
  { id: 'outcome', label: 'Forecast vs measured', dot: OUTCOME_COL.hit },
  { id: 'measured', label: 'What fell · NASA', dot: '#4f8fd6' },
  { id: 'forecast', label: 'What was forecast', dot: '#8ea3b5' },
  { id: 'record', label: 'Season record', dot: '#6fe0d0' },
];

function Bands({ cuts, cols, unit }: { cuts: number[]; cols: string[]; unit: string }) {
  return (
    <span className="fc-bands">
      {cuts.map((cut, i) => (
        <span key={cut} className="fc-band"><i style={{ background: cols[i] }} /><span>{cut}{i === 0 ? ` ${unit}` : ''}</span></span>
      ))}
    </span>
  );
}

export default function CheckRoom({ tenant, stateLabel, headerExtra }: {
  tenant: Tenant; stateLabel: string; headerExtra?: ReactNode;
}) {
  const q = useForecastCheck(tenant.id);
  const s = q.data;
  const unit = unitFor(tenant.id);
  const [sel, setSel] = useState<string | null>(null);         // 'season' | ISO day; null = newest day
  const [layer, setLayer] = useState<DayLayer>('outcome');
  const [model, setModel] = useState<CheckModel>('ifs');
  const [lead, setLead] = useState(1);
  const [basemap, setBasemap] = useState<Basemap>('dark');
  const [picked, setPicked] = useState<string | null>(null);
  const [cardOpen, setCardOpen] = useState(false);
  const [playing, setPlaying] = useState(false);
  const outlines = useForecastOutlines(tenant.id);

  const ribbon = useMemo(() => s?.ribbon ?? [], [s]);
  const newest = ribbon.length ? ribbon[ribbon.length - 1].day : s?.last_day ?? null;
  const current = sel ?? newest ?? 'season';
  const season = current === 'season';
  const dayQ = useForecastCheckDay(tenant.id, season ? null : current, !season);
  const areas = useMemo(() => (season ? [] : dayQ.data?.areas ?? []), [season, dayQ.data]);
  const leadIdx = Math.max(0, (s?.shown_leads ?? []).indexOf(lead));
  const byArea = useMemo(() => new Map(areas.map((a) => [a.lga, a])), [areas]);
  const byLga = useMemo(() => new Map((s?.lgas ?? []).map((l) => [l.lga, l])), [s]);
  const known = (lga: string) => (season ? byLga.has(lga) : byArea.has(lga));
  const select = (lga: string) => { setPicked(lga); setCardOpen(true); };

  const defaultLga = useMemo(() => {
    if (season) {
      const pool = (s?.lgas ?? []).filter((l) => l.wet >= MIN_RAIN_DAYS);
      return pool.length ? pool.reduce((b, l) => (l.wet > b.wet ? l : b)).lga : null;
    }
    const misses = areas.filter((a) => outcome(forecastAt(a, model, lead), a.measured_mm) === 'miss');
    const pool = misses.length ? misses : areas;
    return pool.length ? pool.reduce((b, a) => (a.measured_mm > b.measured_mm ? a : b)).lga : null;
  }, [season, s, areas, model, lead]);
  const selectedLga = picked && known(picked) ? picked : defaultLga;

  const mapLayers = useMemo(() => {
    const fill = (lga: string): string | null => {
      if (season) {
        const l = byLga.get(lga);
        const c = l && l.wet >= MIN_RAIN_DAYS ? lgaCounts(l, model, leadIdx) : null;
        return c ? band(AGREE, agreed(c).pct) : null;
      }
      const a = byArea.get(lga);
      if (!a) return null;
      if (layer === 'measured') return band(RAIN, a.measured_mm);
      const f = forecastAt(a, model, lead);
      if (layer === 'forecast') return band(RAIN, f);
      const o = outcome(f, a.measured_mm);
      return o && o !== 'dry' ? OUTCOME_COL[o] : null;
    };
    const out: unknown[] = [];
    const alpha = fillAlpha(basemap);
    const onDark = basemap !== 'light';
    if (outlines.data) {
      out.push(new GeoJsonLayer({
        id: 'ck-areas',
        data: outlines.data as never,
        filled: true,
        stroked: true,
        pickable: true,
        getFillColor: (f: { properties: { lga: string } }) => {
          const c = fill(f.properties.lga);
          if (c) return [...hexRgb(c), alpha];
          return season && byLga.has(f.properties.lga) ? UNSCORED : [0, 0, 0, 0];
        },
        getLineColor: onDark ? [232, 238, 243, 90] : [40, 44, 52, 110],
        lineWidthMinPixels: 1,
        onClick: (info: { object?: { properties: { lga: string } } }) => {
          const lga = info.object?.properties.lga;
          if (lga && (season ? byLga.has(lga) : byArea.has(lga))) { setPicked(lga); setCardOpen(true); }
        },
        updateTriggers: { getFillColor: [season, byLga, byArea, layer, model, lead, leadIdx, alpha], getLineColor: [onDark] },
      }));
      const selF = outlines.data.find((f) => f.properties.lga === selectedLga);
      if (selF) {
        out.push(new GeoJsonLayer({
          id: 'ck-selected', data: [selF] as never, filled: false, stroked: true,
          getLineColor: [...AMBER_RGB, 255], lineWidthMinPixels: 2.5, pickable: false,
        }));
      }
    }
    if (!season) {
      const score = (a: CheckDayArea): number | null => {
        const f = forecastAt(a, model, lead);
        if (layer === 'measured') return a.measured_mm >= 1 ? a.measured_mm : null;
        if (layer === 'forecast') return f !== null && f >= 1 ? f : null;
        const o = outcome(f, a.measured_mm);
        return o === 'miss' || o === 'false' ? Math.abs((f ?? 0) - a.measured_mm) : null;
      };
      const ranked = areas
        .map((a) => ({ a, v: score(a) }))
        .filter((x): x is { a: CheckDayArea; v: number } => x.v !== null && x.a.location !== null)
        .sort((x, y) => y.v - x.v).slice(0, HALOS).map((x) => x.a);
      const rgb = (a: CheckDayArea): [number, number, number] => hexRgb(fill(a.lga) ?? '#f2b54a');
      out.push(new ScatterplotLayer({
        id: 'ck-halo', data: ranked, pickable: false, radiusUnits: 'pixels',
        getPosition: (a: CheckDayArea) => [a.location!.lon, a.location!.lat],
        getFillColor: (a: CheckDayArea) => [...rgb(a), a.lga === selectedLga ? 110 : 55],
        getRadius: (a: CheckDayArea) => (a.lga === selectedLga ? 22 : 15),
        updateTriggers: { getFillColor: [layer, model, lead, selectedLga], getRadius: [selectedLga] },
      }));
      out.push(new ScatterplotLayer({
        id: 'ck-halo-core', data: ranked, pickable: true, radiusUnits: 'pixels', stroked: true,
        getPosition: (a: CheckDayArea) => [a.location!.lon, a.location!.lat],
        getFillColor: (a: CheckDayArea) => [...rgb(a), 255],
        getLineColor: [255, 255, 255, 235], lineWidthMinPixels: 2,
        getRadius: (a: CheckDayArea) => (a.lga === selectedLga ? 7 : 5.5),
        onClick: (info: { object?: CheckDayArea }) => { if (info.object) { setPicked(info.object.lga); setCardOpen(true); } },
        updateTriggers: { getFillColor: [layer, model, lead], getRadius: [selectedLga] },
      }));
    }
    return out;
  }, [outlines.data, season, byLga, byArea, layer, model, lead, leadIdx, basemap, areas, selectedLga, setPicked, setCardOpen]);

  const tooltip = (lga: string): string => {
    if (season) {
      const l = byLga.get(lga);
      const c = l ? lgaCounts(l, model, leadIdx) : null;
      if (!l || !c) return 'not in the record';
      return l.wet < MIN_RAIN_DAYS ? `${l.wet} rain days: too few to score` : `${pctText(agreed(c))} of rain days agreed · ${l.wet} rain days`;
    }
    const a = byArea.get(lga);
    if (!a) return 'not measured this day';
    const f = forecastAt(a, model, lead);
    const o = outcome(f, a.measured_mm);
    return `measured ${mm(a.measured_mm)} mm · forecast ${f === null ? '—' : `${mm(f)} mm`}${o ? ` · ${OUTCOME_TEXT[o]}` : ''}`;
  };

  const layerId = season ? 'record' : layer;
  const stampTitle = LAYERS.find((l) => l.id === layerId)?.label ?? '';
  const stampSub = season
    ? `${s?.first_day ? dayMonth(s.first_day) : ''}–${s?.last_day ? dayMonth(s.last_day) : ''} · ${MODEL_SHORT[model]} · made ${leadLabel(lead)}`
    : layer === 'measured' ? `${longDay(current)} · NASA IMERG · 00–24 UTC`
      : `${longDay(current)} · ${MODEL_SHORT[model]} · made ${leadLabel(lead)}`;
  const selectedArea = selectedLga ? byArea.get(selectedLga) : undefined;
  const selectedRecord = selectedLga ? byLga.get(selectedLga) : undefined;
  const cardAt = season ? selectedRecord?.location : selectedArea?.location;

  return (
    <section className="sgr" aria-labelledby="ck-title">
      <div className="sgr-head">
        <div className="sgr-head-main">
          <span className="sgr-eyebrow">ShockGuard · Forecast check · {stateLabel}</span>
          <h2 id="ck-title" className="sgr-h1">
            {q.isLoading ? 'Reading the record…' : s && s.days_checked ? headline(stateLabel, unit, s) : `No forecast has been checked for ${stateLabel} yet.`}
          </h2>
          <p className="sgr-sub">
            Each day, the rain ECMWF forecast for every {unit} is set against the rain NASA&rsquo;s IMERG satellites measured there, for
            every forecast made from the same morning back to 14 days before. Both are averages over the {unit}; a day with 1 mm or more is
            wet. A check between a forecast and a satellite estimate, not a rain gauge.
          </p>
        </div>
        <div className="sgr-head-side">
          {headerExtra}
          <span className="sgr-chip">CHECKED DAILY · ECMWF VS NASA IMERG</span>
          <ModuleSources sources={[
            { name: 'ECMWF IFS', role: 'physics model' },
            { name: 'ECMWF AIFS', role: 'AI model' },
            { name: 'ECMWF ENS', role: 'ensemble chances' },
            { name: 'NASA GPM IMERG', role: 'measured rain' },
            { name: 'geoBoundaries', role: 'outlines' },
          ]} />
        </div>
      </div>

      {q.isError && <div className="fp-alert-error">Could not load the forecast check: {q.error?.message ?? 'unknown'}</div>}
      {s && s.feed.last_status === 'failed' && (
        <div className="fp-alert-notice">The latest check failed{s.feed.last_error ? `: ${s.feed.last_error}` : ''}. Showing the record as it stood.</div>
      )}
      {s && !s.days_checked && !q.isLoading && (
        <div className="fp-alert-notice">
          The check runs at 10:30 and 22:30 UTC, after NASA publishes each day&rsquo;s rain (about a day later). The first scorecard for {stateLabel} appears here then.
        </div>
      )}

      {s && s.days_checked > 0 && (
        <>
          <CheckKpis s={s} unit={unit} model={model} lead={lead} leadIdx={leadIdx} />
          <CheckRibbon days={ribbon} sel={current} onSel={(d) => { setSel(d); if (d !== 'season' && current === 'season') setLayer('outcome'); }}
            model={model} leadIdx={leadIdx} season={s.scorecard.all?.[model]?.[lead] ?? null} seasonFrom={s.first_day}
            playing={playing} onPlaying={setPlaying} unit={unit} />

          <div className="ck-controls">
            <div className="ck-ctl">
              <span className="ck-ctl-label">Forecast made</span>
              <div className="fc-mode" role="group" aria-label="How long before the day the forecast was made">
                {s.shown_leads.map((k) => (
                  <button key={k} type="button" aria-pressed={lead === k} onClick={() => setLead(k)}>{leadChip(k)}</button>
                ))}
              </div>
              <span className="ck-ctl-label">days before</span>
            </div>
            <div className="ck-ctl">
              <span className="ck-ctl-label">Model</span>
              <div className="fc-mode" role="group" aria-label="Model">
                <button type="button" aria-pressed={model === 'ifs'} onClick={() => setModel('ifs')}>Physics (IFS)</button>
                <button type="button" aria-pressed={model === 'aifs'} onClick={() => setModel('aifs')}>AI (AIFS)</button>
              </div>
            </div>
          </div>

          <div className="sgr-main">
            <div className="sgr-mapcol">
              <MapToolbar
                tone="dark"
                basemap={basemap}
                onBasemap={setBasemap}
                layers={LAYERS.map((l) => ({ id: l.id, label: l.label, dot: l.dot, on: layerId === l.id }))}
                onToggle={(id) => {
                  if (id === 'record') { setPlaying(false); setSel('season'); return; }
                  setLayer(id as DayLayer);
                  if (season) setSel(newest);
                }}
              />
              <EBMap
                tenant={tenant}
                layers={mapLayers}
                height="560px"
                mapStyle={BASEMAP_STYLE[basemap]}
                ariaLabel={`Forecast check for ${stateLabel}`}
                overlay={<div className="fc-stamp"><b>{stampTitle}</b><span>{stampSub}</span></div>}
                getTooltip={(o) => {
                  const lga = (o as LgaFeature)?.properties?.lga ?? (o as CheckDayArea)?.lga;
                  return lga ? `${lga} · ${tooltip(lga)}\nClick for detail` : null;
                }}
                card={cardOpen && cardAt && selectedLga ? {
                  lng: cardAt.lon, lat: cardAt.lat,
                  node: season && selectedRecord
                    ? <CheckSeasonCard l={selectedRecord} model={model} lead={lead} leadIdx={leadIdx} s={s} stateLabel={stateLabel}
                      unit={unit} onClose={() => setCardOpen(false)} />
                    : selectedArea ? <CheckDayCard a={selectedArea} record={selectedRecord} model={model} lead={lead} leadIdx={leadIdx}
                      day={current} stateLabel={stateLabel} onClose={() => setCardOpen(false)} /> : null,
                } : null}
              />
              <div className="sgr-legend">
                {season ? (
                  <><Bands cuts={AGREE.cuts} cols={AGREE.cols} unit="%" />
                    <span>on days either side had rain, the share where both did</span>
                    <span><i className="fc-swatch" style={{ background: 'rgba(142,163,181,.35)' }} /> under {MIN_RAIN_DAYS} rain days: not scored</span></>
                ) : layer === 'outcome' ? (
                  <>
                    <span><i className="fc-swatch" style={{ background: OUTCOME_COL.hit }} /> rain forecast and measured</span>
                    <span><i className="fc-swatch" style={{ background: OUTCOME_COL.miss }} /> rain measured, not forecast</span>
                    <span><i className="fc-swatch" style={{ background: OUTCOME_COL.false }} /> rain forecast, none measured</span>
                    <span>clear = dry, called dry</span>
                  </>
                ) : <><Bands cuts={RAIN.cuts} cols={RAIN.cols} unit="mm" /><span>{layer === 'measured' ? 'rain measured in the day' : 'rain forecast for the day'} · under 1 mm = dry, left clear</span></>}
                <span>· click any {unit} for its detail</span>
              </div>
              <p className="fc-attrib">{s.attribution} {s.measured_credit}</p>
            </div>
            {season
              ? <CheckRecordList lgas={s.lgas} model={model} leadIdx={leadIdx} lead={lead} selected={selectedLga} onSelect={select} unit={unit} />
              : <CheckDayList areas={areas} model={model} lead={lead} day={current} selected={selectedLga} onSelect={select} unit={unit} />}
          </div>

          <CheckScorecard s={s} unit={unit} />

          <div className="fc-how">
            <div>
              <h3 className="sgr-h2">How we report</h3>
              <ul>
                <li>Both sides are estimates. The measured rain is NASA&rsquo;s IMERG (Late run), read from satellites, not a rain gauge; where the two disagree, either may be the one that is off. So this shows how often they agree, never an accuracy.</li>
                <li>Like for like: both are averaged over each {unit} by the share of its area each cell covers (ECMWF&rsquo;s 0.25° cells, IMERG&rsquo;s 0.1° cells), and both run midnight to midnight UTC. A day is wet at 1 mm or more of that average.</li>
                <li>Every forecast made for a day is checked, from the 00 UTC run of the same morning back to 14 days before. Runs before 17 Nov 2026 were read afterwards from ECMWF&rsquo;s open-data archive: the same files, processed the same way.</li>
                <li>Ensemble chances are set against the share of the {unit} that got the rain. Checked twice a day as NASA publishes each day&rsquo;s file. Nothing here sends an alert or an SMS.</li>
              </ul>
            </div>
            <div>
              <h3 className="sgr-h2">Sources and licences</h3>
              <ul>
                <li>{s.attribution}</li>
                <li>{s.measured_credit}</li>
              </ul>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
