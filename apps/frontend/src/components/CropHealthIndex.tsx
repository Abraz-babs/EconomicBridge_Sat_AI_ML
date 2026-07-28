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
 * Live crop-health index — % of each region's LGAs whose current Sentinel-2
 * NDVI reads healthy, mixed across Nigerian states + Ghana + Senegal (never
 * off-plan countries). Rotates through the pool over time.
 *
 * Reads the per-LGA SATELLITE layer, not the leaf-photo diagnosis table. The
 * old subtitle said "ResNet-50 + modelled", which was accurate about the
 * mechanism and misleading about the evidence: it was 59 photo rows, 50 of
 * them seeded. The row label now carries its own sample size, so a reader can
 * see what each percentage rests on.
 */
export default function CropHealthIndex() {
  const { data, isLoading, isError } = useCropHealth();
  const rows = useRotatingWindow(data ?? [], 5);

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Crop Health Index</span>
        <span className="panel-meta">
          {isError ? 'API unreachable' : 'Sentinel-2 NDVI · per LGA'}
        </span>
      </div>
      <div>
        {isLoading && <div className="feed-item feed-item--empty">Loading…</div>}
        {!isLoading && rows.length === 0 && (
          <div className="feed-item feed-item--empty">
            No region has enough current LGA readings to index yet.
          </div>
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
