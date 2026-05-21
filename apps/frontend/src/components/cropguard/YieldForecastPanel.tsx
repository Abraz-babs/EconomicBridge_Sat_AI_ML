'use client';

import { useMemo, useState } from 'react';

import { useTenant } from '@/context/TenantContext';
import {
  usePredictYield,
  useYieldForecasts,
  type YieldForecastRow,
  type YieldPredictionData,
} from '@/hooks/useYieldForecasts';


const CROPS: { id: string; label: string }[] = [
  { id: 'maize',        label: 'Maize' },
  { id: 'rice',         label: 'Rice' },
  { id: 'cassava',      label: 'Cassava' },
  { id: 'yam',          label: 'Yam' },
  { id: 'sorghum',      label: 'Sorghum' },
  { id: 'millet',       label: 'Millet' },
  { id: 'cowpea',       label: 'Cowpea' },
  { id: 'groundnut',    label: 'Groundnut' },
  { id: 'soybean',      label: 'Soybean' },
  { id: 'tomato',       label: 'Tomato' },
  { id: 'pepper',       label: 'Pepper' },
  { id: 'onion',        label: 'Onion' },
  { id: 'plantain',     label: 'Plantain' },
  { id: 'sweet_potato', label: 'Sweet potato' },
];

const CROP_LABEL = Object.fromEntries(CROPS.map(c => [c.id, c.label]));

/** Same per-crop reference max as apps/ml/models/yield_training.py — keep in sync. */
const CROP_REFERENCE_MAX: Record<string, number> = {
  maize: 6.0, rice: 5.5, cassava: 14.0, yam: 10.0, sorghum: 4.0,
  millet: 3.0, cowpea: 2.0, groundnut: 2.5, soybean: 3.5, tomato: 8.0,
  pepper: 4.0, onion: 7.0, plantain: 10.0, sweet_potato: 8.0,
};


function fmtYield(t: number): string {
  if (t < 1) return `${(t * 1000).toFixed(0)} kg/ha`;
  return `${t.toFixed(2)} t/ha`;
}


/**
 * Deterministic-per-tenant default feature vector. Real fields will
 * carry tenant-specific NDVI/rainfall when the ingestion path lands;
 * for now we hash from the tenant slug + crop to keep the demo
 * reproducible across reloads.
 */
function defaultFeaturesFor(
  tenantId: string,
  crop: string,
): {
  ndvi_mean_30d: number;
  ndvi_anomaly: number;
  rainfall_30d_mm: number;
  rainfall_anomaly: number;
  soil_quality_index: number;
  historical_yield_mean_t_ha: number;
  days_to_harvest: number;
} {
  let h = 5381;
  const s = `${tenantId}|${crop}`;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  h = Math.abs(h);
  const u = (n: number) => (h >>> (n * 3)) & 0xff;

  return {
    ndvi_mean_30d:      0.30 + (u(0) / 255) * 0.55,
    ndvi_anomaly:       -0.3 + (u(1) / 255) * 0.6,
    rainfall_30d_mm:    50 + (u(2) / 255) * 250,
    rainfall_anomaly:   -0.4 + (u(3) / 255) * 0.8,
    soil_quality_index: 0.30 + (u(4) / 255) * 0.55,
    historical_yield_mean_t_ha:
      Math.max(0.5, (CROP_REFERENCE_MAX[crop] ?? 4) * (0.35 + (u(5) / 255) * 0.45)),
    days_to_harvest:    30 + (u(6) % 120),
  };
}


export default function YieldForecastPanel() {
  const { activeTenantId } = useTenant();
  const [headlineResult, setHeadlineResult] = useState<YieldPredictionData | null>(null);
  const [headlineError, setHeadlineError] = useState<string | null>(null);

  const listQuery = useYieldForecasts({ tenantId: activeTenantId, limit: 30 });
  const predictMutation = usePredictYield(activeTenantId);

  // Most recent forecast per crop, derived client-side from the list.
  const latestByCrop = useMemo<Map<string, YieldForecastRow>>(() => {
    const map = new Map<string, YieldForecastRow>();
    for (const f of (listQuery.data?.forecasts ?? [])) {
      if (!map.has(f.crop)) map.set(f.crop, f);
    }
    return map;
  }, [listQuery.data]);

  async function runPrediction(crop: string) {
    setHeadlineError(null);
    setHeadlineResult(null);
    try {
      const features = defaultFeaturesFor(activeTenantId, crop);
      const result = await predictMutation.mutateAsync({
        tenant_id: activeTenantId,
        crop,
        ...features,
        persist: true,
      });
      setHeadlineResult(result);
    } catch (err) {
      setHeadlineError(err instanceof Error ? err.message : 'Prediction failed');
    }
  }

  return (
    <div className="cg-market">
      <div className="cg-section-header">
        Yield Forecasts — 14 staple crops
        <span className="ev-map-meta">
          Random Forest regressor · 8 features · 80% prediction interval
        </span>
      </div>

      {headlineResult && <HeadlineResult result={headlineResult} />}
      {headlineError && (
        <div className="fp-alert-error">{headlineError}</div>
      )}

      <div className="cg-yield-grid">
        {CROPS.map((c) => {
          const latest = latestByCrop.get(c.id);
          const refMax = CROP_REFERENCE_MAX[c.id] ?? 4;
          const fillPct = latest
            ? Math.min(100, Math.round((latest.predicted_yield_t_ha / refMax) * 100))
            : 0;
          const pending = predictMutation.isPending
            && predictMutation.variables?.crop === c.id;
          return (
            <div key={c.id} className="cg-yield-card">
              <div className="cg-yield-head">
                <span className="cg-yield-label">{c.label}</span>
                <span className="cg-yield-max">max {refMax.toFixed(1)} t/ha</span>
              </div>
              <div className="cg-yield-val">
                {latest ? fmtYield(latest.predicted_yield_t_ha) : '—'}
              </div>
              <div className="cg-yield-bar">
                <div
                  className={`cg-yield-bar-fill ${
                    latest && latest.requires_human_review
                      ? 'cg-yield-bar-fill--review'
                      : ''
                  }`}
                  style={{ width: `${fillPct}%` }}
                />
              </div>
              <div className="cg-yield-sub">
                {latest ? (
                  <>
                    {latest.yield_pi_low_t_ha != null && latest.yield_pi_high_t_ha != null
                      ? `${latest.yield_pi_low_t_ha.toFixed(1)}–${latest.yield_pi_high_t_ha.toFixed(1)} t/ha · `
                      : ''}
                    <span className={`cg-band cg-band-${latest.confidence_band.toLowerCase()}`}>
                      {latest.confidence_band}
                    </span>
                    {latest.requires_human_review && (
                      <span className="cg-review-flag"> · ⚑</span>
                    )}
                  </>
                ) : (
                  <span className="cg-yield-empty">no forecast yet</span>
                )}
              </div>
              <button
                type="button"
                className="cg-yield-btn"
                onClick={() => runPrediction(c.id)}
                disabled={predictMutation.isPending}
              >
                {pending ? 'Running…' : latest ? 'Re-run' : 'Run forecast'}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}


function HeadlineResult({ result }: { result: YieldPredictionData }) {
  const topDrivers = Object.entries(result.shap_values)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, 3);
  return (
    <div className="cg-result">
      <div className="cg-result-header">
        <div>
          <div className="cg-result-class">
            {CROP_LABEL[result.crop] ?? result.crop} ·{' '}
            {fmtYield(result.predicted_yield_t_ha)}
          </div>
          <div className="cg-result-sub">
            {result.yield_pi_low_t_ha != null && result.yield_pi_high_t_ha != null
              ? `80% PI: ${result.yield_pi_low_t_ha.toFixed(2)}–${result.yield_pi_high_t_ha.toFixed(2)} t/ha · `
              : ''}
            Confidence: {Math.round(result.confidence * 100)}% ·{' '}
            <span className={`cg-band cg-band-${result.confidence_band.toLowerCase()}`}>
              {result.confidence_band}
            </span>
            {result.requires_human_review && (
              <span className="cg-review-flag"> · ⚑ Human review required</span>
            )}
          </div>
        </div>
        <div className="cg-result-score cg-result-score--ok">
          {Math.round(result.prediction * 100)}
          <span className="cg-result-score-unit">/100</span>
        </div>
      </div>

      <div className="cg-topk-list">
        {topDrivers.map(([feature, value]) => {
          const direction = value >= 0 ? 'pulls yield up' : 'pulls yield down';
          return (
            <div key={feature} className="cg-topk-row">
              <span className="cg-topk-rank">·</span>
              <span className="cg-topk-name">
                {feature} <span className="cg-yield-driver-dir">({direction})</span>
              </span>
              <span className="cg-topk-pct">
                {value >= 0 ? '+' : ''}{value.toFixed(3)}
              </span>
            </div>
          );
        })}
      </div>

      <div className="cg-result-footnote">
        {result.model_name} {result.model_version} · {result.inference_time_ms} ms
        {result.persisted ? ' · saved to yield log' : ' · dry run'}
      </div>
    </div>
  );
}
