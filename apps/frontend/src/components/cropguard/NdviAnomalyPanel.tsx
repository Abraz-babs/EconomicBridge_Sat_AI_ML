'use client';

import { useEffect, useMemo, useState } from 'react';

import { useTenant } from '@/context/TenantContext';
import {
  useNdviAnomalies,
  useScanNdviAnomaly,
  type NdviDataSource,
  type NdviScanData,
} from '@/hooks/useNdviAnomaly';


const RECENT_WINDOW_DAYS = 14;


function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', {
    month: 'short', day: 'numeric',
  });
}

function bandClass(band: 'HIGH' | 'MEDIUM' | 'LOW'): string {
  return `cg-band cg-band-${band.toLowerCase()}`;
}


export default function NdviAnomalyPanel() {
  const { activeTenantId } = useTenant();
  const [lastScan, setLastScan] = useState<NdviScanData | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const [demoMode, setDemoMode] = useState(true);
  const [dataSource, setDataSource] = useState<NdviDataSource>('synthetic');

  const scanMutation = useScanNdviAnomaly(activeTenantId);
  const listQuery = useNdviAnomalies({ tenantId: activeTenantId, limit: 6 });

  // Demo injection is meaningless against real Sentinel-2 rows — you
  // can't inject a synthetic dip into data you don't own.
  const demoEffective = dataSource === 'live' ? false : demoMode;

  // Auto-run scan once per tenant/mode/source change so the chart isn't empty.
  useEffect(() => {
    if (!activeTenantId) return;
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setScanError(null);
    setLastScan(null);
    scanMutation
      .mutateAsync({
        persist: false,
        demo_inject_anomaly: demoEffective,
        data_source: dataSource,
      })
      .then((data) => { if (!cancelled) setLastScan(data); })
      .catch((err) => {
        if (cancelled) return;
        setScanError(err instanceof Error ? err.message : 'Scan failed');
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTenantId, demoEffective, dataSource]);

  async function runConfirmedScan() {
    setScanError(null);
    try {
      const result = await scanMutation.mutateAsync({
        persist: true,
        demo_inject_anomaly: demoEffective,
        data_source: dataSource,
      });
      setLastScan(result);
    } catch (err) {
      setScanError(err instanceof Error ? err.message : 'Scan failed');
    }
  }

  return (
    <div className="cg-market">
      <div className="cg-section-header">
        Pre-symptomatic Disease Detection — NDVI Anomaly
        <span className="ev-map-meta">
          14-day early warning · Sentinel-2 NDVI vs detrended baseline ·{' '}
          <span className={`cg-band ${dataSource === 'live' ? 'cg-band-high' : 'cg-band-low'}`}>
            {dataSource === 'live' ? 'LIVE · sentinel_stat_v1' : 'SYNTHETIC'}
          </span>
        </span>
      </div>

      <div className="cg-ndvi-controls">
        <div className="cg-mode-switch" aria-label="NDVI data source">
          <button
            type="button"
            className={`cg-mode-btn ${dataSource === 'synthetic' ? 'is-active' : ''}`}
            onClick={() => setDataSource('synthetic')}
            disabled={scanMutation.isPending}
            title="Deterministic per-tenant seasonal sinusoid (no live API calls)"
          >
            Synthetic
          </button>
          <button
            type="button"
            className={`cg-mode-btn ${dataSource === 'live' ? 'is-active' : ''}`}
            onClick={() => setDataSource('live')}
            disabled={scanMutation.isPending}
            title="Read real Sentinel-2 NDVI from satellite_observations"
          >
            Live
          </button>
        </div>
        <label className="cg-saliency-toggle">
          <input
            type="checkbox"
            checked={demoMode}
            onChange={(e) => setDemoMode(e.target.checked)}
            disabled={scanMutation.isPending || dataSource === 'live'}
          />
          <span>
            Demo mode (inject 18% NDVI drop in last 14 days)
            {dataSource === 'live' && ' — N/A in live mode'}
          </span>
        </label>
        <button
          type="button"
          className="cg-yield-btn"
          onClick={runConfirmedScan}
          disabled={scanMutation.isPending}
        >
          {scanMutation.isPending ? 'Scanning…' : 'Persist scan to audit log'}
        </button>
      </div>

      {scanError && <div className="fp-alert-error">{scanError}</div>}

      {lastScan?.notice && (
        <div className="fp-alert-notice">{lastScan.notice}</div>
      )}

      {lastScan && (
        <>
          <ScanSummary scan={lastScan} />
          <NdviChart scan={lastScan} />
        </>
      )}

      <div className="cg-section-header cg-ndvi-log-head">
        Recent anomaly audit log
        <span className="ev-map-meta">last {listQuery.data?.anomalies.length ?? 0} scans</span>
      </div>
      {listQuery.isLoading && (
        <div className="fp-alert-empty">Loading audit log…</div>
      )}
      {listQuery.data?.anomalies.length === 0 && (
        <div className="fp-alert-empty">
          No persisted scans yet. Run a scan above and click &ldquo;Persist&rdquo; to log it.
        </div>
      )}
      <div className="cg-ndvi-log">
        {listQuery.data?.anomalies.map((a) => (
          <div key={a.id} className="cg-ndvi-log-row">
            <span className={a.anomaly ? 'cg-ndvi-flag-bad' : 'cg-ndvi-flag-ok'}>
              {a.anomaly ? '⚠' : '✓'}
            </span>
            <span className="cg-ndvi-log-window">
              {fmtDate(a.window_start)} – {fmtDate(a.window_end)}
            </span>
            <span className="cg-ndvi-log-z">z = {a.z_score.toFixed(2)}</span>
            <span className={bandClass(a.confidence_band)}>{a.confidence_band}</span>
            <span className="cg-ndvi-log-dp">
              dp {Math.round(a.disease_probability * 100)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}


function ScanSummary({ scan }: { scan: NdviScanData }) {
  return (
    <div className={`cg-result ${scan.anomaly ? '' : 'cg-result--ok'}`}>
      <div className="cg-result-header">
        <div>
          <div className="cg-result-class">
            {scan.anomaly
              ? '⚠ NDVI anomaly detected'
              : 'No anomaly · vegetation tracking baseline'}
          </div>
          <div className="cg-result-sub">
            z-score {scan.z_score.toFixed(2)} ·{' '}
            <span className={bandClass(scan.confidence_band)}>{scan.confidence_band}</span> ·
            Disease probability {Math.round(scan.disease_probability * 100)}% ·
            Early-warning lead: {scan.days_early_warning} days
            {scan.persisted && ' · saved to audit log'}
          </div>
        </div>
        <div
          className={`cg-result-score ${
            scan.anomaly ? 'cg-result-score--bad' : 'cg-result-score--ok'
          }`}
        >
          {Math.round(scan.disease_probability * 100)}
          <span className="cg-result-score-unit">/100</span>
        </div>
      </div>
      <div className="cg-result-footnote">
        {scan.detector_name} {scan.detector_version} ·
        recent mean {scan.ndvi_recent_mean.toFixed(3)} ·
        baseline mean {scan.ndvi_baseline_mean.toFixed(3)} ·
        baseline σ {scan.ndvi_baseline_std.toFixed(3)}
      </div>
    </div>
  );
}


function NdviChart({ scan }: { scan: NdviScanData }) {
  const w = 720;
  const h = 240;
  const padL = 50, padR = 12, padT = 18, padB = 32;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;

  const series = scan.series;
  // NDVI is in [0, 1]; fix the y-axis to that range for stability.
  const yMin = 0;
  const yMax = 1.0;
  const xStep = series.length > 1 ? plotW / (series.length - 1) : 0;

  const pts = useMemo(
    () => series.map((p, i) => ({
      x: padL + i * xStep,
      y: padT + plotH - ((p.ndvi - yMin) / (yMax - yMin)) * plotH,
    })),
    [series, xStep, plotH, padL, padT],
  );

  const linePath = pts
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`)
    .join(' ');

  // Highlight the recent window (last 14 samples).
  const recentStartIdx = series.length - RECENT_WINDOW_DAYS;
  const recentLineX = padL + recentStartIdx * xStep;

  // Baseline mean line (drawn across the baseline portion, projected to recent centre).
  const baselineMeanY = padT + plotH - (
    (scan.ndvi_baseline_mean - yMin) / (yMax - yMin)
  ) * plotH;
  const recentMeanY = padT + plotH - (
    (scan.ndvi_recent_mean - yMin) / (yMax - yMin)
  ) * plotH;

  const yTicks = [0, 0.25, 0.5, 0.75, 1.0];

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      width="100%"
      height={h}
      role="img"
      aria-label="NDVI time series with anomaly detection"
    >
      {/* Y gridlines */}
      {yTicks.map((v) => {
        const y = padT + plotH - ((v - yMin) / (yMax - yMin)) * plotH;
        return (
          <g key={v}>
            <line
              x1={padL} x2={w - padR} y1={y} y2={y}
              stroke="var(--border)" strokeDasharray="2 4"
            />
            <text
              x={padL - 6} y={y + 3}
              fontSize="10" fill="var(--muted)" textAnchor="end"
            >
              {v.toFixed(2)}
            </text>
          </g>
        );
      })}

      {/* Recent-window shading */}
      <rect
        x={recentLineX}
        y={padT}
        width={(series.length - 1 - recentStartIdx) * xStep}
        height={plotH}
        fill={scan.anomaly ? 'rgba(224, 90, 43, 0.10)' : 'rgba(82, 183, 136, 0.08)'}
      />

      {/* Baseline mean (left side) + recent mean (right side) */}
      <line
        x1={padL} x2={recentLineX}
        y1={baselineMeanY} y2={baselineMeanY}
        stroke="var(--ngo)" strokeWidth="1.5" strokeDasharray="5 3"
      />
      <line
        x1={recentLineX} x2={padL + (series.length - 1) * xStep}
        y1={recentMeanY} y2={recentMeanY}
        stroke={scan.anomaly ? '#e05a2b' : 'var(--ngo)'}
        strokeWidth="1.5" strokeDasharray="5 3"
      />

      {/* Series line */}
      <path
        d={linePath}
        stroke={scan.anomaly ? '#e05a2b' : 'var(--ngo)'}
        strokeWidth="2"
        fill="none"
      />

      {/* X-axis labels — 5 ticks */}
      {[0, Math.floor(series.length * 0.25), Math.floor(series.length * 0.5),
        recentStartIdx, series.length - 1].map((i) => {
        if (i < 0 || i >= series.length) return null;
        const x = padL + i * xStep;
        return (
          <text
            key={i}
            x={x} y={h - padB + 16}
            fontSize="10" fill="var(--muted)" textAnchor="middle"
          >
            {fmtDate(series[i].observed_at)}
          </text>
        );
      })}

      {/* Recent-window label */}
      <text
        x={recentLineX + 4} y={padT + 12}
        fontSize="10" fill="var(--muted)"
        fontWeight="600"
      >
        recent {RECENT_WINDOW_DAYS}d
      </text>
    </svg>
  );
}
