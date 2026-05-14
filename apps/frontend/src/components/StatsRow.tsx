'use client';

import { useRole } from '@/context/RoleContext';

export default function StatsRow() {
  const { roleConfig, accentColor } = useRole();

  return (
    <div className="stats-row anim a2">
      {roleConfig.stats.map((s, i) => (
        <div key={i} className="stat-card" style={{ borderTop: `2px solid ${accentColor}` }}>
          <div className="stat-label">{s.label}</div>
          <div className="stat-value">{s.val}</div>
          <div className={`stat-delta ${s.dc}`}>{s.delta}</div>
        </div>
      ))}
    </div>
  );
}
