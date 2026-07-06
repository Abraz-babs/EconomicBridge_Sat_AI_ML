'use client';

import { useMemo, useState } from 'react';

import { apiFetch, ingestionFetch } from '@/lib/api';
import { useTenant } from '@/context/TenantContext';
import { type FarmCheckResult, type FarmHealth } from '@/hooks/useFarmCheck';
import { fetchPlaceName, parseCoord, pilotMismatch } from './FarmCheckPanel';

// Bulk Farm Check: paste or upload a list of coordinates (e.g. a NASRDA
// location list) and check them all at once. Drives the SAME per-farm endpoint
// as the single check — this is purely a batch driver, no new backend.

const PRECISION_OPTIONS = [
  { label: 'Tight (~1.4 ha)', half: 60 },
  { label: 'Standard (~5.8 ha)', half: 120 },
];

const HEALTH_STYLE: Record<FarmHealth, { label: string; color: string }> = {
  healthy: { label: 'Healthy', color: '#22c55e' },
  moderate: { label: 'Moderate', color: '#84cc16' },
  stressed: { label: 'Stressed', color: '#eab308' },
  poor: { label: 'Poor', color: '#ef4444' },
  bare: { label: 'Bare soil', color: '#9ca3af' },
  unknown: { label: 'No reading', color: '#9ca3af' },
};

// How many farm checks to run at once. Small pool: each check is a live CDSE
// query, and the ingestion client backs off on 429 — 2 in flight is gentle and
// reliable. Each row also retries once on a transient network/rate blip.
const CONCURRENCY = 2;
const ROW_RETRIES = 1;
const RETRY_DELAY_MS = 1500;
const STAGGER_MS = 120;

type RowStatus = 'pending' | 'running' | 'done' | 'error' | 'invalid';

interface BulkRow {
  idx: number;
  raw: string;
  lat: number | null;
  lon: number | null;
  crop: string;
  owner: string;
  lga: string;
  status: RowStatus;
  result?: FarmCheckResult;
  error?: string;
  saved?: boolean;
  place?: string | null;     // reverse-geocoded place for the checked point
  mismatch?: boolean;        // place is outside the selected pilot's state
}

/** Parse pasted/loaded text into rows.
 *  One location per line: `lat, lon[, crop, owner, lga]`. Comma OR tab
 *  separated; a bare "lat lon" (whitespace) also works. A header row that
 *  mentions lat/lon is skipped. Coordinates accept decimal or DMS (parseCoord). */
function parseBulk(text: string): BulkRow[] {
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const rows: BulkRow[] = [];
  let idx = 0;
  for (const line of lines) {
    // Skip an obvious header row.
    if (/lat/i.test(line) && /lon|lng/i.test(line) && !/\d/.test(line.replace(/lat|lon|lng/gi, ''))) {
      continue;
    }
    let parts = line.split(/\s*,\s*|\t/).map((s) => s.trim());
    if (parts.length < 2) parts = line.split(/\s+/);
    const lat = parseCoord(parts[0] ?? '');
    const lon = parseCoord(parts[1] ?? '');
    const valid =
      lat != null && lon != null &&
      lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180;
    rows.push({
      idx: idx++,
      raw: line,
      lat: valid ? lat : null,
      lon: valid ? lon : null,
      crop: parts[2] ?? '',
      owner: parts[3] ?? '',
      lga: parts[4] ?? '',
      status: valid ? 'pending' : 'invalid',
      error: valid ? undefined : 'Could not read a coordinate on this line',
    });
  }
  return rows;
}

export default function FarmCheckBulkPanel() {
  const { activeTenant, pilotTenants } = useTenant();
  const [pilotId, setPilotId] = useState(activeTenant.id);
  const [halfM, setHalfM] = useState(60);
  const [text, setText] = useState('');
  const [rows, setRows] = useState<BulkRow[]>([]);
  const [running, setRunning] = useState(false);
  const [savingAll, setSavingAll] = useState(false);

  const pilot = pilotTenants.find((t) => t.id === pilotId) ?? activeTenant;

  const patchRow = (idx: number, patch: Partial<BulkRow>) =>
    setRows((prev) => prev.map((r) => (r.idx === idx ? { ...r, ...patch } : r)));

  const stats = useMemo(() => {
    const valid = rows.filter((r) => r.status !== 'invalid');
    const done = rows.filter((r) => r.status === 'done').length;
    const errored = rows.filter((r) => r.status === 'error').length;
    const savable = rows.filter((r) => r.status === 'done' && !r.saved).length;
    return { total: valid.length, invalid: rows.length - valid.length, done, errored, savable };
  }, [rows]);

  const loadFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setText(await f.text());
  };

  // Check one row, retrying once on a transient failure (network blip / 429).
  const checkRow = async (row: BulkRow, attempt = 0): Promise<void> => {
    patchRow(row.idx, { status: 'running', error: undefined });
    try {
      const res = await ingestionFetch<FarmCheckResult>('/cropguard/farm-check', {
        method: 'POST',
        body: {
          lat: row.lat, lon: row.lon,
          crop: row.crop.trim() || 'general', // blank → satellite grades vigour itself
          half_m: halfM,
        },
      });
      // Reverse-geocode to catch mistyped coordinates that land in the wrong
      // state (best-effort; a geocode failure never fails the row).
      let place: string | null = null;
      try { place = await fetchPlaceName(res.lon, res.lat); } catch { /* best-effort */ }
      patchRow(row.idx, {
        status: 'done', result: res, place,
        mismatch: pilotMismatch(place, pilot.name), error: undefined,
      });
    } catch (err) {
      if (attempt < ROW_RETRIES) {
        await new Promise((r) => setTimeout(r, RETRY_DELAY_MS));
        return checkRow(row, attempt + 1);
      }
      patchRow(row.idx, {
        status: 'error',
        error: err instanceof Error ? err.message : 'Check failed',
      });
    }
  };

  // Drain a queue of rows through a small concurrency pool. try/finally
  // guarantees the "running" flag is released even if something throws, so the
  // Save / Download / Clear controls can never get stuck hidden.
  const runQueue = async (queue: BulkRow[]) => {
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

  const runBulk = async () => {
    const parsed = parseBulk(text);
    setRows(parsed);
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

  const clearAll = () => {
    setRows([]);
    setText('');
  };

  const downloadCsv = () => {
    const esc = (v: unknown) => {
      const s = v == null ? '' : String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const header = [
      'latitude', 'longitude', 'owner', 'crop', 'lga', 'place',
      'health', 'ndvi', 'ndvi_date', 'sar_db', 'stress_level',
      'area_ha', 'status', 'note',
    ];
    const lines = [header.join(',')];
    for (const row of rows) {
      const r = row.result;
      lines.push([
        row.lat ?? row.raw, row.lon ?? '',
        row.owner, row.crop.trim() || 'general', row.lga,
        row.place ?? '',
        r?.health ?? '', r?.ndvi ?? '', r?.ndvi_date ?? '',
        r?.sar_db ?? '', r?.stress?.level ?? '',
        r?.area_ha ?? '',
        row.status === 'done'
          ? (row.mismatch ? 'done (outside selected state!)' : 'done')
          : row.status,
        row.error ?? '',
      ].map(esc).join(','));
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `farm_checks_${pilot.id}_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const saveAll = async () => {
    setSavingAll(true);
    for (const row of rows) {
      if (row.status !== 'done' || !row.result || row.saved) continue;
      try {
        await apiFetch('/cropguard/farm-checks', {
          method: 'POST',
          tenantId: pilotId,
          body: {
            ...row.result,
            lga: row.lga.trim() || undefined,
            owner_name: row.owner.trim() || undefined,
          },
        });
        patchRow(row.idx, { saved: true });
      } catch {
        // Leave unsaved; the operator can retry Save all.
      }
    }
    setSavingAll(false);
  };

  return (
    <div className="sb-table-wrap" style={{ marginTop: '16px' }}>
      <div className="cg-section-header">Bulk Farm Check — check many locations at once</div>
      <div className="cg-subtitle" style={{ marginBottom: '10px' }}>
        Paste or upload a list of coordinates (e.g. a NASRDA location list) and run them
        together. One location per line: <code>lat, lon</code> — optionally followed by
        <code> crop, owner, LGA</code>. Leave the crop blank for a general (crop-agnostic)
        reading. Decimal or DMS coordinates both work.
      </div>

      <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'flex-end', margin: '4px 0 10px' }}>
        <label style={{ fontSize: '12px' }}>
          <div className="fp-tenant-label">Save to pilot</div>
          <select className="fp-tenant-select" value={pilotId} onChange={(e) => setPilotId(e.target.value)}>
            {pilotTenants.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        </label>
        <label style={{ fontSize: '12px' }}>
          <div className="fp-tenant-label">Precision</div>
          <select className="fp-tenant-select" value={halfM} onChange={(e) => setHalfM(Number(e.target.value))}>
            {PRECISION_OPTIONS.map((o) => (
              <option key={o.half} value={o.half}>{o.label}</option>
            ))}
          </select>
        </label>
        <label style={{ fontSize: '12px' }}>
          <div className="fp-tenant-label">Upload CSV / TXT</div>
          <input type="file" accept=".csv,.txt" onChange={loadFile} style={{ fontSize: '11px', maxWidth: '190px' }} />
        </label>
      </div>

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={'9.0765, 7.3986, maize, Musa Ibrahim, Bwari\n9.10, 7.42\n9°15\'41.6"N, 7°21\'21.4"E, , Aisha Bello'}
        rows={6}
        style={{
          width: '100%', background: 'var(--surface)', border: '1px solid var(--border2)',
          borderRadius: '4px', color: 'var(--ink)', padding: '8px 10px',
          fontSize: '12px', fontFamily: "'DM Mono', monospace", resize: 'vertical',
        }}
      />

      <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap', margin: '10px 0' }}>
        <button type="button" className="fp-refresh-btn" onClick={runBulk} disabled={running || !text.trim()}>
          {running ? `Checking… ${stats.done + stats.errored}/${stats.total}` : 'Run bulk check'}
        </button>
        {stats.total > 0 && !running && (
          <span className="ev-map-meta">
            {stats.done} done{stats.errored ? ` · ${stats.errored} failed` : ''}
            {stats.invalid ? ` · ${stats.invalid} unreadable line${stats.invalid > 1 ? 's' : ''}` : ''}
          </span>
        )}
        {stats.savable > 0 && !running && (
          <button type="button" className="fp-refresh-btn" onClick={saveAll} disabled={savingAll}>
            {savingAll ? 'Saving…' : `Save all ${stats.savable} to ${pilot.name}`}
          </button>
        )}
        {stats.errored > 0 && !running && (
          <button type="button" className="fp-refresh-btn" onClick={retryFailed}>
            ↻ Retry {stats.errored} failed
          </button>
        )}
        {(stats.done + stats.errored) > 0 && !running && (
          <button type="button" className="fp-refresh-btn" onClick={downloadCsv}>
            ⬇ Download results (CSV)
          </button>
        )}
        {rows.length > 0 && !running && (
          <button
            type="button"
            onClick={clearAll}
            style={{
              background: 'transparent', border: '1px solid var(--border2)',
              borderRadius: '4px', color: 'var(--muted)', cursor: 'pointer',
              fontSize: '12px', padding: '5px 12px',
            }}
          >
            Clear
          </button>
        )}
      </div>

      {!running && rows.some((r) => r.mismatch) && (
        <div style={{
          margin: '0 0 10px', padding: '7px 10px', borderRadius: '6px',
          background: '#ef44441f', border: '1px solid #ef444466', fontSize: '12.5px',
        }}>
          <strong style={{ color: '#ef4444' }}>
            ⚠ {rows.filter((r) => r.mismatch).length} location(s) fall outside {pilot.name}
          </strong>
          <span className="ev-map-meta"> — flagged ⚠ below; check those coordinates (a swapped
          or mistyped digit lands in the wrong state) before saving.</span>
        </div>
      )}

      {rows.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
            <thead>
              <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                <th style={{ padding: '4px 6px' }}>#</th>
                <th style={{ padding: '4px 6px' }}>Coordinate</th>
                <th style={{ padding: '4px 6px' }}>Owner</th>
                <th style={{ padding: '4px 6px' }}>Crop</th>
                <th style={{ padding: '4px 6px' }}>LGA</th>
                <th style={{ padding: '4px 6px' }}>Health</th>
                <th style={{ padding: '4px 6px' }}>NDVI</th>
                <th style={{ padding: '4px 6px' }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const hs = row.result ? HEALTH_STYLE[row.result.health] : null;
                return (
                  <tr key={row.idx} style={{ borderTop: '1px solid var(--border2)' }}>
                    <td style={{ padding: '5px 6px', color: 'var(--muted)' }}>{row.idx + 1}</td>
                    <td style={{ padding: '5px 6px', fontFamily: "'DM Mono', monospace" }}>
                      {row.lat != null && row.lon != null
                        ? `${row.lat.toFixed(4)}, ${row.lon.toFixed(4)}`
                        : <span style={{ color: '#b45309' }}>{row.raw.slice(0, 24)}</span>}
                      {row.mismatch && (
                        <span
                          style={{ color: '#ef4444', marginLeft: '6px', fontWeight: 700 }}
                          title={`Reverse-geocodes to “${row.place ?? 'another state'}” — outside ${pilot.name}`}
                        >
                          ⚠ {row.place ? row.place.split(',').slice(-2, -1)[0]?.trim() : 'outside state'}
                        </span>
                      )}
                    </td>
                    <td style={{ padding: '5px 6px' }}>{row.owner || '—'}</td>
                    <td style={{ padding: '5px 6px' }}>{row.crop.trim() ? row.crop : 'general'}</td>
                    <td style={{ padding: '5px 6px' }}>{row.lga || '—'}</td>
                    <td style={{ padding: '5px 6px' }}>
                      {hs ? (
                        <span style={{
                          background: hs.color, color: '#10130f', fontWeight: 700,
                          fontSize: '11px', padding: '2px 8px', borderRadius: '10px',
                        }}>{hs.label}</span>
                      ) : '—'}
                    </td>
                    <td style={{ padding: '5px 6px' }}>
                      {row.result?.ndvi != null ? row.result.ndvi.toFixed(2) : '—'}
                    </td>
                    <td style={{ padding: '5px 6px' }}>
                      {row.status === 'running' && <span className="ev-map-meta">checking…</span>}
                      {row.status === 'pending' && <span className="ev-map-meta">queued</span>}
                      {row.status === 'invalid' && <span style={{ color: '#b45309' }}>unreadable</span>}
                      {row.status === 'error' && (
                        <span style={{ color: '#ef4444' }} title={row.error}>
                          failed{row.error ? ` — ${row.error.length > 44 ? `${row.error.slice(0, 44)}…` : row.error}` : ''}
                        </span>
                      )}
                      {row.status === 'done' && (
                        <span style={{ color: row.saved ? '#16a34a' : 'var(--muted)' }}>
                          {row.saved ? '✓ saved' : 'ready'}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
