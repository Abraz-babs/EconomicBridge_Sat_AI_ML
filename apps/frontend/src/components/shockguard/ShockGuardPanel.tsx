'use client';

import { useEffect, useMemo, useState } from 'react';

import { useTenant } from '@/context/TenantContext';
import {
  useShockEvents,
  useShockScan,
  type DataSource,
  type ShockEventType,
  type ShockScanData,
} from '@/hooks/useShockGuard';
import ShockEventsMap from './ShockEventsMap';


const STATE_NAMES: Record<string, string> = {
  kebbi: 'Kebbi State', benue: 'Benue State', plateau: 'Plateau State',
  kaduna: 'Kaduna State', niger: 'Niger State', zamfara: 'Zamfara State',
  nasarawa: 'Nasarawa State', fct: 'Federal Capital Territory',
  ghana: 'Ghana', senegal: 'Senegal',
};


function fmtNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return n.toLocaleString();
}

function fmtAge(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return 'just now';
  const min = Math.round(ms / 60_000);
  if (min < 60) return `${min} min ago`;
  const hr = Math.round(min / 60);
  if (hr < 48) return `${hr} hr ago`;
  return `${Math.round(hr / 24)} d ago`;
}

function bandClass(b: 'HIGH' | 'MEDIUM' | 'LOW'): string {
  return `cg-band cg-band-${b.toLowerCase()}`;
}

function sevClass(s: string): string {
  const map: Record<string, string> = {
    critical: 'fp-sev-crit', high: 'fp-sev-high',
    medium: 'fp-sev-med', low: 'fp-sev-med',
  };
  return `fp-sev ${map[s] ?? 'fp-sev-med'}`;
}


export default function ShockGuardPanel() {
  const { activeTenantId, activeTenant, pilotTenants, setActiveTenant } = useTenant();
  const [eventType, setEventType] = useState<ShockEventType>('flood');
  const [demoMode, setDemoMode] = useState(true);
  const [dataSource, setDataSource] = useState<DataSource>('synthetic');
  const [lastScan, setLastScan] = useState<ShockScanData | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);

  const scanMutation = useShockScan(activeTenantId);
  const eventsQuery = useShockEvents({ tenantId: activeTenantId, limit: 10 });

  // Live mode for drought stays a Phase B story (MODIS LST not ingested
  // yet) — flip the switch back when the user picks drought.
  const effectiveDataSource: DataSource =
    dataSource === 'live' && eventType === 'drought' ? 'synthetic' : dataSource;
  // Demo injection is meaningless against real satellite data — can't
  // inject into rows you don't own.
  const demoEffective = effectiveDataSource === 'live' ? false : demoMode;

  // Auto-scan on tenant/event-type/demo-mode/source change so the chart isn't empty.
  useEffect(() => {
    if (!activeTenantId) return;
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setScanError(null);
    setLastScan(null);
    scanMutation
      .mutateAsync({
        event_type: eventType, persist: false,
        demo_inject_anomaly: demoEffective,
        data_source: effectiveDataSource,
      })
      .then((data) => { if (!cancelled) setLastScan(data); })
      .catch((err) => {
        if (cancelled) return;
        setScanError(err instanceof Error ? err.message : 'Scan failed');
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTenantId, eventType, demoEffective, effectiveDataSource]);

  async function persistScan() {
    setScanError(null);
    try {
      const result = await scanMutation.mutateAsync({
        event_type: eventType, persist: true,
        demo_inject_anomaly: demoEffective,
        data_source: effectiveDataSource,
      });
      setLastScan(result);
    } catch (err) {
      setScanError(err instanceof Error ? err.message : 'Scan failed');
    }
  }

  const stateLabel = STATE_NAMES[activeTenantId] ?? activeTenant.name;
  const events = eventsQuery.data?.events ?? [];
  const lastScanAt = eventsQuery.data?.lastScanAt ?? null;
  const activeShockCount = eventsQuery.data?.activeShockCount ?? 0;

  return (
    <div>
      {/* HEADER */}
      <div className="cg-header">
        <div>
          <div className="cg-title">ShockGuard — Disaster Early Warning</div>
          <div className="cg-subtitle">
            48-hour flood + drought advance alerts · Sentinel-1 SAR backscatter ·
            MODIS thermal + NDVI composite
          </div>
        </div>
        <div
          className={`cg-mode-badge ${
            effectiveDataSource === 'live' ? 'cg-mode-trained' : 'cg-mode-untuned'
          }`}
        >
          {effectiveDataSource === 'live'
            ? 'LIVE · sentinel_stat_v1'
            : 'DETECTOR · synthetic series'}
        </div>
      </div>

      {/* TENANT SELECTOR */}
      <div className="fp-tenant-bar">
        <label htmlFor="sg-tenant-select" className="fp-tenant-label">Viewing tenant</label>
        <select
          id="sg-tenant-select"
          className="fp-tenant-select"
          value={activeTenantId}
          onChange={(e) => setActiveTenant(e.target.value)}
        >
          {pilotTenants.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
        <button
          type="button"
          className="fp-refresh-btn"
          onClick={() => eventsQuery.refetch()}
          disabled={eventsQuery.isFetching}
        >
          {eventsQuery.isFetching ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {/* MONITORING STATUS — proves the daily scan is live even when (correctly)
          no flood/drought is active, so an episodic feed never reads as stale. */}
      {lastScanAt && (
        <div
          style={{
            display: 'flex', alignItems: 'center', gap: '8px',
            margin: '4px 0 12px', padding: '7px 12px', borderRadius: '6px',
            fontSize: '12.5px',
            background: activeShockCount > 0 ? 'rgba(234,179,8,0.10)' : 'rgba(34,197,94,0.10)',
            border: `1px solid ${activeShockCount > 0 ? 'rgba(234,179,8,0.35)' : 'rgba(34,197,94,0.30)'}`,
            color: 'var(--text-secondary, #94a3b8)',
          }}
        >
          <span
            aria-hidden
            style={{
              width: '8px', height: '8px', borderRadius: '50%',
              background: activeShockCount > 0 ? '#eab308' : '#22c55e',
              boxShadow: `0 0 6px ${activeShockCount > 0 ? '#eab308' : '#22c55e'}`,
              flexShrink: 0,
            }}
          />
          <span>
            Continuously monitored · last scan <strong>{fmtAge(lastScanAt)}</strong> ·{' '}
            {activeShockCount > 0
              ? `${activeShockCount} active shock${activeShockCount > 1 ? 's' : ''}`
              : 'no active flood/drought signal'}
          </span>
        </div>
      )}

      {/* STATS */}
      {lastScan && (
        <div className="fp-grid">
          <div className={`fp-stat ${lastScan.triggered ? 'crit' : 'ok'}`}>
            <div className="fp-stat-label">Event Status</div>
            <div className="fp-stat-val">
              {lastScan.triggered ? '⚠' : '✓'}
            </div>
            <div className="fp-stat-sub">
              {lastScan.triggered
                ? `${lastScan.event_type.toUpperCase()} flagged · ${lastScan.severity}`
                : `No ${lastScan.event_type} activity · baseline holding`}
            </div>
          </div>
          <div className="fp-stat warn">
            <div className="fp-stat-label">Lead Time</div>
            <div className="fp-stat-val">{lastScan.projected_onset_hours}h</div>
            <div className="fp-stat-sub">Projected onset window</div>
          </div>
          <div className="fp-stat crit">
            <div className="fp-stat-label">Population at Risk</div>
            <div className="fp-stat-val">{fmtNum(lastScan.population_at_risk)}</div>
            <div className="fp-stat-sub">
              ~{lastScan.affected_area_km2.toFixed(0)} km² affected
            </div>
          </div>
          <div className="fp-stat ok">
            <div className="fp-stat-label">Confidence</div>
            <div className="fp-stat-val">{Math.round(lastScan.confidence * 100)}%</div>
            <div className="fp-stat-sub">
              <span className={bandClass(lastScan.confidence_band)}>
                {lastScan.confidence_band}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* DETECTOR CONTROLS */}
      <div className="cg-market" data-no-bg="true">
        <div className="cg-section-header">Run Detector — {stateLabel}</div>

        <div className="cg-ndvi-controls">
          <div className="cg-mode-switch">
            <button
              type="button"
              className={`cg-mode-btn ${eventType === 'flood' ? 'is-active' : ''}`}
              onClick={() => setEventType('flood')}
              disabled={scanMutation.isPending}
            >
              Flood
            </button>
            <button
              type="button"
              className={`cg-mode-btn ${eventType === 'drought' ? 'is-active' : ''}`}
              onClick={() => setEventType('drought')}
              disabled={scanMutation.isPending}
            >
              Drought
            </button>
          </div>
          <div className="cg-mode-switch" aria-label="ShockGuard data source">
            <button
              type="button"
              className={`cg-mode-btn ${effectiveDataSource === 'synthetic' ? 'is-active' : ''}`}
              onClick={() => setDataSource('synthetic')}
              disabled={scanMutation.isPending}
              title="Deterministic per-tenant series (no live API calls)"
            >
              Synthetic
            </button>
            <button
              type="button"
              className={`cg-mode-btn ${effectiveDataSource === 'live' ? 'is-active' : ''}`}
              onClick={() => setDataSource('live')}
              disabled={scanMutation.isPending || eventType === 'drought'}
              title={
                eventType === 'drought'
                  ? 'Live drought needs MODIS LST ingestion (Phase B)'
                  : 'Read real Sentinel-1 SAR from satellite_observations'
              }
            >
              Live
            </button>
          </div>
          <label className="cg-saliency-toggle">
            <input
              type="checkbox"
              checked={demoMode}
              onChange={(e) => setDemoMode(e.target.checked)}
              disabled={scanMutation.isPending || effectiveDataSource === 'live'}
            />
            <span>
              Demo mode (inject synthetic anomaly)
              {effectiveDataSource === 'live' && ' — N/A in live mode'}
            </span>
          </label>
          <button
            type="button"
            className="cg-yield-btn"
            onClick={persistScan}
            disabled={scanMutation.isPending}
          >
            {scanMutation.isPending ? 'Scanning…' : 'Persist scan to audit log'}
          </button>
        </div>

        {scanError && <div className="fp-alert-error">{scanError}</div>}

        {lastScan?.notice && (
          <div className="fp-alert-notice">{lastScan.notice}</div>
        )}

        {lastScan && <ShockScanCard scan={lastScan} />}
      </div>

      {/* MAP + EVENTS */}
      <div className="fp-main-row">
        <div className="fp-map">
          <div className="fp-map-header">
            <span className="fp-map-title">
              Event Map — {stateLabel}
            </span>
            <span className="ev-map-meta">
              {events.length} event{events.length === 1 ? '' : 's'} ·
              live per-LGA Sentinel scan + labelled historical examples
            </span>
          </div>
          <ShockEventsMap tenant={activeTenant} events={events} />
        </div>

        <div className="fp-alerts">
          <div className="fp-alerts-header">
            Recent Events — {stateLabel}
            <span className="fp-alert-count">{events.length}</span>
          </div>
          {eventsQuery.isLoading && (
            <div className="fp-alert-empty">Loading audit log…</div>
          )}
          {!eventsQuery.isLoading && events.length === 0 && (
            <div className="fp-alert-empty">
              No persisted events yet. Run a scan and click &ldquo;Persist&rdquo; to log it.
            </div>
          )}
          {events.map((ev) => {
            // Live per-LGA scan vs kept historical examples — labelled honestly.
            const isHistorical = ev.source === 'seed_v1';
            return (
            <div key={ev.id} className="fp-alert-item">
              <div className="fp-alert-top">
                <span className="fp-alert-location">
                  {ev.event_type === 'flood' ? '🌊' : '🔥'}{' '}
                  {ev.event_type.toUpperCase()} · {ev.lga ?? stateLabel}
                </span>
                <span style={{
                  fontSize: '9px', fontWeight: 700, letterSpacing: '0.04em',
                  padding: '2px 6px', borderRadius: '8px',
                  background: isHistorical ? 'rgba(148,163,184,0.18)' : 'rgba(34,197,94,0.18)',
                  color: isHistorical ? '#64748b' : '#16a34a',
                  border: `1px solid ${isHistorical ? 'rgba(148,163,184,0.45)' : 'rgba(34,197,94,0.45)'}`,
                }}>{isHistorical ? 'HISTORICAL' : 'LIVE'}</span>
                <span className={sevClass(ev.severity)}>
                  {ev.severity.charAt(0).toUpperCase() + ev.severity.slice(1)}
                </span>
              </div>
              <div className="fp-alert-desc">
                {ev.population_at_risk != null && ev.affected_area_km2 != null ? (
                  <>
                    ~{fmtNum(ev.population_at_risk)} at risk over{' '}
                    {ev.affected_area_km2.toFixed(0)} km²
                    {ev.projected_onset_hours != null
                      ? ` · onset in ${ev.projected_onset_hours}h.`
                      : '.'}
                  </>
                ) : (
                  ev.zone_name ?? 'Satellite-detected signal · ROI-level · under review'
                )}
              </div>
              <div className="fp-alert-meta">
                <span>{ev.detector_name} {ev.detector_version}</span>
                <span className={bandClass(ev.confidence_band)}>{ev.confidence_band}</span>
                <span>{fmtAge(ev.created_at)}</span>
              </div>
            </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}


// ─── Inline scan-result card ──────────────────────────────────────────────


function ShockScanCard({ scan }: { scan: ShockScanData }) {
  const headline = scan.triggered
    ? `${scan.event_type === 'flood' ? '🌊' : '🔥'} ${scan.event_type.toUpperCase()} DETECTED · ${scan.severity}`
    : `No ${scan.event_type} activity · baseline holding`;

  const metricsLine = useMemo(() => {
    if (scan.event_type === 'flood') {
      const m = scan.metrics;
      return `recent ${m.recent_mean_db?.toFixed(2)} dB · baseline ${m.baseline_mean_db?.toFixed(2)} dB · z ${m.z_score?.toFixed(2)}`;
    }
    const m = scan.metrics;
    return `stress mean ${m.recent_stress_mean?.toFixed(2)} · threshold ${m.stress_threshold?.toFixed(2)} · pseudo-z ${m.pseudo_z?.toFixed(2)}`;
  }, [scan]);

  return (
    <div className={`cg-result ${!scan.triggered ? 'cg-result--ok' : ''}`}>
      <div className="cg-result-header">
        <div>
          <div className="cg-result-class">{headline}</div>
          <div className="cg-result-sub">
            Onset in {scan.projected_onset_hours}h ·{' '}
            <span className={bandClass(scan.confidence_band)}>
              {scan.confidence_band}
            </span>
            {scan.persisted && ' · saved to audit log'}
          </div>
        </div>
        <div className={`cg-result-score ${scan.triggered ? 'cg-result-score--bad' : 'cg-result-score--ok'}`}>
          {Math.round(scan.confidence * 100)}
          <span className="cg-result-score-unit">/100</span>
        </div>
      </div>
      <div className="cg-result-footnote">
        {scan.detector_name} {scan.detector_version} · {metricsLine}
      </div>
      {scan.event_type === 'flood' && scan.flood_series.length > 0 && (
        <FloodSparkline series={scan.flood_series} triggered={scan.triggered} />
      )}
      {scan.event_type === 'drought' && scan.drought_series.length > 0 && (
        <DroughtSparkline series={scan.drought_series} triggered={scan.triggered} />
      )}
    </div>
  );
}


// ─── SVG sparklines ──────────────────────────────────────────────────────


function FloodSparkline(props: {
  series: { observed_at: string; backscatter_db: number }[];
  triggered: boolean;
}) {
  const { series, triggered } = props;
  const w = 720, h = 150, padL = 50, padR = 12, padT = 12, padB = 24;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;
  const ys = series.map((p) => p.backscatter_db);
  const yMin = Math.min(...ys) - 0.5;
  const yMax = Math.max(...ys) + 0.5;
  const range = yMax - yMin || 1;
  const xStep = series.length > 1 ? plotW / (series.length - 1) : 0;
  const path = series.map((p, i) => {
    const x = padL + i * xStep;
    const y = padT + plotH - ((p.backscatter_db - yMin) / range) * plotH;
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} role="img"
         aria-label="SAR backscatter time series">
      <text x={padL - 6} y={padT + 8} fontSize="9" fill="var(--muted)" textAnchor="end">{yMax.toFixed(1)}</text>
      <text x={padL - 6} y={padT + plotH} fontSize="9" fill="var(--muted)" textAnchor="end">{yMin.toFixed(1)}</text>
      <text x={padL - 6} y={padT + plotH / 2} fontSize="9" fill="var(--muted)" textAnchor="end">dB</text>
      <path d={path} stroke={triggered ? '#e05a2b' : 'var(--ngo)'} strokeWidth="2" fill="none" />
    </svg>
  );
}


function DroughtSparkline(props: {
  series: { observed_at: string; stress_index: number }[];
  triggered: boolean;
}) {
  const { series, triggered } = props;
  const w = 720, h = 150, padL = 50, padR = 12, padT = 12, padB = 24;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;
  const ys = series.map((p) => p.stress_index);
  const yMin = Math.min(-0.5, Math.min(...ys));
  const yMax = Math.max(1.0, Math.max(...ys));
  const range = yMax - yMin || 1;
  const xStep = series.length > 1 ? plotW / (series.length - 1) : 0;
  const path = series.map((p, i) => {
    const x = padL + i * xStep;
    const y = padT + plotH - ((p.stress_index - yMin) / range) * plotH;
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  // Threshold line at stress = 0.4
  const thresholdY = padT + plotH - ((0.4 - yMin) / range) * plotH;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} role="img"
         aria-label="Drought stress index time series">
      <line x1={padL} x2={w - padR} y1={thresholdY} y2={thresholdY}
            stroke="var(--border2)" strokeDasharray="3 3" />
      <text x={padL - 6} y={thresholdY + 3} fontSize="9" fill="var(--muted)" textAnchor="end">0.4</text>
      <path d={path} stroke={triggered ? '#e05a2b' : 'var(--ngo)'} strokeWidth="2" fill="none" />
    </svg>
  );
}
