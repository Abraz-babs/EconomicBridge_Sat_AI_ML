'use client';

import { useCropHealth } from '@/hooks/useOverviewStats';
import { useRotatingWindow } from '@/hooks/useRotatingWindow';

const TONE_COLOR: Record<string, string> = {
  ok: '#52b788',
  warn: '#f4a832',
  neg: '#e05a2b',
  '': '#52b788',
};

/**
 * Live crop-health index — % of detections classified healthy per crop ×
 * region, from the trained ResNet, MIXED across Nigerian states + Ghana +
 * Senegal (never off-plan countries). Rotates through the pool over time.
 */
export default function CropHealthIndex() {
  const { data, isLoading, isError } = useCropHealth();
  const rows = useRotatingWindow(data ?? [], 5);

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Crop Health Index</span>
        <span className="panel-meta">
          {isError ? 'API unreachable' : 'ResNet-50 + modelled · mixed regions'}
        </span>
      </div>
      <div>
        {isLoading && <div className="feed-item feed-item--empty">Loading…</div>}
        {!isLoading && rows.length === 0 && (
          <div className="feed-item feed-item--empty">No crop detections yet.</div>
        )}
        {rows.map((c) => (
          <div key={c.label} className="crop-row">
            <span>{c.label}</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div className="progress-wrap">
                <div
                  className="progress-bar"
                  style={{ width: `${c.pct}%`, background: TONE_COLOR[c.tone] ?? '#52b788' }}
                />
              </div>
              <span style={{ fontSize: '9px', color: 'var(--muted)', width: '26px', textAlign: 'right' }}>
                {c.pct}%
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
