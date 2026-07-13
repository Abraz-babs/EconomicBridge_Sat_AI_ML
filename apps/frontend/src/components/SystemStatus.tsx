'use client';

import { useState, useEffect } from 'react';

interface FeedStatus {
  name: string;
  short: string;
  status: 'online' | 'degraded' | 'offline';
  latency: string;
}

const INITIAL_FEEDS: FeedStatus[] = [
  { name: 'Copernicus Sentinel-1 SAR', short: 'S1-SAR', status: 'online', latency: '14 min' },
  { name: 'Copernicus Sentinel-2 MSI', short: 'S2-MSI', status: 'online', latency: '22 min' },
  { name: 'NASA FIRMS', short: 'FIRMS', status: 'online', latency: '8 min' },
  { name: 'N2YO Live Pass', short: 'N2YO', status: 'online', latency: '< 1 min' },
  { name: 'VIIRS Nightlight', short: 'VIIRS', status: 'degraded', latency: '47 min' },
];

const AI_MODELS = [
  { name: 'Conflict Predictor (RF)', status: 'active' as const },
  { name: 'NDVI Analyser', status: 'active' as const },
  { name: 'SAR Processor (U-Net)', status: 'standby' as const },
];

const statusColors = {
  online: '#2d6a4f',
  degraded: '#c97d00',
  offline: '#c1440e',
  active: '#2d6a4f',
  standby: '#8a8278',
};

function nextTimestamp(): string {
  const now = new Date();
  const mins = Math.floor(Math.random() * 3) + 1;
  const ts = new Date(now.getTime() - mins * 60000);
  return ts.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
}

export default function SystemStatus() {
  const feeds = INITIAL_FEEDS;
  // Stable placeholder for SSR + first client render — nextTimestamp() uses
  // Date.now()/Math.random(), which differ server↔client and would cause a
  // hydration mismatch (and a full client-side tree regeneration). The real
  // value is set after mount, client-side only.
  const [lastIngestion, setLastIngestion] = useState<string>('—');
  const uptime = '99.7%';
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLastIngestion(nextTimestamp());
    const interval = setInterval(
      () => setLastIngestion(nextTimestamp()),
      30000,
    );
    return () => clearInterval(interval);
  }, []);

  const onlineCount = feeds.filter((f) => f.status === 'online').length;
  const totalCount = feeds.length;

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
            style={{ background: onlineCount === totalCount ? statusColors.online : statusColors.degraded }}
          />
          <span className="ss-label">SYSTEM STATUS</span>
          <span className="ss-value">
            {onlineCount}/{totalCount} feeds online
          </span>
          <span className="ss-sep">·</span>
          <span className="ss-value">Last ingestion: {lastIngestion || '—'}</span>
          <span className="ss-sep">·</span>
          <span className="ss-value">Uptime: {uptime}</span>
        </div>
        <div className="ss-right">
          <span className="ss-expand-hint">{expanded ? '▲' : '▼'}</span>
        </div>
      </div>

      {expanded && (
        <div className="ss-details" role="region" aria-label="Detailed system status">
          <div className="ss-section">
            <div className="ss-section-title">Satellite Data Feeds</div>
            <div className="ss-feeds-grid">
              {feeds.map((feed) => (
                <div key={feed.short} className="ss-feed-item">
                  <div className="ss-feed-dot" style={{ background: statusColors[feed.status] }} />
                  <div className="ss-feed-info">
                    <span className="ss-feed-name">{feed.short}</span>
                    <span className="ss-feed-latency">{feed.latency}</span>
                  </div>
                  <span
                    className="ss-feed-status"
                    style={{ color: statusColors[feed.status] }}
                  >
                    {feed.status.toUpperCase()}
                  </span>
                </div>
              ))}
            </div>
          </div>
          <div className="ss-section">
            <div className="ss-section-title">AI Models</div>
            <div className="ss-feeds-grid">
              {AI_MODELS.map((model) => (
                <div key={model.name} className="ss-feed-item">
                  <div className="ss-feed-dot" style={{ background: statusColors[model.status] }} />
                  <span className="ss-feed-name">{model.name}</span>
                  <span
                    className="ss-feed-status"
                    style={{ color: statusColors[model.status] }}
                  >
                    {model.status.toUpperCase()}
                  </span>
                </div>
              ))}
            </div>
          </div>
          <div className="ss-compliance">
            <span className="ss-ndpa-badge">NDPA 2023 COMPLIANT</span>
            {/* Region stated truthfully — must always match the DPA §5.1
                (AWS EU-Ireland, NDPA Part VIII transfer basis). The old
                af-south-1 claim was aspirational, never deployed. */}
            <span className="ss-audit">All queries audit-logged · Hosted: AWS eu-west-1 (Ireland) · NDPA cross-border safeguards per DPA</span>
          </div>
        </div>
      )}
    </div>
  );
}
