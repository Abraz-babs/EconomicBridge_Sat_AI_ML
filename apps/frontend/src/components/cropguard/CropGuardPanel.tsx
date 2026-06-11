'use client';

import { useMemo, useRef, useState } from 'react';

import { useTenant } from '@/context/TenantContext';
import {
  fileToBase64,
  useCropModelInfo,
  useCropPredictions,
  usePredictCropDisease,
  usePredictCropDiseaseTiled,
  type CropPredictionData,
  type CropPredictionRow,
  type CropTiledPredictionData,
  type TileResult,
} from '@/hooks/useCropPredictions';
import CropGuardMap from './CropGuardMap';
import CropMarketPanel from './CropMarketPanel';
import NdviAnomalyPanel from './NdviAnomalyPanel';
import YieldForecastPanel from './YieldForecastPanel';


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

  const [analysisMode, setAnalysisMode] = useState<'leaf' | 'field'>('leaf');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<CropPredictionData | null>(null);
  const [lastTiledResult, setLastTiledResult] = useState<CropTiledPredictionData | null>(null);
  const [requestSaliency, setRequestSaliency] = useState(true);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const recentQuery = useCropPredictions({ tenantId: activeTenantId, limit: 10 });
  const recent = useMemo(
    () => recentQuery.data?.predictions ?? [],
    [recentQuery.data],
  );
  const modelInfo = useCropModelInfo();

  const predictMutation = usePredictCropDisease(activeTenantId);
  const predictTiledMutation = usePredictCropDiseaseTiled(activeTenantId);
  const isPending = predictMutation.isPending || predictTiledMutation.isPending;

  const stateLabel = STATE_NAMES[activeTenantId] ?? activeTenant.name;
  const modeBadge = useMemo(() => {
    // The badge reports MODEL CAPABILITY (what the ml service would use for
    // the next inference), not the provenance of historic rows — a trained
    // model reads TRAINED on every tenant, even those whose stored rows are
    // still seeds. Falls back to the latest row's version if the capability
    // endpoint is unreachable.
    const v =
      modelInfo.data?.model_version ??
      lastResult?.model_version ??
      recent[0]?.model_version;
    if (!v) return null;
    if (v.endsWith('-trained')) return { label: 'TRAINED', cls: 'cg-mode-trained' };
    if (v.endsWith('-untuned')) return { label: 'UNTUNED', cls: 'cg-mode-untuned' };
    if (v.endsWith('-stub')) return { label: 'STUB', cls: 'cg-mode-stub' };
    if (v.endsWith('-seed')) return { label: 'DEMO', cls: 'cg-mode-untuned' };
    return { label: v, cls: 'cg-mode-stub' };
  }, [modelInfo.data, lastResult, recent]);

  function handleFile(file: File) {
    setUploadError(null);
    setLastResult(null);
    setLastTiledResult(null);
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
    setLastTiledResult(null);
    setUploadError(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  async function analyze() {
    if (!selectedFile) return;
    setUploadError(null);
    try {
      const base64 = await fileToBase64(selectedFile);
      if (analysisMode === 'leaf') {
        const result = await predictMutation.mutateAsync({
          tenant_id: activeTenantId,
          image_base64: base64,
          top_k: 5,
          compute_saliency: requestSaliency,
          persist: true,
        });
        setLastResult(result);
        setLastTiledResult(null);
      } else {
        const result = await predictTiledMutation.mutateAsync({
          tenant_id: activeTenantId,
          image_base64: base64,
          rows: 4, cols: 4,
          top_k: 3,
          persist: true,
        });
        setLastTiledResult(result);
        setLastResult(null);
      }
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

      {/* MAP — predictions geography */}
      <div className="fp-map ac-map-wrap">
        <div className="fp-map-header">
          <span className="fp-map-title">
            Disease Geography — {stateLabel}
          </span>
          <span className="ev-map-meta">
            {recent.length} prediction{recent.length === 1 ? '' : 's'} ·
            Sources: ResNet-50 + Sentinel-2 ROI · synthesised positions for
            non-geolocated uploads
          </span>
        </div>
        <CropGuardMap tenant={activeTenant} predictions={recent} />
      </div>

      <div className="cg-main-row">
        {/* LEFT: UPLOAD + RESULT */}
        <div className="cg-upload-col">
          <div className="cg-section-header">
            Analyze {analysisMode === 'leaf' ? 'a leaf photo' : 'a field photo'}
            <div className="cg-mode-switch">
              <button
                type="button"
                className={`cg-mode-btn ${analysisMode === 'leaf' ? 'is-active' : ''}`}
                onClick={() => setAnalysisMode('leaf')}
                disabled={isPending}
              >
                Leaf
              </button>
              <button
                type="button"
                className={`cg-mode-btn ${analysisMode === 'field' ? 'is-active' : ''}`}
                onClick={() => setAnalysisMode('field')}
                disabled={isPending}
              >
                Field (4×4 tiles)
              </button>
            </div>
          </div>

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
                  {analysisMode === 'leaf'
                    ? <>Drop a leaf photo here or <span className="cg-link">click to choose</span></>
                    : <>Drop a wide field photo here or <span className="cg-link">click to choose</span></>}
                </div>
                <div className="cg-dropzone-hint">
                  {analysisMode === 'leaf'
                    ? 'Best results: ONE leaf filling the frame, top side, good light — the model is trained on single-leaf close-ups. For whole-field shots switch to Field mode.'
                    : 'Wide canopy shot — analysed as 4×4 tiles and aggregated.'}
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
              disabled={!selectedFile || isPending}
            >
              {isPending ? 'Analyzing…' : 'Analyze'}
            </button>
            {selectedFile && (
              <button
                type="button"
                className="fp-refresh-btn"
                onClick={clearSelection}
                disabled={isPending}
              >
                Clear
              </button>
            )}
            {analysisMode === 'leaf' && (
              <label className="cg-saliency-toggle">
                <input
                  type="checkbox"
                  checked={requestSaliency}
                  onChange={(e) => setRequestSaliency(e.target.checked)}
                  disabled={isPending}
                />
                <span>Show Grad-CAM heatmap</span>
              </label>
            )}
          </div>

          {lastResult && <ResultCard result={lastResult} />}
          {lastTiledResult && <TiledResultCard result={lastTiledResult} />}
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

      {/* PRE-SYMPTOMATIC NDVI ANOMALY (Slice 04.d) */}
      <NdviAnomalyPanel />

      {/* YIELD FORECASTS (Slice 04.c) */}
      <YieldForecastPanel />

      {/* MARKET PRICES (Slice 04.b) */}
      <CropMarketPanel />
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


function TiledResultCard({ result }: { result: CropTiledPredictionData }) {
  const hottest = result.hottest_tile;
  const isDisease = !hottest.predicted_class.endsWith('_healthy');
  return (
    <div className="cg-result">
      <div className="cg-result-header">
        <div>
          <div className="cg-result-class">
            {prettifyClass(hottest.predicted_class)}
            <span className="cg-tiled-flag"> · hottest tile (row {hottest.row}, col {hottest.col})</span>
          </div>
          <div className="cg-result-sub">
            {result.rows}×{result.cols} grid · {result.tiles.length} tiles ·{' '}
            {result.tile_width}×{result.tile_height}px each ·{' '}
            {result.total_inference_time_ms} ms total
          </div>
        </div>
        <div className={`cg-result-score ${isDisease ? 'cg-result-score--bad' : 'cg-result-score--ok'}`}>
          {Math.round(result.aggregate_prediction * 100)}
          <span className="cg-result-score-unit">/100</span>
        </div>
      </div>

      <div
        className="cg-tile-grid"
        data-cols={result.cols}
      >
        {result.tiles.map((tile) => (
          <TileCell key={`${tile.row}-${tile.col}`} tile={tile} cols={result.cols} />
        ))}
      </div>

      <div className="cg-result-footnote">
        {result.model_name} {result.model_version} ·{' '}
        {result.persisted ? 'aggregate row saved to predictions log' : 'dry run'}
      </div>
    </div>
  );
}


function TileCell({ tile, cols }: { tile: TileResult; cols: number }) {
  const isDisease = !tile.predicted_class.endsWith('_healthy');
  const intensity = Math.round(tile.prediction * 100);
  return (
    <div
      className={`cg-tile-cell ${isDisease ? 'cg-tile-cell--bad' : 'cg-tile-cell--ok'}`}
      title={`Row ${tile.row}, Col ${tile.col} · ${prettifyClass(tile.predicted_class)} · ${intensity}%`}
      style={{
        // The grid layout itself is in CSS; only the per-cell heat fill
        // is dynamic and must stay inline.
        '--cg-tile-heat': `${intensity}%`,
        width: `${100 / cols}%`,
      } as React.CSSProperties}
    >
      <div className="cg-tile-fill" />
      <div className="cg-tile-label">
        <span className={bandClass(tile.confidence_band)}>{intensity}</span>
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
