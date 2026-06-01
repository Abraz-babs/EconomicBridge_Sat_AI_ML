'use client';

import { useActiveResponse } from '@/hooks/useOverviewStats';
import { useRotatingWindow } from '@/hooks/useRotatingWindow';

/**
 * Live active-response events — recent shocks per region (flood/drought),
 * MIXED across Nigerian states + Ghana + Senegal (real persisted rows, never
 * off-plan countries). Rotates through the pool over time.
 */
export default function ActiveResponse() {
  const { data, isLoading, isError } = useActiveResponse();
  const rows = useRotatingWindow(data ?? [], 4);

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Active Response</span>
        <span className="panel-meta">
          {isError ? 'API unreachable' : `${data?.length ?? 0} events · mixed regions`}
        </span>
      </div>
      <div>
        {isLoading && <div className="feed-item feed-item--empty">Loading…</div>}
        {!isLoading && rows.length === 0 && (
          <div className="feed-item feed-item--empty">No active events.</div>
        )}
        {rows.map((e) => (
          <div key={`${e.region}-${e.sub}`} className="event-row">
            <div>
              <div>{e.region}</div>
              <div className="event-sub">{e.sub}</div>
            </div>
            <span className={`status-tag ${e.tone}`}>{e.status}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
