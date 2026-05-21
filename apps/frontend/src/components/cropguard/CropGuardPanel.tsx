'use client';

import { useMemo, useRef, useState } from 'react';

import { useTenant } from '@/context/TenantContext';
import {
  fileToBase64,
  useCropPredictions,
  usePredictCropDisease,
  type CropPredictionData,
  type CropPredictionRow,
} from '@/hooks/useCropPredictions';


const STATE_NAMES: Record<string, string> = {
  kebbi: 'Kebbi State',
  benue: 'Benue State',
  plateau: 'Plateau State',
  kaduna: 'Kaduna State',
  niger: 'Niger State',
  zamfara: 'Zamfara State',
  nasarawa: 'Nasarawa State',
  fct: 'Federal Capital Territory',
  ghana: 'Ghana',
  senegal: 'Senegal',
};

const MAX_INLINE_BYTES = 8 * 1024 * 1024;
const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];


function prettifyClass(name: string): string {
  return name
    .split('_')
    .map((p) => (p === p.toUpperCase() ? p : p.charAt(0).toUpperCase() + p.slice(1)))
    .join(' ');
}

function relativeAge(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return 'just now';
  const min = Math.round(ms / 60_000);
  if (min < 60) return `${min} min ago`;
  const hr = Math.round(min / 60);
  if (hr < 48) return `${hr} hr ago`;
  return `${Math.round(hr / 24)} d ago`;
}

function bandClass(band: 'HIGH' | 'MEDIUM' | 'LOW'): string {
  switch (band) {
    case 'HIGH': return 'cg-band cg-band-high';
    case 'MEDIUM': return 'cg-band cg-band-medium';
    case 'LOW': return 'cg-band cg-band-low';
  }
}


export default function CropGuardPanel() {
  const { activeTenantId, activeTenant, pilotTenants, setActiveTenant } = useTenant();

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<CropPredictionData | null>(null);
  const [requestSaliency, setRequestSaliency] = useState(true);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const recentQuery = useCropPredictions({ tenantId: activeTenantId, limit: 10 });
  const recent = useMemo(
    () => recentQuery.data?.predictions ?? [],
    [recentQuery.data],
  );

  const predictMutation = usePredictCropDisease(activeTenantId);

  const stateLabel = STATE_NAMES[activeTenantId] ?? activeTenant.name;
  const modeBadge = useMemo(() => {
    // Show whatever the most recent prediction tells us; otherwise neutral.
    const v = lastResult?.model_version ?? recent[0]?.model_version;
    if (!v) return null;
    if (v.endsWith('-trained')) return { label: 'TRAINED', cls: 'cg-mode-trained' };
    if (v.endsWith('-untuned')) return { label: 'UNTUNED', cls: 'cg-mode-untuned' };
    if (v.endsWith('-stub')) return { label: 'STUB', cls: 'cg-mode-stub' };
    return { label: v, cls: 'cg-mode-stub' };
  }, [lastResult, recent]);

  function handleFile(file: File) {
    setUploadError(null);
    setLastResult(null);
    if (!ACCEPTED_TYPES.includes(file.type)) {
      setUploadError(`Unsupported file type: ${file.type}. Use JPEG, PNG, or WebP.`);
      return;
    }
    if (file.size > MAX_INLINE_BYTES) {
      setUploadError(
        `Image too large (${Math.round(file.size / 1024 / 1024)} MB). Max is 8 MB.`,
      );
      return;
    }
    setSelectedFile(file);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(URL.createObjectURL(file));
  }

  function clearSelection() {
    setSelectedFile(null);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    setLastResult(null);
    setUploadError(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  async function analyze() {
    if (!selectedFile) return;
    setUploadError(null);
    try {
      const base64 = await fileToBase64(selectedFile);
      const result = await predictMutation.mutateAsync({
        tenant_id: activeTenantId,
        image_base64: base64,
        top_k: 5,
        compute_saliency: requestSaliency,
        persist: true,
      });
      setLastResult(result);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Prediction failed';
      setUploadError(msg);
    }
  }

  function onDrop(e: React.DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }

  return (
    <div>
      {/* HEADER */}
      <div className="cg-header">
        <div>
          <div className="cg-title">CropGuard — ResNet-50 Disease Classifier</div>
          <div className="cg-subtitle">
            12-class West African crop diseases (cassava, maize, rice, tomato, plantain) · upload
            a leaf photo for an instant on-field diagnosis
          </div>
        </div>
        {modeBadge && (
          <div className={`cg-mode-badge ${modeBadge.cls}`}>
            MODEL: {modeBadge.label}
          </div>
        )}
      </div>

      {/* TENANT SELECTOR */}
      <div className="fp-tenant-bar">
        <label htmlFor="cg-tenant-select" className="fp-tenant-label">
          Viewing tenant
        </label>
        <select
          id="cg-tenant-select"
          className="fp-tenant-select"
          value={activeTenantId}
          onChange={(e) => setActiveTenant(e.target.value)}
        >
          {pilotTenants.map((t) => (
            <option key={t.id} value={t.id}>
              {STATE_NAMES[t.id] ?? t.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="fp-refresh-btn"
          onClick={() => recentQuery.refetch()}
          disabled={recentQuery.isFetching}
        >
          {recentQuery.isFetching ? 'Refreshing…' : 'Refresh feed'}
        </button>
      </div>

      <div className="cg-main-row">
        {/* LEFT: UPLOAD + RESULT */}
        <div className="cg-upload-col">
          <div className="cg-section-header">Analyze a leaf photo</div>

          <label
            htmlFor="cg-file-input"
            className={`cg-dropzone ${previewUrl ? 'cg-dropzone--has-image' : ''}`}
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop}
          >
            {previewUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={previewUrl} alt="Selected leaf preview" className="cg-preview" />
            ) : (
              <div className="cg-dropzone-empty">
                <div className="cg-dropzone-icon">📷</div>
                <div className="cg-dropzone-text">
                  Drop a leaf photo here or <span className="cg-link">click to choose</span>
                </div>
                <div className="cg-dropzone-hint">JPEG / PNG / WebP · max 8 MB</div>
              </div>
            )}
            <input
              ref={fileInputRef}
              id="cg-file-input"
              type="file"
              accept={ACCEPTED_TYPES.join(',')}
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleFile(file);
              }}
            />
          </label>

          {uploadError && (
            <div className="fp-alert-error">{uploadError}</div>
          )}

          <div className="cg-upload-actions">
            <button
              type="button"
              className="cg-primary-btn"
              onClick={analyze}
              disabled={!selectedFile || predictMutation.isPending}
            >
              {predictMutation.isPending ? 'Analyzing…' : 'Analyze'}
            </button>
            {selectedFile && (
              <button
                type="button"
                className="fp-refresh-btn"
                onClick={clearSelection}
                disabled={predictMutation.isPending}
              >
                Clear
              </button>
            )}
            <label className="cg-saliency-toggle">
              <input
                type="checkbox"
                checked={requestSaliency}
                onChange={(e) => setRequestSaliency(e.target.checked)}
                disabled={predictMutation.isPending}
              />
              <span>Show Grad-CAM heatmap</span>
            </label>
          </div>

          {lastResult && (
            <ResultCard result={lastResult} />
          )}
        </div>

        {/* RIGHT: RECENT FEED */}
        <div className="cg-recent-col">
          <div className="cg-section-header">
            Recent predictions — {stateLabel}
            <span className="fp-alert-count">{recent.length}</span>
          </div>
          {recentQuery.isLoading && (
            <div className="fp-alert-empty">Loading recent predictions…</div>
          )}
          {recentQuery.isError && (
            <div className="fp-alert-error">
              Could not load recent predictions: {recentQuery.error?.message ?? 'unknown'}
            </div>
          )}
          {!recentQuery.isLoading && !recentQuery.isError && recent.length === 0 && (
            <div className="fp-alert-empty">
              No predictions yet for {stateLabel}. Upload a leaf photo to populate the feed.
            </div>
          )}
          {recent.map((row) => <RecentRow key={row.id} row={row} />)}
        </div>
      </div>
    </div>
  );
}


function ResultCard({ result }: { result: CropPredictionData }) {
  const isDisease = !result.predicted_class.endsWith('_healthy');
  return (
    <div className="cg-result">
      <div className="cg-result-header">
        <div>
          <div className="cg-result-class">{prettifyClass(result.predicted_class)}</div>
          <div className="cg-result-sub">
            Confidence: {Math.round(result.confidence * 100)}% ·{' '}
            <span className={bandClass(result.confidence_band)}>{result.confidence_band}</span>
            {result.requires_human_review && (
              <span className="cg-review-flag"> · ⚑ Human review required</span>
            )}
          </div>
        </div>
        <div className={`cg-result-score ${isDisease ? 'cg-result-score--bad' : 'cg-result-score--ok'}`}>
          {Math.round(result.prediction * 100)}
          <span className="cg-result-score-unit">/100</span>
        </div>
      </div>

      {result.saliency_b64 && (
        <div className="cg-saliency-wrap">
          <div className="cg-saliency-label">
            Grad-CAM saliency · where the model looked
          </div>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`data:image/png;base64,${result.saliency_b64}`}
            alt="Grad-CAM heatmap overlay highlighting attended regions"
            className="cg-saliency-img"
          />
        </div>
      )}

      <div className="cg-topk-list">
        {result.top_k.map((entry, idx) => (
          <div key={entry.class_name} className="cg-topk-row">
            <span className="cg-topk-rank">{idx + 1}.</span>
            <span className="cg-topk-name">{prettifyClass(entry.class_name)}</span>
            <div className="cg-topk-bar-wrap">
              <div
                className="cg-topk-bar"
                style={{ width: `${Math.max(2, Math.round(entry.probability * 100))}%` }}
              />
            </div>
            <span className="cg-topk-pct">{Math.round(entry.probability * 100)}%</span>
          </div>
        ))}
      </div>

      <div className="cg-result-footnote">
        {result.model_name} {result.model_version} · {result.inference_time_ms} ms
        {result.persisted ? ' · saved to predictions log' : ' · dry run (not saved)'}
      </div>
    </div>
  );
}


function RecentRow({ row }: { row: CropPredictionRow }) {
  const isDisease = !row.predicted_class.endsWith('_healthy');
  return (
    <div className="cg-recent-row">
      <div className="cg-recent-top">
        <span className={`cg-recent-marker ${isDisease ? 'cg-recent-marker--bad' : 'cg-recent-marker--ok'}`}>
          {isDisease ? '⚠' : '✓'}
        </span>
        <span className="cg-recent-class">{prettifyClass(row.predicted_class)}</span>
        <span className={bandClass(row.confidence_band)}>{row.confidence_band}</span>
      </div>
      <div className="cg-recent-meta">
        {Math.round(row.confidence * 100)}% confidence · {relativeAge(row.created_at)} ·{' '}
        {row.model_version}
        {row.requires_human_review && <span className="cg-review-flag"> · review</span>}
      </div>
    </div>
  );
}
