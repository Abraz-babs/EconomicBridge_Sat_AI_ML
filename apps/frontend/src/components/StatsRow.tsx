'use client';

import { useRole } from '@/context/RoleContext';
import { useOverviewStats } from '@/hooks/useOverviewStats';

/**
 * Top KPI cards on the overview. Driven by the LIVE cross-tenant aggregate
 * (/api/v1/overview/stats) — every number traces to a real row (LGAs from
 * geoBoundaries, settlements from VIIRS+WorldPop, crop detections from the
 * trained ResNet). If the endpoint is unreachable the cards say so — they
 * never fall back to typed-in figures (the old persona stats were invented).
 */
export default function StatsRow() {
  const { accentColor } = useRole();
  const { data, isError } = useOverviewStats();

  const cards =
    data && !isError
      ? data.cards.map((c) => ({
          label: c.label,
          val: c.value,
          delta: c.subtitle,
          dc: c.tone,
        }))
      : [{
          label: 'Platform figures',
          val: '—',
          delta: isError ? 'Could not reach the live figures — try Refresh' : 'Loading live figures…',
          dc: '',
        }];

  return (
    <div className="stats-row anim a2">
      {cards.map((s, i) => (
        <div key={i} className="stat-card" style={{ borderTop: `2px solid ${accentColor}` }}>
          <div className="stat-label">{s.label}</div>
          <div className="stat-value">{s.val}</div>
          <div className={`stat-delta ${s.dc}`}>{s.delta}</div>
        </div>
      ))}
    </div>
  );
}
