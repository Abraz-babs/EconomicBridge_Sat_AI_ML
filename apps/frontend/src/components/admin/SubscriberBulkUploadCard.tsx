'use client';

import { useRef, useState } from 'react';

import { useTenant } from '@/context/TenantContext';
import {
  useBulkSubscriberUpload,
  type BulkSubscriberUploadResult,
} from '@/hooks/useBulkUpload';

const SAMPLE_CSV =
  'phone_e164,lga,language,severity_threshold,full_name\n' +
  '+2348030000001,Logo,ha,all,Audu Musa\n' +
  '+2348030000002,Gboko,ha,high,Bala Iko\n' +
  '+221770000003,Bakel,fr,high,Diallo\n';

/**
 * Bulk-import farmer contacts for a state/tenant into alert_subscribers.
 * Partner-agency lists (state ag dept, NEMA, cooperatives) per state. Upserts
 * on (phone, lga) so re-uploads refresh rather than duplicate.
 */
export default function SubscriberBulkUploadCard() {
  const { activeTenantId, pilotTenants } = useTenant();
  const [uploadTenant, setUploadTenant] = useState(activeTenantId);
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<BulkSubscriberUploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const mutation = useBulkSubscriberUpload();

  async function submit() {
    if (!file) { setError('Pick a CSV file first.'); return; }
    setError(null);
    setResult(null);
    try {
      setResult(await mutation.mutateAsync({ tenantId: uploadTenant, file }));
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
        <span className="panel-title">Farmer Contacts · Bulk Import</span>
        <span className="panel-meta">Partner-agency lists · per state/LGA</span>
      </div>
      <div className="upload-body">
        <p className="upload-desc">
          Upload a partner agency&apos;s farmer contact list for one state. Required
          columns: <code>phone_e164,lga</code> (<code>language</code>,{' '}
          <code>severity_threshold</code>, <code>full_name</code> optional).
          Stored in <code>tenant_&lt;id&gt;.alert_subscribers</code>; re-uploads
          UPSERT on (phone, LGA) so they refresh, never duplicate.
        </p>

        <div className="upload-row">
          <label className="upload-field">
            <span className="upload-field-label">State / tenant</span>
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
          <label className="upload-field upload-field--grow">
            <span className="upload-field-label">CSV file (≤5 MB)</span>
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,text/csv,application/csv"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              disabled={mutation.isPending}
              className="upload-file"
            />
          </label>
          <button type="button" className="cg-yield-btn" onClick={submit}
            disabled={mutation.isPending || !file}>
            {mutation.isPending ? 'Importing…' : 'Import'}
          </button>
          {(result || error) && (
            <button type="button" className="upload-reset-btn" onClick={reset}
              disabled={mutation.isPending}>
              Reset
            </button>
          )}
        </div>

        <details className="upload-sample">
          <summary>Show sample CSV format</summary>
          <pre>{SAMPLE_CSV}</pre>
        </details>

        {error && <div className="fp-alert-error">{error}</div>}
        {result && <ImportResultPanel result={result} />}
      </div>
    </div>
  );
}

function ImportResultPanel({ result }: { result: BulkSubscriberUploadResult }) {
  const allClean = result.rows_skipped === 0;
  return (
    <div className={`upload-result ${allClean ? 'upload-result--ok' : 'upload-result--mixed'}`}>
      <div className="upload-result-summary">
        <strong>{allClean ? '✓' : '⚠'} {result.rows_inserted} added</strong>
        {' · '}{result.rows_updated} updated{' · '}{result.rows_skipped} skipped{' · '}
        state <code>{result.tenant_id}</code>
      </div>
      {result.errors.length > 0 && (
        <div className="upload-errors">
          <div className="upload-errors-header">Per-row errors</div>
          <table className="upload-errors-table">
            <thead><tr><th>Line</th><th>Error</th><th>Row</th></tr></thead>
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
