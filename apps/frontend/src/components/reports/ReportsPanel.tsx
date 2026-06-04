'use client';

import { useState } from 'react';

import { useTenant } from '@/context/TenantContext';
import {
  useReportModules,
  useReportSummary,
  downloadReportCsv,
  downloadReportPdf,
} from '@/hooks/useReports';

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}
const TODAY = () => new Date().toISOString().slice(0, 10);

type Preset = 'month' | 'quarter' | 'year' | 'custom';
const PRESETS: { id: Preset; label: string; days: number }[] = [
  { id: 'month', label: 'Last month', days: 30 },
  { id: 'quarter', label: 'Last quarter', days: 90 },
  { id: 'year', label: 'Last year', days: 365 },
];

/**
 * Reports & Export — historical summary + CSV/PDF download for any module, for
 * the active tenant. Access-controlled server-side: a viewer can only report on
 * tenants they're permitted to see.
 */
export default function ReportsPanel() {
  const { activeTenantId, activeTenant } = useTenant();
  const { data: modules } = useReportModules();
  const [module, setModule] = useState('farmland');
  const [preset, setPreset] = useState<Preset>('quarter');
  const [from, setFrom] = useState(isoDaysAgo(90));
  const [to, setTo] = useState(TODAY());
  const [busy, setBusy] = useState<'csv' | 'pdf' | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const { data, isLoading, isError, error } = useReportSummary(activeTenantId, module, from, to);

  function applyPreset(p: Preset, days: number) {
    setPreset(p);
    setFrom(isoDaysAgo(days));
    setTo(TODAY());
  }

  async function dl(kind: 'csv' | 'pdf') {
    setBusy(kind);
    setErr(null);
    try {
      const fn = kind === 'csv' ? downloadReportCsv : downloadReportPdf;
      await fn(activeTenantId, module, from, to);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Download failed.');
    } finally {
      setBusy(null);
    }
  }

  const empty = (data?.total_rows ?? 0) === 0;

  return (
    <div className="panel rep-card">
      <div className="panel-header">
        <span className="panel-title">Reports &amp; Export — {activeTenant.name}</span>
        <span className="panel-meta">historical summary · CSV / PDF</span>
      </div>
      <div className="upload-body">
        <div className="rep-controls">
          <label className="rep-date">Module
            <select value={module} onChange={(e) => setModule(e.target.value)}>
              {(modules ?? [{ key: 'farmland', label: 'Farmland Protection' }]).map((m) => (
                <option key={m.key} value={m.key}>{m.label}</option>
              ))}
            </select>
          </label>
          <div className="rep-presets" role="group" aria-label="Report period">
            {PRESETS.map((p) => (
              <button key={p.id} type="button"
                className={`rep-preset ${preset === p.id ? 'is-active' : ''}`}
                onClick={() => applyPreset(p.id, p.days)}>
                {p.label}
              </button>
            ))}
          </div>
          <label className="rep-date">From
            <input type="date" value={from} max={to}
              onChange={(e) => { setFrom(e.target.value); setPreset('custom'); }} />
          </label>
          <label className="rep-date">To
            <input type="date" value={to} min={from} max={TODAY()}
              onChange={(e) => { setTo(e.target.value); setPreset('custom'); }} />
          </label>
          <div className="rep-dl-group">
            <button type="button" className="sms-btn sms-btn--go"
              title="Formatted report with charts (trend + breakdown)"
              disabled={busy !== null || isLoading || empty} onClick={() => dl('pdf')}>
              {busy === 'pdf' ? 'Preparing…' : '📊 PDF report (charts)'}
            </button>
            <button type="button" className="sms-btn"
              title="Raw data rows — opens in Excel / Google Sheets"
              disabled={busy !== null || isLoading || empty} onClick={() => dl('csv')}>
              {busy === 'csv' ? 'Preparing…' : '⤓ CSV data (Excel)'}
            </button>
          </div>
        </div>

        {isLoading && <div className="fp-alert-empty">Loading report…</div>}
        {isError && <div className="fp-alert-error">Could not load report: {error?.message ?? 'unknown error'}</div>}
        {err && <div className="fp-alert-error">{err}</div>}

        {data && !isLoading && (
          <>
            <div className="rep-stats">
              {data.metrics.map((m) => (
                <div key={m.label} className="rep-stat">
                  <div className="rep-stat-v">{m.display}</div>
                  <div className="rep-stat-k">{m.label}</div>
                </div>
              ))}
            </div>
            {empty ? (
              <div className="fp-alert-empty">No {data.label} records in this period for {activeTenant.name}.</div>
            ) : data.breakdown && data.breakdown.rows.length > 0 ? (
              <div className="rep-breakdown">
                <div>
                  <div className="rep-bd-title">{data.breakdown.title}</div>
                  {data.breakdown.rows.map((r) => (
                    <div key={r.key} className="rep-bd-row"><span>{r.key.replace(/_/g, ' ')}</span><span>{r.count}</span></div>
                  ))}
                </div>
              </div>
            ) : null}
            <p className="rep-note">
              {data.label} · {data.date_from} → {data.date_to} · {data.total_rows.toLocaleString()} records.
              <strong> PDF</strong> = formatted report with trend &amp; breakdown charts;
              <strong> CSV</strong> = one row per record (opens in Excel / Sheets). Exports
              are scoped to tenants you’re permitted to view.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
