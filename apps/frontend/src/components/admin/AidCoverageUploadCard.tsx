'use client';

import { useRef, useState } from 'react';

import { useTenant } from '@/context/TenantContext';
import {
  useBulkAidCoverageUpload,
  type BulkCoverageUploadResult,
} from '@/hooks/useBulkUpload';


const SOURCE_OPTIONS: { value: string; label: string }[] = [
  { value: 'wfp_scope_v1', label: 'WFP SCOPE export (wfp_scope_v1)' },
  { value: 'unhcr_progres_v1', label: 'UNHCR proGres export (unhcr_progres_v1)' },
  { value: 'nema_manual_v1', label: 'NEMA manual entry (nema_manual_v1)' },
  { value: 'manual_admin_v1', label: 'Manual admin (manual_admin_v1)' },
];

const SAMPLE_CSV =
  'agency_slug,lga,beneficiaries_served,last_active_at\n' +
  'wfp,Argungu,12500,2026-04-15\n' +
  'unhcr,Birnin Kebbi,3400,2026-04-12\n';


export default function AidCoverageUploadCard() {
  const { activeTenantId, pilotTenants } = useTenant();
  const [uploadTenant, setUploadTenant] = useState(activeTenantId);
  const [source, setSource] = useState(SOURCE_OPTIONS[0].value);
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<BulkCoverageUploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const mutation = useBulkAidCoverageUpload();

  async function submit() {
    if (!file) {
      setError('Pick a CSV file first.');
      return;
    }
    setError(null);
    setResult(null);
    try {
      const data = await mutation.mutateAsync({
        tenantId: uploadTenant, file, source,
      });
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
    }
  }

  function reset() {
    setFile(null);
    setResult(null);
    setError(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Aid Coverage Bulk Upload — Module 02</span>
        <span className="panel-meta">WFP SCOPE · UNHCR proGres · NEMA</span>
      </div>
      <div className="upload-body">
        <p className="upload-desc">
          Upload a CSV of agency × LGA coverage rows. Required columns:{' '}
          <code>agency_slug,lga,beneficiaries_served</code>{' '}
          (<code>last_active_at</code> optional, ISO-8601). Re-uploads of
          the same source replace cleanly (UPSERT on agency × LGA × source).
        </p>

        <div className="upload-row">
          <label className="upload-field">
            <span className="upload-field-label">Tenant</span>
            <select
              value={uploadTenant}
              onChange={(e) => setUploadTenant(e.target.value)}
              disabled={mutation.isPending}
              className="upload-select"
            >
              {pilotTenants.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </label>
          <label className="upload-field">
            <span className="upload-field-label">Source tag</span>
            <select
              value={source}
              onChange={(e) => setSource(e.target.value)}
              disabled={mutation.isPending}
              className="upload-select"
            >
              {SOURCE_OPTIONS.map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </label>
        </div>

        <div className="upload-row">
          <label className="upload-field upload-field--grow">
            <span className="upload-field-label">CSV file (≤5 MB, ≤5000 rows)</span>
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,text/csv,application/csv"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              disabled={mutation.isPending}
              className="upload-file"
            />
          </label>
          <button
            type="button"
            className="cg-yield-btn"
            onClick={submit}
            disabled={mutation.isPending || !file}
          >
            {mutation.isPending ? 'Uploading…' : 'Upload'}
          </button>
          {(result || error) && (
            <button
              type="button"
              className="upload-reset-btn"
              onClick={reset}
              disabled={mutation.isPending}
            >
              Reset
            </button>
          )}
        </div>

        <details className="upload-sample">
          <summary>Show sample CSV format</summary>
          <pre>{SAMPLE_CSV}</pre>
        </details>

        {error && <div className="fp-alert-error">{error}</div>}
        {result && <UploadResultPanel result={result} />}
      </div>
    </div>
  );
}


function UploadResultPanel({ result }: { result: BulkCoverageUploadResult }) {
  const allClean = result.rows_skipped === 0;
  return (
    <div className={`upload-result ${allClean ? 'upload-result--ok' : 'upload-result--mixed'}`}>
      <div className="upload-result-summary">
        <strong>
          {allClean ? '✓' : '⚠'} {result.rows_inserted} row
          {result.rows_inserted === 1 ? '' : 's'} inserted
        </strong>
        {' · '}
        {result.rows_skipped} skipped{' · '}
        tenant <code>{result.tenant_id}</code>{' · '}
        source <code>{result.source}</code>
      </div>
      {result.errors.length > 0 && (
        <div className="upload-errors">
          <div className="upload-errors-header">Per-row errors</div>
          <table className="upload-errors-table">
            <thead>
              <tr>
                <th>Line</th>
                <th>Error</th>
                <th>Row</th>
              </tr>
            </thead>
            <tbody>
              {result.errors.map((e, i) => (
                <tr key={`${e.line_number}-${i}`}>
                  <td>{e.line_number}</td>
                  <td>{e.error}</td>
                  <td>
                    <code>
                      {Object.entries(e.raw_row)
                        .map(([k, v]) => `${k}=${v || '(empty)'}`)
                        .join(', ')}
                    </code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
