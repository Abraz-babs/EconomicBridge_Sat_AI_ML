'use client';

import { useMemo, useState } from 'react';

import { useAuth } from '@/context/AuthContext';
import { downloadFile, ingestionFetch } from '@/lib/api';
import { parseCoord } from './FarmCheckPanel';

// Insurance claims verification: an insurer's claims list (plot + loss date)
// checked with Sentinel-1 radar and Sentinel-2 before and after each loss date.
// Kept as its own section, apart from Farm Check, at the operator's request
// (9 Oct 2026): a claim check answers a different question (what changed around
// a date) and its output is evidence for a claims team, never a claim decision.
// Super-admin only: the report is a paid deliverable the operator reviews.

type Peril = 'flood' | 'drought' | 'general';
type Conclusion = 'supports' | 'partly_supports' | 'not_supported' | 'inconclusive';

interface PassWater { date: string; water_share: number; plot_seen: number; window: 'before' | 'after' }
interface PassNdvi { date: string; ndvi: number; plot_seen: number; window: 'before' | 'after' }

export interface ClaimCheckResult {
  lat: number;
  lon: number;
  loss_date: string;
  peril: Peril;
  crop: string;
  area_ha: number;
  windows: Record<string, string>;
  thresholds: Record<string, number>;
  ndvi_passes: PassNdvi[];
  water_passes: PassWater[];
  metrics: {
    water_share_before: number | null;
    water_share_after_peak: number | null;
    ndvi_before: number | null;
    ndvi_after_low: number | null;
    ndvi_change: number | null;
  };
  flood_evidence: string;
  vegetation_change: string;
  conclusion: Conclusion;
  summary: string;
  recommendation: string;
  limitations: string[];
  source: string;
}

// Same labels and colours as the PDF report. Never red: red reads as
// "rejected", which this tool never says.
const OUTCOME: Record<Conclusion, { label: string; cls: string }> = {
  supports: { label: 'Consistent with loss', cls: 'cv-out-supports' },
  partly_supports: { label: 'Partly consistent', cls: 'cv-out-partly' },
  not_supported: { label: 'Not seen by satellite', cls: 'cv-out-notseen' },
  inconclusive: { label: 'Inconclusive', cls: 'cv-out-inconclusive' },
};

// Both box sizes were measured against UN-mapped floods (8 Oct 2026).
const BOX_OPTIONS = [
  { label: 'Plot (120 m box, ~1.4 ha)', half: 60 },
  { label: 'Wider (400 m box, ~16 ha)', half: 200 },
];

const MAX_CLAIMS = 200;          // per run: each claim is two live satellite queries
const CONCURRENCY = 2;
const ROW_RETRIES = 1;
const RETRY_DELAY_MS = 1500;
const STAGGER_MS = 150;
const EARLIEST = '2017-01-01';

type RowStatus = 'pending' | 'running' | 'done' | 'error' | 'invalid';

interface ClaimRow {
  idx: number;
  raw: string;
  claimId: string;
  lat: number | null;
  lon: number | null;
  lossDate: string | null;   // ISO yyyy-mm-dd
  peril: Peril;
  insured: string;
  location: string;
  status: RowStatus;
  result?: ClaimCheckResult;
  error?: string;
}

const COLUMN_ALIASES: Record<string, string[]> = {
  claimId: ['claim_id', 'claim', 'claim no', 'claim number', 'claim_no', 'policy', 'id'],
  lat: ['lat', 'latitude'],
  lon: ['lon', 'lng', 'long', 'longitude'],
  lossDate: ['loss_date', 'loss date', 'date', 'event_date', 'date of loss'],
  peril: ['peril', 'cause', 'hazard'],
  insured: ['insured_name', 'insured', 'name', 'farmer', 'farmer_name'],
  location: ['lga', 'location', 'village', 'community'],
};
const POSITIONAL = ['claimId', 'lat', 'lon', 'lossDate', 'peril', 'insured', 'location'];

/** yyyy-mm-dd, yyyy/mm/dd or dd/mm/yyyy (the Nigerian order) → ISO date. */
export function parseLossDate(text: string): string | null {
  const t = text.trim();
  let y: number, m: number, d: number;
  let match = /^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$/.exec(t);
  if (match) {
    [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])];
  } else {
    match = /^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$/.exec(t);
    if (!match) return null;
    [d, m, y] = [Number(match[1]), Number(match[2]), Number(match[3])];
  }
  const dt = new Date(Date.UTC(y, m - 1, d));
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) return null;
  return dt.toISOString().slice(0, 10);
}

function normalisePeril(text: string): Peril {
  const p = text.trim().toLowerCase();
  if (p.startsWith('drought') || p === 'dry spell') return 'drought';
  if (p === '' || p.startsWith('flood') || p === 'inundation') return 'flood';
  return 'general';
}

function splitLine(line: string): string[] {
  return line.split(/\s*,\s*|\t/).map((s) => s.trim());
}

/** Parse a pasted or uploaded claims list. A header row maps columns by name;
 *  without one the order is claim_id, lat, lon, loss_date, peril, insured_name, lga. */
export function parseClaims(text: string, today: string): ClaimRow[] {
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (lines.length === 0) return [];
  let order = POSITIONAL;
  const first = splitLine(lines[0]).map((h) => h.toLowerCase());
  const looksLikeHeader = first.some((h) => COLUMN_ALIASES.lat.includes(h))
    && first.some((h) => COLUMN_ALIASES.lon.includes(h));
  if (looksLikeHeader) {
    order = first.map((h) => Object.keys(COLUMN_ALIASES).find((k) => COLUMN_ALIASES[k].includes(h)) ?? '');
    lines.shift();
  }
  return lines.map((line, idx) => {
    const parts = splitLine(line);
    const get = (key: string) => {
      const i = order.indexOf(key);
      return i >= 0 ? (parts[i] ?? '') : '';
    };
    const lat = parseCoord(get('lat'));
    const lon = parseCoord(get('lon'));
    const lossDate = parseLossDate(get('lossDate'));
    let error: string | undefined;
    if (lat == null || lon == null || Math.abs(lat) > 90 || Math.abs(lon) > 180) error = 'Could not read the coordinates';
    else if (!lossDate) error = 'Could not read the loss date (use 2024-09-07 or 07/09/2024)';
    else if (lossDate > today) error = 'Loss date is in the future';
    else if (lossDate < EARLIEST) error = `Loss dates before ${EARLIEST} are not supported`;
    else if (idx >= MAX_CLAIMS) error = `Over the ${MAX_CLAIMS}-claim limit for one run`;
    return {
      idx,
      raw: line,
      claimId: get('claimId') || `ROW-${idx + 1}`,
      lat: error ? null : lat,
      lon: error ? null : lon,
      lossDate: error ? null : lossDate,
      peril: normalisePeril(get('peril')),
      insured: get('insured'),
      location: get('location'),
      status: error ? 'invalid' : 'pending',
      error,
    } satisfies ClaimRow;
  });
}

const pct = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v * 100)}%`);
const ndvi = (v: number | null | undefined) => (v == null ? '—' : v.toFixed(2));

export default function ClaimsVerificationPanel() {
  const { isSuperAdmin } = useAuth();
  const [text, setText] = useState('');
  const [rows, setRows] = useState<ClaimRow[]>([]);
  const [halfM, setHalfM] = useState(60);
  const [running, setRunning] = useState(false);
  const [client, setClient] = useState('');
  const [batchRef, setBatchRef] = useState('');
  const [reportBusy, setReportBusy] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  const patchRow = (idx: number, patch: Partial<ClaimRow>) =>
    setRows((prev) => prev.map((r) => (r.idx === idx ? { ...r, ...patch } : r)));

  const stats = useMemo(() => {
    const done = rows.filter((r) => r.status === 'done');
    const count = (c: Conclusion) => done.filter((r) => r.result?.conclusion === c).length;
    return {
      valid: rows.filter((r) => r.status !== 'invalid').length,
      invalid: rows.filter((r) => r.status === 'invalid').length,
      done: done.length,
      errored: rows.filter((r) => r.status === 'error').length,
      supports: count('supports'),
      partly: count('partly_supports'),
      notSeen: count('not_supported'),
      inconclusive: count('inconclusive'),
    };
  }, [rows]);

  const checkRow = async (row: ClaimRow, attempt = 0): Promise<void> => {
    patchRow(row.idx, { status: 'running', error: undefined });
    try {
      const res = await ingestionFetch<ClaimCheckResult>('/cropguard/claim-check', {
        method: 'POST',
        body: { lat: row.lat, lon: row.lon, loss_date: row.lossDate, peril: row.peril, half_m: halfM },
      });
      patchRow(row.idx, { status: 'done', result: res });
    } catch (err) {
      if (attempt < ROW_RETRIES) {
        await new Promise((r) => setTimeout(r, RETRY_DELAY_MS));
        return checkRow(row, attempt + 1);
      }
      patchRow(row.idx, { status: 'error', error: err instanceof Error ? err.message : 'Check failed' });
    }
  };

  const runQueue = async (queue: ClaimRow[]) => {
    let cursor = 0;
    const worker = async () => {
      while (cursor < queue.length) {
        const row = queue[cursor++];
        await checkRow(row);
        await new Promise((r) => setTimeout(r, STAGGER_MS));
      }
    };
    try {
      await Promise.all(Array.from({ length: Math.min(CONCURRENCY, queue.length) }, worker));
    } finally {
      setRunning(false);
    }
  };

  const run = async () => {
    const parsed = parseClaims(text, new Date().toISOString().slice(0, 10));
    setRows(parsed);
    setReportError(null);
    const queue = parsed.filter((r) => r.status === 'pending');
    if (queue.length === 0) return;
    setRunning(true);
    await runQueue(queue);
  };

  const retryFailed = async () => {
    const failed = rows.filter((r) => r.status === 'error');
    if (failed.length === 0) return;
    setRunning(true);
    await runQueue(failed);
  };

  const loadFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) setText(await f.text());
  };

  const downloadReport = async () => {
    setReportBusy(true);
    setReportError(null);
    try {
      const ref = batchRef.trim() || `BATCH-${new Date().toISOString().slice(0, 10)}`;
      await downloadFile('/claims/report', `claims_report_${ref.replace(/[^\w-]/g, '_')}.pdf`, {
        method: 'POST',
        body: {
          client_name: client.trim() || 'Not stated',
          batch_ref: ref,
          claims: rows.filter((r) => r.status === 'done' && r.result).map((r) => ({
            claim_id: r.claimId.slice(0, 60),
            insured_name: r.insured.trim() ? r.insured.trim().slice(0, 120) : undefined,
            location_note: r.location.trim() ? r.location.trim().slice(0, 120) : undefined,
            result: r.result,
          })),
        },
      });
    } catch (err) {
      setReportError(err instanceof Error ? err.message : 'The report could not be generated');
    } finally {
      setReportBusy(false);
    }
  };

  const downloadCsv = () => {
    const esc = (v: unknown) => {
      const s = v == null ? '' : String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const header = ['claim_id', 'insured_name', 'location', 'latitude', 'longitude', 'loss_date', 'peril',
      'outcome', 'radar_water_before', 'radar_water_peak_after', 'ndvi_before', 'ndvi_after',
      'summary', 'recommendation', 'status'];
    const lines = [header.join(',')];
    for (const r of rows) {
      const res = r.result;
      lines.push([
        r.claimId, r.insured, r.location, r.lat ?? '', r.lon ?? '', r.lossDate ?? '', r.peril,
        res ? OUTCOME[res.conclusion].label : '',
        res?.metrics.water_share_before ?? '', res?.metrics.water_share_after_peak ?? '',
        res?.metrics.ndvi_before ?? '', res?.metrics.ndvi_after_low ?? '',
        res?.summary ?? '', res?.recommendation ?? '', r.error ?? r.status,
      ].map(esc).join(','));
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `claims_check_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div className="sb-table-wrap" style={{ marginTop: '16px' }}>
      <div className="cg-section-header">Insurance claims verification</div>
      <div className="cg-subtitle" style={{ marginBottom: '10px' }}>
        Check insured plots before and after each reported loss date with Sentinel-1 radar (sees through cloud)
        and Sentinel-2 vegetation. Results are evidence for the claims team, never a claim decision: anything the
        satellites do not show is marked for a field visit. Paste or upload the claims list with a header row:
        {' '}<code>claim_id, lat, lon, loss_date, peril, insured_name, lga</code>. Peril is flood, drought or
        general. Up to {MAX_CLAIMS} claims per run, about 15 seconds each.
      </div>

      <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'flex-end', margin: '4px 0 10px' }}>
        <label style={{ fontSize: '11px' }}>
          <div className="fp-tenant-label">Area checked</div>
          <select className="fp-tenant-select" value={halfM} onChange={(e) => setHalfM(Number(e.target.value))}
            disabled={running}>
            {BOX_OPTIONS.map((o) => <option key={o.half} value={o.half}>{o.label}</option>)}
          </select>
        </label>
        <label style={{ fontSize: '11px' }}>
          <div className="fp-tenant-label">Upload CSV / TXT</div>
          <input type="file" accept=".csv,.txt" onChange={loadFile} style={{ fontSize: '11px', maxWidth: '190px' }} />
        </label>
      </div>

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={'claim_id, lat, lon, loss_date, peril, insured_name, lga\nNAIC-0001, 11.3000, 4.2167, 2024-09-07, flood, Musa Ibrahim, Bagudo'}
        rows={6}
        style={{
          width: '100%', background: 'var(--surface)', border: '1px solid var(--border2)',
          borderRadius: '4px', color: 'var(--ink)', padding: '8px 10px',
          fontSize: '11px', fontFamily: "'DM Mono', monospace", resize: 'vertical',
        }}
      />

      <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap', margin: '10px 0' }}>
        <button type="button" className="fp-refresh-btn" onClick={run} disabled={running || !text.trim()}>
          {running ? `Checking… ${stats.done + stats.errored}/${stats.valid}` : 'Check claims'}
        </button>
        {stats.errored > 0 && !running && (
          <button type="button" className="fp-refresh-btn" onClick={retryFailed}>
            ↻ Retry {stats.errored} failed
          </button>
        )}
        {stats.invalid > 0 && !running && (
          <span className="ev-map-meta">{stats.invalid} line{stats.invalid > 1 ? 's' : ''} could not be read</span>
        )}
      </div>

      {stats.done > 0 && (
        <div className="cv-summary">
          <span><span className="fp-sev cv-out-supports">Consistent</span> <b>{stats.supports}</b></span>
          <span><span className="fp-sev cv-out-partly">Partly</span> <b>{stats.partly}</b></span>
          <span><span className="fp-sev cv-out-notseen">Not seen</span> <b>{stats.notSeen}</b></span>
          <span><span className="fp-sev cv-out-inconclusive">Inconclusive</span> <b>{stats.inconclusive}</b></span>
          <span>Field visits recommended <b>{stats.partly + stats.notSeen + stats.inconclusive}</b></span>
        </div>
      )}

      {rows.length > 0 && (
        <div className="ev-lga-table-wrap">
          <table className="ev-lga-table">
            <thead>
              <tr>
                <th>Claim</th>
                <th>Plot</th>
                <th>Loss date</th>
                <th>Peril</th>
                <th className="cv-left">Outcome</th>
                <th>Radar water before → peak</th>
                <th>Vegetation before → after</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const res = r.result;
                return (
                  <tr key={r.idx}>
                    <td>
                      {r.claimId}
                      {(r.insured || r.location) && (
                        <div className="cv-detail">{[r.insured, r.location].filter(Boolean).join(' · ')}</div>
                      )}
                    </td>
                    <td>{r.lat != null && r.lon != null ? `${r.lat.toFixed(4)}, ${r.lon.toFixed(4)}` : '—'}</td>
                    <td>{r.lossDate ?? '—'}</td>
                    <td>{r.peril}</td>
                    <td className="cv-left">
                      {res ? (
                        <>
                          <span className={`fp-sev ${OUTCOME[res.conclusion].cls}`}>{OUTCOME[res.conclusion].label}</span>
                          <div className="cv-detail">{res.summary}</div>
                        </>
                      ) : (
                        <span className="ev-map-meta" title={r.error}>
                          {r.status === 'running' && 'checking…'}
                          {r.status === 'pending' && 'queued'}
                          {r.status === 'invalid' && (r.error ?? 'unreadable')}
                          {r.status === 'error' && `failed — ${r.error ?? ''}`}
                        </span>
                      )}
                    </td>
                    <td>{res ? `${pct(res.metrics.water_share_before)} → ${pct(res.metrics.water_share_after_peak)}` : '—'}</td>
                    <td>{res ? `${ndvi(res.metrics.ndvi_before)} → ${ndvi(res.metrics.ndvi_after_low)}` : '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Downloads are paid deliverables: super-admin only, even for insurer accounts. */}
      {isSuperAdmin && stats.done > 0 && !running && (
        <div className="cv-report">
          <label style={{ fontSize: '11px' }}>
            <div className="fp-tenant-label">Prepared for</div>
            <input className="cv-input" value={client} onChange={(e) => setClient(e.target.value)}
              placeholder="e.g. NAIC" maxLength={120} />
          </label>
          <label style={{ fontSize: '11px' }}>
            <div className="fp-tenant-label">Batch reference</div>
            <input className="cv-input" value={batchRef} onChange={(e) => setBatchRef(e.target.value)}
              placeholder="e.g. NAIC-KEBBI-2026-01" maxLength={60} />
          </label>
          <button type="button" className="fp-refresh-btn" onClick={downloadReport} disabled={reportBusy}>
            {reportBusy ? 'Preparing report…' : `⬇ Claims report (PDF, ${stats.done} claims)`}
          </button>
          <button type="button" className="fp-refresh-btn" onClick={downloadCsv}>⬇ Results (CSV)</button>
          {reportError && <span className="ev-map-meta" style={{ color: 'var(--alert)' }}>{reportError}</span>}
        </div>
      )}
    </div>
  );
}
