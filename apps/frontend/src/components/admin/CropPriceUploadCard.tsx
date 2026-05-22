'use client';

import { useRef, useState } from 'react';

import {
  useBulkCropPriceUpload,
  type BulkPriceUploadResult,
} from '@/hooks/useBulkUpload';


const SOURCE_OPTIONS: { value: string; label: string }[] = [
  { value: 'nbs_fpw_v1', label: 'NBS Food Price Watch (nbs_fpw_v1)' },
  { value: 'wfp_hdx_v1', label: 'WFP HDX food prices (wfp_hdx_v1)' },
  { value: 'faostat_v1', label: 'FAOSTAT (faostat_v1)' },
  { value: 'amis_v1', label: 'AMIS (amis_v1)' },
  { value: 'manual_admin_v1', label: 'Manual admin (manual_admin_v1)' },
];

const SAMPLE_CSV =
  'crop,region,observed_at,price_ngn_per_kg\n' +
  'maize,kebbi,2026-04-01,560\n' +
  'rice,kaduna,2026-04-01,1920\n' +
  'sorghum,kebbi,2026-04-01,820\n';


export default function CropPriceUploadCard() {
  const [source, setSource] = useState(SOURCE_OPTIONS[0].value);
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<BulkPriceUploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const mutation = useBulkCropPriceUpload();

  async function submit() {
    if (!file) {
      setError('Pick a CSV file first.');
      return;
    }
    setError(null);
    setResult(null);
    try {
      const data = await mutation.mutateAsync({ file, source });
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
        <span className="panel-title">Crop Price Bulk Upload — Module 04</span>
        <span className="panel-meta">NBS · WFP HDX · FAOSTAT · AMIS</span>
      </div>
      <div className="upload-body">
        <p className="upload-desc">
          Upload a CSV of crop × region × date prices. Required columns:{' '}
          <code>crop,region,observed_at,price_ngn_per_kg</code> (ISO-8601 date,
          price &gt; 0). Cross-tenant table — no tenant selector. Re-uploads
          of the same source replace cleanly.
        </p>

        <div className="upload-row">
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
            <span className="upload-field-label">CSV file (≤5 MB, ≤20,000 rows)</span>
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
        {result && <PriceResultPanel result={result} />}
      </div>
    </div>
  );
}


function PriceResultPanel({ result }: { result: BulkPriceUploadResult }) {
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
        source <code>{result.source}</code>
      </div>
      <div className="upload-result-detail">
        Crops covered ({result.crops_seen.length}):{' '}
        <code>{result.crops_seen.join(', ') || '—'}</code>
        <br />
        Regions covered ({result.regions_seen.length}):{' '}
        <code>{result.regions_seen.join(', ') || '—'}</code>
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
