'use client';

import { useEffect, useMemo, useState } from 'react';

import { fetchPlaceName } from '@/components/cropguard/FarmCheckPanel';
import type { AlertResponse, AlertSeverity } from '@/hooks/useFarmlandAlerts';
import {
  compareLandCover,
  classColor,
  topClasses,
  type LandCoverComparison,
} from './landCoverAnalysis';

/**
 * Alert Spotlight (Phase 1) — fills the column under the Farmland map.
 *
 * Click a pulsing halo (or an alert card's Spotlight button) → a briefing on
 * that exact coordinate: real Esri World Imagery centred on the alert with a
 * crosshair + to-scale affected-area box, the reverse-geocoded place name,
 * the alert's own numbers, Esri Wayback 2014/2026 before-after, the Esri 10 m
 * land-cover classification 2018 vs 2025, and a DETERMINISTIC summary composed
 * only from the alert-card values (decision 2026-07-10: no generative model —
 * zero hallucination surface).
 *
 * Idle (nothing selected) = Option B state briefing: live aggregates + the
 * top active watches as real-imagery chips. The auto-tour and pixel-counting
 * analytics are Phase 2.
 *
 * Honesty labels: Esri imagery is REFERENCE context (capture date varies),
 * never presented as the detection-time image — detection is our SAR/NDVI.
 * All imagery is plain <img> (CSP img-src allows https:) — no new WebGL
 * context, so the deck.gl perf discipline is untouched.
 */

// ─── Esri endpoints (keyless; verified live over Nigeria 2026-07) ─────────
const ESRI_TILE = (z: number, x: number, y: number) =>
  `https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${y}/${x}`;
const WAYBACK_TILE = (release: number, z: number, x: number, y: number) =>
  `https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/WMTS/1.0.0/default028mm/MapServer/tile/${release}/${z}/${y}/${x}`;
// One old + one recent Wayback release (same pair as the Farmland map slider).
const WAYBACK_OLD = { release: 10, label: '2014' };
const WAYBACK_NEW = { release: 10842, label: '2026' };

const LULC_IMAGE = (lat: number, lon: number, year: number, halfM = 3000) => {
  const R = 20037508.34;
  const mx = (lon * R) / 180;
  const my = ((Math.log(Math.tan(((90 + lat) * Math.PI) / 360)) / (Math.PI / 180)) * R) / 180;
  const bbox = `${mx - halfM},${my - halfM},${mx + halfM},${my + halfM}`;
  return (
    'https://ic.imagery1.arcgis.com/arcgis/rest/services/Sentinel2_10m_LandCover/ImageServer/exportImage' +
    `?f=image&bbox=${bbox}&bboxSR=3857&imageSR=3857&size=300,300&format=png32&transparent=true` +
    `&time=${Date.UTC(year, 6, 1)}`
  );
};

// ─── Web-Mercator tile math ────────────────────────────────────────────────
function tileAt(lat: number, lon: number, z: number) {
  const n = 2 ** z;
  const xf = ((lon + 180) / 360) * n;
  const yf = ((1 - Math.asinh(Math.tan((lat * Math.PI) / 180)) / Math.PI) / 2) * n;
  return { x: Math.floor(xf), y: Math.floor(yf), fx: xf - Math.floor(xf), fy: yf - Math.floor(yf) };
}

/** Metres per pixel at this latitude/zoom (for the to-scale area box). */
function metresPerPixel(lat: number, z: number): number {
  return (156543.03392 * Math.cos((lat * Math.PI) / 180)) / 2 ** z;
}

const HERO_ZOOM = 15;
const HERO_H = 300;

// Zoom-from-orbit intro: static Esri tiles cross-fading through these zoom
// levels (space → region → district → plot). Pure <img> + CSS — deliberately
// NO WebGL map, so the cinematic runs on low-spec government PCs. Skipped
// entirely under prefers-reduced-motion.
const INTRO_ZOOMS = [4, 8, 12, 15] as const;
const INTRO_STEP_MS = 550;

const SEV_RANK: Record<AlertSeverity, number> = { critical: 0, high: 1, medium: 2, low: 3 };
const SEV_COLOR: Record<AlertSeverity, string> = {
  critical: '#ff4500', high: '#ff8c00', medium: '#f0af3c', low: '#52b788',
};

/** "radar land-surface change 5.6σ" → "5.6σ" (from the alert's own zone_name). */
function sigmaOf(a: AlertResponse): string | null {
  const m = a.zone_name?.match(/(\d+(?:\.\d+)?)\s*σ/);
  return m ? `${m[1]}σ` : null;
}

/** The deterministic summary — composed ONLY from this alert's card values
 *  (+ the reverse-geocoded place name). No generative model by design. */
function composeSummary(a: AlertResponse, place: string | null): string {
  const parts: string[] = [];
  const sig = sigmaOf(a);
  const where = place ?? (a.lga ? `${a.lga} LGA` : 'this location');
  parts.push(
    sig
      ? `Radar detects a ${sig} land-surface change near ${where}.`
      : `${a.alert_type === 'conflict' ? 'Land-disturbance risk' : 'Alert'} detected near ${where}.`,
  );
  if (a.affected_area_ha != null && a.livelihoods_at_risk != null) {
    parts.push(
      `~${Math.round(a.affected_area_ha)} ha exposed affecting ~${a.livelihoods_at_risk.toLocaleString()} livelihoods.`,
    );
  }
  if (a.confidence_score != null) parts.push(`Confidence ${Math.round(a.confidence_score * 100)}%.`);
  if (a.status === 'resolved') parts.push('Resolved via agency response.');
  else if (a.predicted_breach_hours != null) {
    parts.push(`Field verification recommended within ${a.predicted_breach_hours} h.`);
  }
  return parts.join(' ');
}

// ─── Shared style atoms (dark panel matching the map canvas) ───────────────
const S = {
  panel: {
    marginTop: '10px', background: '#1e1a16', border: '1px solid #33291f',
    borderRadius: '10px', padding: '14px 16px', color: '#f5f2ee',
    fontFamily: 'ui-monospace, Consolas, monospace',
  } as React.CSSProperties,
  eyebrow: { fontSize: '10px', letterSpacing: '.18em', color: '#52b788', marginBottom: '4px' } as React.CSSProperties,
  h: { fontSize: '19px', fontWeight: 700, lineHeight: 1.15 } as React.CSSProperties,
  muted: { color: '#a89f93', fontSize: '11px' } as React.CSSProperties,
  dim: { color: '#6e6459', fontSize: '9.5px', lineHeight: 1.6 } as React.CSSProperties,
  card: {
    background: 'rgba(255,255,255,0.03)', border: '1px solid #33291f',
    borderRadius: '8px', padding: '10px 12px',
  } as React.CSSProperties,
  cardH: { fontSize: '9.5px', letterSpacing: '.16em', color: '#a89f93', fontWeight: 700, marginBottom: '8px' } as React.CSSProperties,
  statV: { fontSize: '17px', fontWeight: 700 } as React.CSSProperties,
  statK: { fontSize: '9px', letterSpacing: '.12em', color: '#6e6459', marginTop: '1px' } as React.CSSProperties,
};

interface Props {
  alerts: AlertResponse[];
  selected: AlertResponse | null;
  stateLabel: string;
  onSelect: (id: string) => void;
  onClose: () => void;
  /** Auto-tour (Phase 2): true while the panel is cycling watches. */
  touring: boolean;
  onToggleTour: () => void;
}

export default function AlertSpotlight(props: Props) {
  const { alerts, selected, stateLabel, onSelect, onClose, touring, onToggleTour } = props;
  const [place, setPlace] = useState<string | null>(null);

  // Reverse-geocode the selected coordinate (same Mapbox helper Farm Check uses).
  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset stale place for the new selection
    setPlace(null);
    if (selected?.location) {
      fetchPlaceName(selected.location.lon, selected.location.lat).then((p) => {
        if (!cancelled) setPlace(p);
      });
    }
    return () => { cancelled = true; };
    // Primitive deps (id + coords) — the location OBJECT gets a fresh identity
    // on every feed refetch, which would re-fire the geocode for no reason.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.id, selected?.location?.lat, selected?.location?.lon]);

  const active = useMemo(() => alerts.filter((a) => a.status !== 'resolved'), [alerts]);
  const topWatches = useMemo(
    () =>
      active
        .filter((a) => a.location)
        .sort((a, b) =>
          SEV_RANK[a.severity] !== SEV_RANK[b.severity]
            ? SEV_RANK[a.severity] - SEV_RANK[b.severity]
            : (b.confidence_score ?? 0) - (a.confidence_score ?? 0),
        )
        .slice(0, 3),
    [active],
  );

  if (!selected || !selected.location) {
    return (
      <IdleBriefing
        active={active}
        topWatches={topWatches}
        stateLabel={stateLabel}
        onSelect={onSelect}
        onStartTour={onToggleTour}
      />
    );
  }
  return (
    <SelectedBriefing
      alert={selected}
      place={place}
      stateLabel={stateLabel}
      onClose={onClose}
      touring={touring}
      onToggleTour={onToggleTour}
    />
  );
}

// ─── Idle state — Option B: calm state briefing ────────────────────────────
function IdleBriefing(props: {
  active: AlertResponse[];
  topWatches: AlertResponse[];
  stateLabel: string;
  onSelect: (id: string) => void;
  onStartTour: () => void;
}) {
  const { active, topWatches, stateLabel, onSelect, onStartTour } = props;
  const tourable = active.filter((a) => a.location).length;
  const totalHa = active.reduce((s, a) => s + (a.affected_area_ha ?? 0), 0);
  const totalLiv = active.reduce((s, a) => s + (a.livelihoods_at_risk ?? 0), 0);
  const etas = active.map((a) => a.predicted_breach_hours).filter((h): h is number => h != null);
  const earliestEta = etas.length ? Math.min(...etas) : null;

  return (
    <div style={S.panel} aria-label={`Farmland briefing — ${stateLabel}`}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px' }}>
        <div>
          <div style={S.eyebrow}>⊕ ALERT SPOTLIGHT — NO ALERT SELECTED</div>
          <div style={S.h}>{stateLabel} · overview</div>
          <div style={{ ...S.muted, marginTop: '3px' }}>
            click a pulsing halo on the map — or “Spotlight” on any alert card
          </div>
        </div>
        <div style={{ display: 'flex', gap: '18px', textAlign: 'right' }}>
          <div><div style={S.statV}>{active.length}</div><div style={S.statK}>WATCHES</div></div>
          <div><div style={S.statV}>~{Math.round(totalHa).toLocaleString()}</div><div style={S.statK}>HA AT RISK</div></div>
          <div><div style={S.statV}>~{totalLiv.toLocaleString()}</div><div style={S.statK}>LIVELIHOODS</div></div>
          <div><div style={S.statV}>{earliestEta != null ? `${earliestEta}h` : '—'}</div><div style={S.statK}>EARLIEST ETA</div></div>
        </div>
      </div>

      {topWatches.length > 0 && (
        <div style={{ marginTop: '12px' }}>
          <div style={S.cardH}>TOP WATCHES — TAP TO SPOTLIGHT</div>
          <div style={{ display: 'grid', gridTemplateColumns: `repeat(${topWatches.length}, 1fr)`, gap: '9px' }}>
            {topWatches.map((a) => {
              const t = tileAt(a.location!.lat, a.location!.lon, 14);
              return (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => onSelect(a.id)}
                  style={{
                    position: 'relative', borderRadius: '6px', overflow: 'hidden',
                    border: '1px solid #33291f', padding: 0, cursor: 'pointer',
                    height: '86px', background: '#0f0d0b',
                  }}
                  aria-label={`Spotlight ${a.lga ?? a.zone_name ?? 'alert'}`}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element -- external Esri tile, not an optimizable asset */}
                  <img
                    src={ESRI_TILE(14, t.x, t.y)}
                    alt=""
                    style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block', opacity: 0.9 }}
                    loading="lazy"
                  />
                  <span
                    style={{
                      position: 'absolute', left: 0, right: 0, bottom: 0,
                      padding: '3px 7px', fontSize: '9px', letterSpacing: '.1em',
                      background: 'linear-gradient(transparent, rgba(15,13,11,0.92))',
                      color: '#f5f2ee', textAlign: 'left',
                    }}
                  >
                    {(a.lga ?? '').toUpperCase()}{' '}
                    <em style={{ fontStyle: 'normal', color: SEV_COLOR[a.severity] }}>
                      {sigmaOf(a) ?? a.severity}
                    </em>
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginTop: '11px', flexWrap: 'wrap' }}>
        {tourable >= 2 && (
          <button
            type="button"
            onClick={onStartTour}
            style={{
              border: '1px solid #52b788', color: '#52b788', background: 'transparent',
              fontSize: '10.5px', letterSpacing: '.12em', padding: '5px 13px',
              borderRadius: '5px', cursor: 'pointer', font: 'inherit',
            }}
          >
            ▶ START TOUR ({tourable} WATCHES)
          </button>
        )}
        <span style={S.dim}>
          Aggregates: live alert feed · hotspot chips: Esri World Imagery at each alert coordinate (reference)
        </span>
      </div>
    </div>
  );
}

// ─── Zoom-from-orbit intro — static Esri tiles + CSS only (no WebGL) ───────
// One tile per zoom step, anchored so the alert coordinate stays dead-centre
// while each frame scales up, then unmounts to reveal the sharp 3×3 mosaic
// underneath. Remounted per selection via key={alert.id}.
function IntroZoom({ lat, lon }: { lat: number; lon: number }) {
  const [step, setStep] = useState(0);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- reduced motion: skip the cinematic entirely
      setDone(true);
      return;
    }
    const timers: number[] = [];
    INTRO_ZOOMS.forEach((_, i) => {
      timers.push(window.setTimeout(() => setStep(i), i * INTRO_STEP_MS));
    });
    timers.push(window.setTimeout(() => setDone(true), INTRO_ZOOMS.length * INTRO_STEP_MS + 180));
    return () => timers.forEach((t) => window.clearTimeout(t));
  }, []);

  if (done) return null;
  const z = INTRO_ZOOMS[step];
  const t = tileAt(lat, lon, z);
  return (
    <div style={{ position: 'absolute', inset: 0, background: '#0f0d0b', overflow: 'hidden' }} aria-hidden>
      {/* eslint-disable-next-line @next/next/no-img-element -- external Esri tile */}
      <img
        key={z}
        src={ESRI_TILE(z, t.x, t.y)}
        alt=""
        className="ebspot-zoomframe"
        style={{
          position: 'absolute', left: '50%', top: '50%',
          width: '256px', height: '256px',
          marginLeft: `${-t.fx * 256}px`, marginTop: `${-t.fy * 256}px`,
          transformOrigin: `${t.fx * 256}px ${t.fy * 256}px`,
        }}
      />
      <span
        style={{
          position: 'absolute', bottom: '9px', left: '9px', fontSize: '9px',
          letterSpacing: '.16em', color: '#52b788', padding: '3px 8px',
          background: 'rgba(15,13,11,0.78)', borderRadius: '3px',
        }}
      >
        ACQUIRING · ESRI WORLD IMAGERY · Z{z}
      </span>
    </div>
  );
}

// ─── Computed land-mix bars (Phase 2 pixel analytics) ──────────────────────
function LandMixBars({ cmp }: { cmp: LandCoverComparison }) {
  const rows = [
    { year: cmp.yearA, mix: cmp.mixA },
    { year: cmp.yearB, mix: cmp.mixB },
  ];
  const growing = cmp.builtDeltaPts > 0;
  return (
    <div style={{ marginTop: '9px' }}>
      {rows.map(({ year, mix }) => (
        <div key={year} style={{ marginBottom: '6px' }}>
          <div style={{ ...S.dim, letterSpacing: '.1em' }}>{year}</div>
          <div style={{ display: 'flex', height: '11px', borderRadius: '3px', overflow: 'hidden', margin: '2px 0' }}>
            {topClasses(mix, 4).map(([label, pct]) => (
              <div key={label} style={{ width: `${pct}%`, background: classColor(label) }} title={`${label} ${pct}%`} />
            ))}
          </div>
          <div style={{ ...S.dim, display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
            {topClasses(mix, 3).map(([label, pct]) => (
              <span key={label}>{label} {pct}%</span>
            ))}
          </div>
        </div>
      ))}
      <div
        style={{
          marginTop: '7px', padding: '6px 9px', borderRadius: '5px', fontSize: '11px',
          background: growing ? 'rgba(240,175,60,0.10)' : 'rgba(82,183,136,0.10)',
          border: `1px solid ${growing ? 'rgba(240,175,60,0.3)' : 'rgba(82,183,136,0.3)'}`,
          color: growing ? '#f0af3c' : '#52b788',
        }}
      >
        {growing
          ? `▲ built-up +${cmp.builtDeltaPts} pts since ${cmp.yearA} — settlement pressure`
          : `built-up stable since ${cmp.yearA} (${cmp.builtDeltaPts >= 0 ? '+' : ''}${cmp.builtDeltaPts} pts)`}
      </div>
      <div style={{ ...S.dim, marginTop: '4px' }}>
        Computed in-browser from Esri 10 m land-cover pixels within {cmp.radiusKm} km of the alert — deterministic, no model.
      </div>
    </div>
  );
}

// ─── Selected state — coordinate briefing ─────────────────────────────────
function SelectedBriefing(props: {
  alert: AlertResponse;
  place: string | null;
  stateLabel: string;
  onClose: () => void;
  touring: boolean;
  onToggleTour: () => void;
}) {
  const { alert: a, place, stateLabel, onClose, touring, onToggleTour } = props;
  const lat = a.location!.lat;
  const lon = a.location!.lon;
  const t = tileAt(lat, lon, HERO_ZOOM);
  const tOld = tileAt(lat, lon, 14);

  // Phase 2 pixel analytics — computed land mix around this alert, 2018 vs
  // 2025. Null (service gap / low coverage / tainted canvas) → the card
  // falls back to thumbnails only; never publish a number we couldn't count.
  const [landCmp, setLandCmp] = useState<LandCoverComparison | null>(null);
  const [landPending, setLandPending] = useState(false);
  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset for the new selection
    setLandCmp(null);
    setLandPending(true);
    compareLandCover(lat, lon).then((cmp) => {
      if (cancelled) return;
      setLandCmp(cmp);
      setLandPending(false);
    });
    return () => { cancelled = true; };
  }, [lat, lon]);

  // To-scale affected-area box: side = sqrt(ha) in metres → hero pixels.
  // Cheap arithmetic — computed inline, no memo needed.
  let boxPx: number | null = null;
  if (a.affected_area_ha != null) {
    const sideM = Math.sqrt(a.affected_area_ha * 10_000);
    const px = sideM / metresPerPixel(lat, HERO_ZOOM);
    boxPx = Math.min(Math.max(px, 26), HERO_H - 40);
  }

  const sig = sigmaOf(a);
  const detected = new Date(a.created_at).toISOString().slice(0, 10);

  return (
    <div style={S.panel} aria-label={`Alert spotlight — ${a.lga ?? stateLabel}`}>
      {/* Pulse keyframes; disabled under prefers-reduced-motion. */}
      <style>{`
        @keyframes ebspot-pulse { 0% { transform: scale(.4); opacity: .9; } 100% { transform: scale(1.6); opacity: 0; } }
        @keyframes ebspot-zoom { 0% { transform: scale(2.4); opacity: .15; } 100% { transform: scale(4.4); opacity: 1; } }
        .ebspot-zoomframe { animation: ebspot-zoom ${INTRO_STEP_MS + 40}ms ease-out forwards; }
        @media (prefers-reduced-motion: reduce) {
          .ebspot-ring, .ebspot-zoomframe { animation: none !important; }
        }
      `}</style>

      <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px' }}>
        <div>
          <div style={S.eyebrow}>⊕ ALERT SPOTLIGHT</div>
          <div style={S.h}>{a.lga ? `${a.lga} · ${stateLabel}` : stateLabel}</div>
          <div style={{ ...S.muted, marginTop: '3px' }}>
            {lat.toFixed(4)}°N, {lon.toFixed(4)}°E
            {place ? ` · 📍 ${place}` : ''} · detected {detected}
          </div>
          <div style={{ display: 'flex', gap: '6px', marginTop: '7px', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '10px', fontWeight: 700, letterSpacing: '.1em', padding: '2px 8px', borderRadius: '3px', background: 'rgba(240,175,60,0.16)', color: SEV_COLOR[a.severity] }}>
              {a.status === 'resolved' ? 'RESOLVED' : a.severity.toUpperCase()}
            </span>
            {sig && (
              <span style={{ fontSize: '10px', padding: '2px 8px', borderRadius: '3px', background: 'rgba(255,255,255,0.07)' }}>
                radar land-surface change {sig}
              </span>
            )}
          </div>
        </div>
        <div style={{ display: 'flex', gap: '16px', textAlign: 'right', alignItems: 'flex-start' }}>
          <div><div style={S.statV}>{a.affected_area_ha != null ? `~${Math.round(a.affected_area_ha)}` : '—'}</div><div style={S.statK}>HA AT RISK</div></div>
          <div><div style={S.statV}>{a.livelihoods_at_risk != null ? `~${a.livelihoods_at_risk.toLocaleString()}` : '—'}</div><div style={S.statK}>LIVELIHOODS</div></div>
          <div><div style={S.statV}>{a.confidence_score != null ? `${Math.round(a.confidence_score * 100)}%` : '—'}</div><div style={S.statK}>CONFIDENCE</div></div>
          <div><div style={S.statV}>{a.predicted_breach_hours != null ? `${a.predicted_breach_hours}h` : '—'}</div><div style={S.statK}>ETA</div></div>
          {touring && (
            <button
              type="button"
              onClick={onToggleTour}
              style={{
                background: 'rgba(82,183,136,0.12)', border: '1px solid #52b788',
                color: '#52b788', borderRadius: '5px', cursor: 'pointer',
                fontSize: '10px', letterSpacing: '.1em', padding: '3px 9px', font: 'inherit',
              }}
            >
              ▶ TOUR · STOP
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="Close spotlight"
            style={{ background: 'transparent', border: '1px solid #33291f', color: '#a89f93', borderRadius: '5px', cursor: 'pointer', fontSize: '11px', padding: '3px 9px' }}
          >
            ✕
          </button>
        </div>
      </div>

      {/* Hero — 3×3 Esri tile mosaic, coordinate dead-centre. */}
      <div
        style={{
          position: 'relative', marginTop: '12px', height: `${HERO_H}px`,
          borderRadius: '8px', overflow: 'hidden', border: '1px solid #33291f',
          background: '#0f0d0b',
        }}
      >
        <div
          style={{
            position: 'absolute', left: '50%', top: '50%', width: '768px', height: '768px',
            transform: `translate(${-(256 + t.fx * 256)}px, ${-(256 + t.fy * 256)}px)`,
          }}
        >
          {[-1, 0, 1].map((dy) =>
            [-1, 0, 1].map((dx) => (
              // eslint-disable-next-line @next/next/no-img-element -- external Esri tiles
              <img
                key={`${dx}:${dy}`}
                src={ESRI_TILE(HERO_ZOOM, t.x + dx, t.y + dy)}
                alt=""
                style={{ position: 'absolute', left: `${(dx + 1) * 256}px`, top: `${(dy + 1) * 256}px`, width: '256px', height: '256px' }}
                loading="lazy"
              />
            )),
          )}
        </div>
        {/* to-scale affected-area box */}
        {boxPx != null && (
          <div
            style={{
              position: 'absolute', left: '50%', top: '50%',
              width: `${boxPx}px`, height: `${boxPx}px`,
              transform: 'translate(-50%, -50%)',
              border: '1.5px dashed rgba(240,175,60,0.85)', borderRadius: '2px',
            }}
          >
            <span style={{ position: 'absolute', top: '-15px', left: 0, fontSize: '8.5px', color: '#f0af3c', letterSpacing: '.1em' }}>
              ~{Math.round(a.affected_area_ha!)} HA (TO SCALE)
            </span>
          </div>
        )}
        {/* crosshair + pulse ring on the exact coordinate */}
        <div style={{ position: 'absolute', left: '50%', top: '50%' }} aria-hidden>
          <span className="ebspot-ring" style={{ position: 'absolute', left: '-24px', top: '-24px', width: '48px', height: '48px', borderRadius: '50%', border: '1.5px solid rgba(82,183,136,0.9)', animation: 'ebspot-pulse 2s ease-out infinite' }} />
          <span style={{ position: 'absolute', left: '-13px', top: '-0.5px', width: '8px', height: '1px', background: 'rgba(245,242,238,0.9)', boxShadow: '18px 0 rgba(245,242,238,0.9)' }} />
          <span style={{ position: 'absolute', left: '-0.5px', top: '-13px', width: '1px', height: '8px', background: 'rgba(245,242,238,0.9)', boxShadow: '0 18px rgba(245,242,238,0.9)' }} />
        </div>
        <span style={{ position: 'absolute', top: '9px', left: '9px', fontSize: '9px', letterSpacing: '.13em', padding: '3px 8px', background: 'rgba(15,13,11,0.78)', borderRadius: '3px', color: '#4da3d8' }}>
          ESRI WORLD IMAGERY · REFERENCE (NOT DETECTION-TIME)
        </span>
        {/* Zoom-from-orbit intro — plays once per selection, unmounts to the mosaic. */}
        <IntroZoom key={a.id} lat={lat} lon={lon} />
      </div>

      {/* Evidence strip + deterministic summary */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '12px', marginTop: '12px' }}>
        <div style={S.card}>
          <div style={S.cardH}>SAME GROUND OVER TIME — ESRI WAYBACK + 10 M LAND COVER</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px' }}>
            {[
              { src: WAYBACK_TILE(WAYBACK_OLD.release, 14, tOld.x, tOld.y), cap: WAYBACK_OLD.label, pixel: false },
              { src: WAYBACK_TILE(WAYBACK_NEW.release, 14, tOld.x, tOld.y), cap: WAYBACK_NEW.label, pixel: false },
              { src: LULC_IMAGE(lat, lon, 2018), cap: 'land 2018', pixel: true },
              { src: LULC_IMAGE(lat, lon, 2025), cap: 'land 2025', pixel: true },
            ].map((f) => (
              <figure key={f.cap} style={{ position: 'relative', margin: 0, borderRadius: '5px', overflow: 'hidden', border: '1px solid #33291f', aspectRatio: '1', background: '#0f0d0b' }}>
                {/* eslint-disable-next-line @next/next/no-img-element -- external Esri imagery */}
                <img
                  src={f.src}
                  alt={f.cap}
                  style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block', imageRendering: f.pixel ? 'pixelated' : 'auto' }}
                  loading="lazy"
                />
                <figcaption style={{ position: 'absolute', left: 0, right: 0, bottom: 0, padding: '2px 6px', fontSize: '8.5px', letterSpacing: '.1em', background: 'linear-gradient(transparent, rgba(15,13,11,0.92))' }}>
                  {f.cap.toUpperCase()}
                </figcaption>
              </figure>
            ))}
          </div>
          <div style={{ ...S.dim, marginTop: '7px' }}>
            Land-cover colours: yellow crops · red built · tan rangeland · green trees · blue water
            (© Esri, Impact Observatory, Microsoft)
          </div>
          {landCmp ? (
            <LandMixBars cmp={landCmp} />
          ) : landPending ? (
            <div style={{ ...S.dim, marginTop: '8px' }}>computing land mix from classification pixels…</div>
          ) : null}
        </div>

        <div style={S.card}>
          <div style={S.cardH}>SUMMARY — COMPOSED FROM THIS ALERT&apos;S VALUES</div>
          <div style={{ fontSize: '12px', lineHeight: 1.7 }}>{composeSummary(a, place)}</div>
          <div style={{ ...S.dim, marginTop: '8px' }}>
            Deterministic — assembled from the alert card&apos;s detection values only, no generative model.
            {a.satellite_source ? ` Detection: ${a.satellite_source}.` : ''}
            {' '}Context imagery: Esri (reference) · place name: Mapbox.
          </div>
        </div>
      </div>
    </div>
  );
}
