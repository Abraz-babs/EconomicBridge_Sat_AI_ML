'use client';

import { useRef, useState } from 'react';

import { useTenant } from '@/context/TenantContext';
import {
  fileToBase64,
  usePredictCropDisease,
  useTenantLgas,
} from '@/hooks/useCropPredictions';

function fmtClass(c: string): string {
  return c
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

const inputStyle: React.CSSProperties = {
  background: 'var(--surface)',
  border: '1px solid var(--border2)',
  borderRadius: '3px',
  color: 'var(--ink)',
  padding: '5px 10px',
  fontSize: '12px',
  fontFamily: "'DM Mono', monospace",
  width: '130px',
};

export default function LeafDiagnosisPanel() {
  const { activeTenantId, activeTenant } = useTenant();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [lga, setLga] = useState('');
  const [crop, setCrop] = useState('');
  const predict = usePredictCropDisease(activeTenantId);
  const lgasQuery = useTenantLgas(activeTenantId);
  const inputRef = useRef<HTMLInputElement>(null);

  const onPick = (f: File | null) => {
    setFile(f);
    predict.reset();
    if (preview) URL.revokeObjectURL(preview);
    setPreview(f ? URL.createObjectURL(f) : null);
  };

  const diagnose = async () => {
    if (!file) return;
    const image_base64 = await fileToBase64(file);
    // Persist the record, tagged by state (tenant) + LGA + crop, so it can be
    // recalled later in the recent-diagnoses feed.
    predict.mutate({
      tenant_id: activeTenantId,
      image_base64,
      top_k: 3,
      persist: true,
      lga: lga || undefined,
      zone_name: crop.trim() || undefined,
    });
  };

  const r = predict.data;
  const isHealthy = r?.predicted_class.endsWith('_healthy') ?? false;
  const color = !r ? '#9ca3af' : isHealthy ? '#22c55e' : r.confidence >= 0.6 ? '#ef4444' : '#eab308';

  return (
    <div className="sb-table-wrap" style={{ marginTop: '16px' }}>
      <div className="cg-section-header">Leaf Diagnosis — AI disease ID from a photo</div>
      <div className="cg-subtitle" style={{ marginBottom: '4px' }}>
        Upload a <strong>close-up of a single leaf that fills the frame</strong> —
        not a whole field or landscape. The trained ResNet-50 then identifies the
        disease (or confirms it is healthy) with a confidence score.
      </div>
      <div className="ev-map-meta" style={{ marginBottom: '10px' }}>
        📷 Best results: one affected leaf, plain background, good light. For
        field-/landscape-level monitoring, use the satellite <em>Farm Check</em> above.
      </div>

      {/* Record tag — state (the panel's tenant selector) + LGA + crop. */}
      <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'flex-end', margin: '4px 0 10px' }}>
        <label style={{ fontSize: '12px' }}>
          <div className="fp-tenant-label">State</div>
          <div style={{ ...inputStyle, width: 'auto', minWidth: '130px' }}>{activeTenant.name}</div>
        </label>
        <label style={{ fontSize: '12px' }}>
          <div className="fp-tenant-label">LGA</div>
          <select className="fp-tenant-select" value={lga} onChange={(e) => setLga(e.target.value)}>
            <option value="">{lgasQuery.isLoading ? 'Loading…' : 'Select LGA…'}</option>
            {(lgasQuery.data ?? []).map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>
        </label>
        <label style={{ fontSize: '12px' }}>
          <div className="fp-tenant-label">Crop</div>
          <input style={inputStyle} value={crop} onChange={(e) => setCrop(e.target.value)} placeholder="e.g. maize" />
        </label>
        <span className="ev-map-meta">State follows the selector at the top of CropGuard.</span>
      </div>

      <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center', margin: '4px 0 12px' }}>
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          style={{ display: 'none' }}
          onChange={(e) => onPick(e.target.files?.[0] ?? null)}
        />
        <button type="button" className="fp-refresh-btn" onClick={() => inputRef.current?.click()}>
          Choose leaf photo
        </button>
        {file && <span className="ev-map-meta">{file.name}</span>}
        <button
          type="button"
          className="fp-refresh-btn"
          onClick={diagnose}
          disabled={!file || predict.isPending}
        >
          {predict.isPending ? 'Diagnosing…' : 'Diagnose'}
        </button>
      </div>

      {preview && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={preview}
          alt="Uploaded crop leaf"
          style={{ maxHeight: '180px', borderRadius: '8px', marginBottom: '10px', display: 'block' }}
        />
      )}

      {predict.isError && (
        <div className="fp-alert-empty">Couldn&apos;t diagnose: {predict.error.message}</div>
      )}

      {r && (
        <div style={{ padding: '12px 14px', borderRadius: '8px', background: 'rgba(0,0,0,0.03)', borderLeft: `4px solid ${color}` }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <span style={{ background: color, color: '#10130f', fontWeight: 700, fontSize: '12px', padding: '3px 10px', borderRadius: '12px' }}>
              {isHealthy ? 'Healthy' : 'Disease'}
            </span>
            <strong style={{ fontSize: '15px' }}>{fmtClass(r.predicted_class)}</strong>
            <span className="ev-map-meta">
              {(r.confidence * 100).toFixed(0)}% confidence · {r.confidence_band}
              {r.requires_human_review ? ' · review advised' : ''}
            </span>
          </div>
          {r.top_k.length > 1 && (
            <div className="ev-map-meta" style={{ marginTop: '8px' }}>
              Also considered:{' '}
              {r.top_k.slice(1).map((t) => `${fmtClass(t.class_name)} ${(t.probability * 100).toFixed(0)}%`).join(' · ')}
            </div>
          )}
          {r.confidence < 0.6 && (
            <div className="ev-map-meta" style={{ marginTop: '8px', color: '#b45309' }}>
              ⚠ Low confidence — if this looks wrong, retake as a tighter close-up
              of one affected leaf (a field/landscape photo can&apos;t be diagnosed per-leaf).
            </div>
          )}
          <div className="ev-map-meta" style={{ marginTop: '8px' }}>
            {r.persisted ? (
              <span style={{ color: '#16a34a' }}>
                ✓ Saved to field records — {activeTenant.name}
                {lga ? ` · ${lga}` : ''}{crop.trim() ? ` · ${crop.trim()}` : ''}.
                Recall it in “Recent predictions” below.
              </span>
            ) : (
              'Not saved (add an LGA/crop and re-run to keep a record).'
            )}
          </div>
          <div className="ev-map-meta" style={{ marginTop: '8px', opacity: 0.85 }}>
            AI diagnosis from the leaf image (model {r.model_version}). Trained on
            specific crops/diseases — confirm in‑field before treatment; local
            labelled data sharpens accuracy further.
          </div>
        </div>
      )}
    </div>
  );
}
