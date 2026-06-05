'use client';

import { useState } from 'react';

import { useTenant } from '@/context/TenantContext';
import {
  useCropPriceCorrelation,
  useCropPriceSeries,
  type CropPricePoint,
} from '@/hooks/useCropPrices';


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


// Crop prices are stored in NGN/kg. For ECOWAS tenants (Senegal, Ghana) we show
// USD instead of Naira (indicative conversion — the regional series is shared).
const NGN_PER_USD = 1600;

function fmtMoney(n: number | null | undefined, isEcowas: boolean): string {
  if (n == null) return '—';
  if (isEcowas) {
    const usd = n / NGN_PER_USD;
    if (usd >= 1000) return `$${(usd / 1000).toFixed(1)}K`;
    if (usd >= 100) return `$${usd.toFixed(0)}`;
    return `$${usd.toFixed(2)}`; // small per-kg prices, e.g. $0.38
  }
  if (n >= 1_000_000) return `₦${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `₦${(n / 1_000).toFixed(1)}K`;
  return `₦${n.toFixed(0)}`;
}

function fmtPctSigned(n: number | null | undefined): string {
  if (n == null) return '—';
  const sign = n >= 0 ? '+' : '';
  return `${sign}${n.toFixed(1)}%`;
}


export default function CropMarketPanel() {
  const { activeTenantId, activeTenant } = useTenant();
  const isEcowas = activeTenant.type === 'ecowas_country';
  const [selectedCrop, setSelectedCrop] = useState<string>('maize');

  const seriesQuery = useCropPriceSeries({
    tenantId: activeTenantId, crop: selectedCrop, months: 24,
  });
  const corrQuery = useCropPriceCorrelation({
    tenantId: activeTenantId, months: 24,
  });

  const series = seriesQuery.data;
  const corr = corrQuery.data;

  return (
    <div className="cg-market">
      <div className="cg-section-header">
        Market Price Intelligence — 14 staple crops
        <span className="ev-map-meta">
          Sources: NBS Food Price Watch · FAOSTAT · AMIS
        </span>
      </div>

      {/* CROP PICKER */}
      <div className="cg-crop-picker">
        {CROPS.map((c) => (
          <button
            key={c.id}
            type="button"
            className={`cg-crop-chip ${selectedCrop === c.id ? 'is-active' : ''}`}
            onClick={() => setSelectedCrop(c.id)}
          >
            {c.label}
          </button>
        ))}
      </div>

      <div className="cg-market-row">
        {/* PRICE CHART */}
        <div className="cg-chart-card">
          <div className="cg-chart-head">
            <div>
              <div className="cg-chart-title">{CROP_LABEL[selectedCrop]} · {isEcowas ? 'USD' : 'NGN'} / kg</div>
              <div className="cg-chart-sub">
                {series ? (
                  <>
                    Latest {fmtMoney(series.latest_price, isEcowas)} ·{' '}
                    24-mo change{' '}
                    <span
                      className={
                        (series.pct_change ?? 0) >= 0
                          ? 'cg-pct-up'
                          : 'cg-pct-down'
                      }
                    >
                      {fmtPctSigned(series.pct_change)}
                    </span>
                  </>
                ) : seriesQuery.isLoading
                  ? 'Loading prices…'
                  : seriesQuery.isError
                  ? `Could not load: ${seriesQuery.error?.message ?? 'unknown'}`
                  : '—'}
              </div>
            </div>
          </div>
          {series && series.points.length > 0 && (
            <PriceLineChart points={series.points} isEcowas={isEcowas} />
          )}
          {series && series.points.length === 0 && (
            <div className="fp-alert-empty">
              No price data for {CROP_LABEL[selectedCrop]} in this region. Run{' '}
              <code>python -m scripts.seed_crop_prices</code> from{' '}
              <code>apps/api/</code> to populate seed data, or wait for the
              NBS / FAOSTAT ingestion to land.
            </div>
          )}
        </div>

        {/* CORRELATION HEATMAP */}
        <div className="cg-chart-card">
          <div className="cg-chart-head">
            <div>
              <div className="cg-chart-title">Co-movement matrix</div>
              <div className="cg-chart-sub">
                Pearson r on monthly log-returns · diversification guide
              </div>
            </div>
          </div>
          {corr ? (
            <CorrelationHeatmap data={corr} highlight={selectedCrop} />
          ) : corrQuery.isLoading ? (
            <div className="fp-alert-empty">Loading correlation matrix…</div>
          ) : corrQuery.isError ? (
            <div className="fp-alert-error">
              Could not load: {corrQuery.error?.message ?? 'unknown'}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}


// ─── SVG line chart ──────────────────────────────────────────────────────


function PriceLineChart({ points, isEcowas }: { points: CropPricePoint[]; isEcowas: boolean }) {
  const w = 560;
  const h = 220;
  const padL = 56;
  const padR = 12;
  const padT = 14;
  const padB = 32;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;

  const prices = points.map((p) => p.price_ngn_per_kg);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const range = max - min || 1;

  const xStep = points.length > 1 ? plotW / (points.length - 1) : 0;

  const pathD = points
    .map((p, i) => {
      const x = padL + i * xStep;
      const y = padT + plotH - ((p.price_ngn_per_kg - min) / range) * plotH;
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  const areaD =
    `${pathD} L${(padL + (points.length - 1) * xStep).toFixed(1)},${padT + plotH} ` +
    `L${padL.toFixed(1)},${padT + plotH} Z`;

  const yTicks = 4;
  const tickVals = Array.from({ length: yTicks + 1 }, (_, i) => min + (range * i) / yTicks);

  // Pick ~6 x-axis labels evenly across the range.
  const xLabels = points
    .map((p, i) => ({ p, i }))
    .filter(
      ({ i }) =>
        points.length <= 6 || i % Math.ceil(points.length / 6) === 0,
    );

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      width="100%"
      height={h}
      role="img"
      aria-label="Crop price time series"
    >
      {/* Y gridlines + labels */}
      {tickVals.map((v, i) => {
        const y = padT + plotH - ((v - min) / range) * plotH;
        return (
          <g key={i}>
            <line
              x1={padL} x2={w - padR} y1={y} y2={y}
              stroke="var(--border)" strokeDasharray="2 4"
            />
            <text
              x={padL - 6} y={y + 3}
              fontSize="10" fill="var(--muted)" textAnchor="end"
            >
              {fmtMoney(v, isEcowas)}
            </text>
          </g>
        );
      })}

      {/* Area + line */}
      <path d={areaD} fill="rgba(82, 183, 136, 0.18)" />
      <path d={pathD} stroke="var(--ngo)" strokeWidth="2" fill="none" />

      {/* Last point dot */}
      {points.length > 0 && (() => {
        const last = points[points.length - 1];
        const x = padL + (points.length - 1) * xStep;
        const y = padT + plotH - ((last.price_ngn_per_kg - min) / range) * plotH;
        return <circle cx={x} cy={y} r="4" fill="var(--ngo)" stroke="white" strokeWidth="1.5" />;
      })()}

      {/* X-axis labels */}
      {xLabels.map(({ p, i }) => {
        const x = padL + i * xStep;
        const d = new Date(p.observed_at);
        const label = d.toLocaleDateString('en-GB', { month: 'short', year: '2-digit' });
        return (
          <text
            key={i}
            x={x} y={h - padB + 16}
            fontSize="10" fill="var(--muted)" textAnchor="middle"
          >
            {label}
          </text>
        );
      })}
    </svg>
  );
}


// ─── Correlation heatmap ─────────────────────────────────────────────────


function CorrelationHeatmap({
  data,
  highlight,
}: {
  data: { crops: string[]; matrix: number[][] };
  highlight: string;
}) {
  const n = data.crops.length;
  if (n === 0) return null;

  const cell = 22;
  const labelW = 80;
  const labelH = 80;
  const w = labelW + n * cell + 8;
  const h = labelH + n * cell + 8;

  function colour(r: number): string {
    // r in [-1, 1]: red (neg) → white (0) → green (pos)
    const clamped = Math.max(-1, Math.min(1, r));
    if (clamped >= 0) {
      const t = clamped;
      return `rgba(45, 106, 79, ${0.10 + t * 0.85})`;
    }
    const t = -clamped;
    return `rgba(224, 90, 43, ${0.10 + t * 0.85})`;
  }

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      width="100%"
      role="img"
      aria-label="Crop price correlation matrix"
    >
      {/* Column labels (rotated) */}
      {data.crops.map((c, j) => {
        const x = labelW + j * cell + cell / 2;
        return (
          <text
            key={c}
            x={x} y={labelH - 6}
            fontSize="9"
            fill={c === highlight ? 'var(--ink)' : 'var(--muted)'}
            fontWeight={c === highlight ? 700 : 400}
            textAnchor="start"
            transform={`rotate(-55, ${x}, ${labelH - 6})`}
          >
            {CROP_LABEL[c] ?? c}
          </text>
        );
      })}

      {/* Row labels + heatmap cells */}
      {data.crops.map((c, i) => (
        <g key={c}>
          <text
            x={labelW - 4} y={labelH + i * cell + cell / 2 + 3}
            fontSize="9"
            fill={c === highlight ? 'var(--ink)' : 'var(--muted)'}
            fontWeight={c === highlight ? 700 : 400}
            textAnchor="end"
          >
            {CROP_LABEL[c] ?? c}
          </text>
          {data.crops.map((c2, j) => {
            const r = data.matrix[i]?.[j] ?? 0;
            return (
              <g key={c2}>
                <rect
                  x={labelW + j * cell}
                  y={labelH + i * cell}
                  width={cell - 1.5}
                  height={cell - 1.5}
                  fill={colour(r)}
                  stroke={
                    c === highlight || c2 === highlight
                      ? 'var(--ink)' : 'transparent'
                  }
                  strokeWidth={c === highlight || c2 === highlight ? 1 : 0}
                />
                <title>{`${CROP_LABEL[c] ?? c} × ${CROP_LABEL[c2] ?? c2}: r=${r.toFixed(2)}`}</title>
              </g>
            );
          })}
        </g>
      ))}
    </svg>
  );
}
