'use client';

/**
 * Footer status bar — read from the feeds, never typed in.
 *
 * Until 2026-09-29 this listed five feeds with fixed latencies, a "last
 * ingestion" time made up with Math.random(), "Uptime: 99.7%" and three "AI
 * models" with statuses nobody set. Now every monitored feed reports its real
 * last successful run and whether that is within its own cadence (the same
 * budgets the feed watchdog enforces — apps/api/services/feed_health.py), and
 * the last ingestion is the newest successful run. Uptime is not measured, so
 * it is not shown; the API check is a real round trip from this browser.
 */

import { useEffect, useState } from 'react';

import { useSystemStatus, type FeedState } from '@/hooks/useOverviewLive';
import { apiFetch } from '@/lib/api';

const statusColors = { current: '#2d6a4f', late: '#c97d00', never: '#8a8278', down: '#c1440e' };

function ago(iso: string | null, now: number): string {
  if (!iso) return 'never';
  const mins = Math.max(0, Math.round((now - Date.parse(iso)) / 60_000));
  if (mins < 60) return `${mins} min ago`;
  const h = Math.round(mins / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} days ago`;
}

function cadence(f: FeedState): string {
  return f.max_age_hours > 24 * 7 ? 'monthly' : 'daily';
}

function utc(iso: string | null): string {
  return iso ? `${iso.replace('T', ' ').slice(0, 16)} UTC` : '—';
}

export default function SystemStatus() {
  const status = useSystemStatus();
  const [expanded, setExpanded] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [api, setApi] = useState<{ ok: boolean; ms: number } | null>(null);

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      const t0 = performance.now();
      try {
        await apiFetch('/health');
        if (!cancelled) setApi({ ok: true, ms: Math.round(performance.now() - t0) });
      } catch {
        if (!cancelled) setApi({ ok: false, ms: 0 });
      }
      if (!cancelled) setNow(Date.now());
    };
    void check();
    const id = window.setInterval(() => {
      if (document.visibilityState === 'visible') void check();
    }, 60_000);
    return () => { cancelled = true; window.clearInterval(id); };
  }, []);

  const d = status.data;
  const allCurrent = d ? d.current === d.total : false;

  return (
    <div className="system-status" role="status" aria-label="System status indicators">
      <div
        className="ss-summary"
        onClick={() => setExpanded(!expanded)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setExpanded(!expanded); }}
        tabIndex={0}
        role="button"
        aria-expanded={expanded}
        aria-label="Toggle system status details"
      >
        <div className="ss-left">
          <div
            className="ss-indicator"
            style={{ background: !d ? statusColors.never : allCurrent ? statusColors.current : statusColors.late }}
          />
          <span className="ss-label">SYSTEM STATUS</span>
          <span className="ss-value">
            {d ? `${d.current}/${d.total} feeds current` : status.isError ? 'feed status unavailable' : 'reading feed status…'}
          </span>
          <span className="ss-sep">·</span>
          <span className="ss-value">Last ingestion: {utc(d?.last_ingestion_at ?? null)}</span>
          <span className="ss-sep">·</span>
          <span className="ss-value">
            API: {api ? (api.ok ? `responding (${api.ms} ms)` : 'not responding') : 'checking…'}
          </span>
        </div>
        <div className="ss-right">
          <span className="ss-expand-hint">{expanded ? '▲' : '▼'}</span>
        </div>
      </div>

      {expanded && (
        <div className="ss-details" role="region" aria-label="Detailed system status">
          <div className="ss-section">
            <div className="ss-section-title">Data feeds · last successful run</div>
            <div className="ss-feeds-grid">
              {(d?.feeds ?? []).map((f) => {
                const tone = f.current ? statusColors.current
                  : !f.last_success_at ? statusColors.never
                    : f.last_status === 'failed' ? statusColors.down : statusColors.late;
                return (
                  <div key={f.source} className="ss-feed-item">
                    <div className="ss-feed-dot" style={{ background: tone }} />
                    <div className="ss-feed-info">
                      <span className="ss-feed-name">{f.label}</span>
                      <span className="ss-feed-latency">{ago(f.last_success_at, now)} · runs {cadence(f)}</span>
                    </div>
                    <span className="ss-feed-status" style={{ color: tone }}>
                      {f.current ? 'CURRENT' : f.last_success_at ? 'LATE' : 'NOT RUN'}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
          <div className="ss-compliance">
            <span className="ss-ndpa-badge">NDPA 2023</span>
            {/* Region stated truthfully — must always match the DPA §5.1
                (AWS EU-Ireland, NDPA Part VIII transfer basis). */}
            <span className="ss-audit">Requests audit-logged · Hosted: AWS eu-west-1 (Ireland) · NDPA cross-border safeguards per DPA</span>
          </div>
        </div>
      )}
    </div>
  );
}
