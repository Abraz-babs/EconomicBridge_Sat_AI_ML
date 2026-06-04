'use client';

import { useMemo, useState } from 'react';

import { useReportSummary, downloadReportCsv } from '@/hooks/useReports';

/** Today / N-days-ago as ISO YYYY-MM-DD. */
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
 * Historical report + CSV export for the active tenant's alert/encroachment
 * history. Access-controlled server-side (a viewer can only export tenants they
 * may see). Pick a period, see the summary, download the rows as CSV (Excel).
 */
export default function ReportsCard({ tenantId, tenantName }: { tenantId: string; tenantName: string }) {
  const [preset, setPreset] = useState<Preset>('quarter');
  const [from, setFrom] = useState(isoDaysAgo(90));
  const [to, setTo] = useState(TODAY());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const { data, isLoading, isError, error } = useReportSummary(tenantId, from, to);

  function applyPreset(p: Preset, days: number) {
    setPreset(p);
    setFrom(isoDaysAgo(days));
    setTo(TODAY());
  }

  async function download() {
    setBusy(true);
    setErr(null);
    try {
      await downloadReportCsv(tenantId, from, to);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Download failed.');
    } finally {
      setBusy(false);
    }
  }

  const sevRows = useMemo(() => Object.entries(data?.by_severity ?? {}), [data]);
  const statusRows = useMemo(() => Object.entries(data?.by_status ?? {}), [data]);

  return (
    <div className="panel rep-card">
      <div className="panel-header">
        <span className="panel-title">Reports &amp; Export — {tenantName}</span>
        <span className="panel-meta">alert history · CSV</span>
      </div>
      <div className="upload-body">
        <div className="rep-controls">
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
          <button type="button" className="sms-btn sms-btn--go rep-download"
            disabled={busy || isLoading || (data?.total_alerts ?? 0) === 0}
            onClick={download}>
            {busy ? 'Preparing…' : 'Download CSV'}
          </button>
        </div>

        {isLoading && <div className="fp-alert-empty">Loading report…</div>}
        {isError && (
          <div className="fp-alert-error">
            Could not load report: {error?.message ?? 'unknown error'}
          </div>
        )}
        {err && <div className="fp-alert-error">{err}</div>}

        {data && !isLoading && (
          <>
            <div className="rep-stats">
              <div className="rep-stat"><div className="rep-stat-v">{data.total_alerts}</div><div className="rep-stat-k">Total alerts</div></div>
              <div className="rep-stat"><div className="rep-stat-v">{data.resolved}</div><div className="rep-stat-k">Resolved</div></div>
              <div className="rep-stat"><div className="rep-stat-v">{data.livelihoods_at_risk.toLocaleString()}</div><div className="rep-stat-k">Livelihoods at risk</div></div>
              <div className="rep-stat"><div className="rep-stat-v">{Math.round(data.affected_area_ha).toLocaleString()}</div><div className="rep-stat-k">Hectares affected</div></div>
              <div className="rep-stat"><div className="rep-stat-v">{data.live_alerts}/{data.total_alerts}</div><div className="rep-stat-k">Live (vs seed)</div></div>
            </div>
            {data.total_alerts === 0 ? (
              <div className="fp-alert-empty">No alerts in this period for {tenantName}.</div>
            ) : (
              <div className="rep-breakdown">
                <div>
                  <div className="rep-bd-title">By severity</div>
                  {sevRows.map(([k, v]) => <div key={k} className="rep-bd-row"><span>{k}</span><span>{v}</span></div>)}
                </div>
                <div>
                  <div className="rep-bd-title">By status</div>
                  {statusRows.map(([k, v]) => <div key={k} className="rep-bd-row"><span>{k.replace('_', ' ')}</span><span>{v}</span></div>)}
                </div>
              </div>
            )}
            <p className="rep-note">
              {data.date_from} → {data.date_to}. CSV contains one row per alert
              (date, type, severity, status, LGA, confidence, area, livelihoods,
              value, source, model). Exports are scoped to tenants you’re permitted
              to view.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
