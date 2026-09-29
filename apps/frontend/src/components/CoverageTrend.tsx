'use client';

/**
 * Readings stored per month — from public.ingestion_runs, not typed in.
 *
 * Until 2026-09-29 this panel drew six invented bars ("mapped households /
 * month", OCT–MAR). Now each bar is the number of readings the platform's
 * feeds actually stored that month (satellite passes, fire detections, storms,
 * prices…), with how many runs stored them.
 */

import { useReadingsTrend } from '@/hooks/useOverviewLive';

function monthShort(iso: string): string {
  return new Date(`${iso.slice(0, 10)}T12:00:00Z`).toLocaleDateString('en-GB', { month: 'short' }).toUpperCase();
}

function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}K`;
  return String(n);
}

export default function CoverageTrend() {
  const { data, isLoading, isError } = useReadingsTrend();
  const months = data?.months ?? [];
  const maxV = Math.max(1, ...months.map((m) => m.readings));
  const last = months[months.length - 1];

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Readings Stored</span>
        <span className="panel-meta">All feeds · per month</span>
      </div>
      <div className="bar-chart">
        <div style={{ fontSize: '9px', letterSpacing: '2px', textTransform: 'uppercase', color: 'var(--muted)' }}>
          {isError ? 'Could not load the record' : isLoading ? 'Loading…'
            : last ? `${compact(last.readings)} this month · ${last.runs} runs` : 'No runs recorded'}
        </div>
        <div className="bars">
          {months.map((m, i) => {
            const pct = (m.readings / maxV) * 100;
            const current = i === months.length - 1;
            return (
              <div key={m.month} className="bar-col" title={`${m.readings.toLocaleString('en-US')} readings · ${m.runs} runs`}>
                <div
                  className="bar-block"
                  style={{ height: `${Math.max(pct, m.readings ? 2 : 0)}%`, background: current ? '#2d6a4f' : '#52b788', opacity: 0.7 }}
                />
                <span className="bar-lbl">{monthShort(m.month)}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
