'use client';

import { useEffect, useRef, useState, type RefObject } from 'react';

import { useTenant } from '@/context/TenantContext';
import { NGN_PER_USD } from '@/lib/currency';
import {
  useAllCropPriceSeries,
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
// NGN_PER_USD is the single shared market rate (see lib/currency).

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


/** Width of an element, kept current as it resizes — so a chart can draw to
 *  its card instead of a fixed 560 units centred in a wider box. */
function useWidth<T extends HTMLElement>(): [RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

/** Publisher names, not our ingest ids (fews_market_v1 → FEWS NET). */
const sourceName = (src: string) =>
  /fews/i.test(src) ? 'FEWS NET' : /nbs/i.test(src) ? 'NBS' : /wb|world.?bank/i.test(src) ? 'World Bank' : src;

const monthYear = (iso: string) =>
  new Date(iso).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' });


export default function CropMarketPanel() {
  const { activeTenantId, activeTenant } = useTenant();
  const isEcowas = activeTenant.type === 'ecowas_country';
  const [selectedCrop, setSelectedCrop] = useState<string>('maize');
  const [chartRef, chartW] = useWidth<HTMLDivElement>();

  const seriesQuery = useCropPriceSeries({
    tenantId: activeTenantId, crop: selectedCrop, months: 24,
  });

  const series = seriesQuery.data;

  // Every crop a public source publishes for this state, beside the chart.
  const all = useAllCropPriceSeries(activeTenantId, CROPS.map((c) => c.id), 24);
  const allLoading = all.some((q) => q.isLoading);
  const glance = CROPS.flatMap((c, i) => {
    const d = all[i]?.data;
    if (!d || d.points.length === 0) return [];
    const last = d.points[d.points.length - 1];
    return [{ id: c.id, label: c.label, latest: d.latest_price, change: d.pct_change, at: last.observed_at, source: last.source }];
  });

  return (
    <div className="cg-market">
      <div className="cg-section-header">
        Market Price Intelligence — retail prices, NGN per kg
        {/* Name only what we actually read. FAOSTAT and AMIS were never
            wired; claiming them made the panel look better sourced than it
            was. NBS is listed as historical because its Selected Food Prices
            Watch has not been published since Oct 2024. */}
        <span className="ev-map-meta">
          Sources: FEWS NET market prices · NBS Food Price Watch (to Oct
          2024) · every price shown with its date
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
        <div className="cg-chart-card" ref={chartRef}>
          <div className="cg-chart-head">
            <div>
              <div className="cg-chart-title">{CROP_LABEL[selectedCrop]} · {isEcowas ? 'USD' : 'NGN'} / kg</div>
              <div className="cg-chart-sub">
                {series ? (
                  <>
                    Last published {fmtMoney(series.latest_price, isEcowas)}
                    {series.points.length > 0 && (
                      <> in {new Date(series.points[series.points.length - 1].observed_at)
                        .toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })}</>
                    )} ·{' '}
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
            <PriceLineChart points={series.points} isEcowas={isEcowas} width={chartW} />
          )}
          {series && series.points.length === 0 && (
            /* Was: "run the seed script". That advice is now wrong — seeded
               prices are deliberately not served, because a fabricated series
               beside a real one is indistinguishable. State the actual reason
               instead: nobody currently publishes this market. */
            <div className="fp-alert-empty">
              <strong>No current price series for {CROP_LABEL[selectedCrop]} here.</strong>
              <br />
              {isEcowas ? (
                <>
                  The market sources connected to the platform — FEWS NET and
                  NBS — publish Nigerian markets only. No source publishing
                  {' '}{activeTenant.name}&apos;s market prices is connected yet.
                </>
              ) : (
                <>
                  We show only prices a public source actually publishes for this
                  state. FEWS NET collects retail prices in Zamfara; it stopped
                  collecting in Kebbi and Kaduna in January 2025, and does not
                  cover Niger, Benue, Plateau, Nasarawa or the FCT. NBS&apos;s
                  Selected Food Prices Watch has not been published since October
                  2024.
                </>
              )}
              <br />
              An empty chart here means no one is publishing — not that
              prices are unchanged.
            </div>
          )}
        </div>

        {/* EVERY CROP AT A GLANCE — the question the chart raises next: what
            about the other crops? Only published prices, each with its date. */}
        <div className="cg-chart-card cg-glance">
          <div className="cg-chart-head">
            <div className="cg-chart-title">Every crop at a glance</div>
            <div className="cg-chart-sub">Last published price per kg, with its date — click a crop for its chart</div>
          </div>
          {glance.length > 0 ? (
            <table className="ev-lga-table cg-glance-table">
              <thead>
                <tr><th>Crop</th><th className="is-num">Last price</th><th>Published</th><th className="is-num">Change, 24 mo</th><th>Source</th></tr>
              </thead>
              <tbody>
                {glance.map((g) => (
                  <tr
                    key={g.id}
                    className={g.id === selectedCrop ? 'is-sel' : ''}
                    onClick={() => setSelectedCrop(g.id)}
                    tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelectedCrop(g.id); } }}
                  >
                    <td>{g.label}</td>
                    <td className="is-num">{fmtMoney(g.latest, isEcowas)}</td>
                    <td>{monthYear(g.at)}</td>
                    <td className={`is-num ${(g.change ?? 0) >= 0 ? 'cg-pct-up' : 'cg-pct-down'}`}>{fmtPctSigned(g.change)}</td>
                    <td>{sourceName(g.source)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="fp-alert-empty">
              {allLoading ? 'Reading every crop…' : `No crop has a published price series for ${activeTenant.name}.`}
            </div>
          )}
          {glance.length > 0 && (
            <div className="cg-glance-foot">
              {glance.length} of {CROPS.length} crops have a published series here · a series that has stopped keeps its last date
            </div>
          )}
        </div>
      </div>
    </div>
  );
}


// ─── SVG line chart ──────────────────────────────────────────────────────


function PriceLineChart({ points, isEcowas, width }: { points: CropPricePoint[]; isEcowas: boolean; width: number }) {
  // Draw to the card's measured content width, so the chart fills it.
  const w = width > 0 ? Math.max(320, width) : 560;
  const h = 220;
  const padL = 56;
  const padR = 26;   // room for the last month label, centred on the end point
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
