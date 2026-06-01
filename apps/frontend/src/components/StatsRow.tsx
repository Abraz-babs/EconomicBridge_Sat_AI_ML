'use client';

import { useRole } from '@/context/RoleContext';
import { useOverviewStats } from '@/hooks/useOverviewStats';

/**
 * Top KPI cards on the overview. Driven by the LIVE cross-tenant aggregate
 * (/api/v1/overview/stats) — every number traces to a real row (LGAs from
 * geoBoundaries, settlements from VIIRS+WorldPop, crop detections from the
 * trained ResNet). Falls back to the role's static stats only if the
 * endpoint is unreachable, so the row never renders blank.
 */
export default function StatsRow() {
  const { roleConfig, accentColor } = useRole();
  const { data, isError } = useOverviewStats();

  const cards =
    data && !isError
      ? data.cards.map((c) => ({
          label: c.label,
          val: c.value,
          delta: c.subtitle,
          dc: c.tone,
        }))
      : roleConfig.stats; // graceful fallback

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
