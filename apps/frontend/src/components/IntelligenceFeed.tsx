'use client';

import {
  useIntelligenceFeed,
  type FeedEvent,
  type FeedSeverity,
  type FeedTag,
} from '@/hooks/useIntelligenceFeed';


const TAG_CLASS: Record<FeedTag, string> = {
  Disaster: 'tag-d',
  Agriculture: 'tag-a',
  Poverty: 'tag-p',
  Aid: 'tag-p',
  Encroachment: 'tag-d',
};

const SEVERITY_DOT_CLASS: Record<FeedSeverity, string> = {
  critical: 'feed-dot--critical',
  high: 'feed-dot--high',
  medium: 'feed-dot--medium',
  low: 'feed-dot--low',
};


function fmtAge(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return 'just now';
  const min = Math.round(ms / 60_000);
  if (min < 60) return `${min} min ago`;
  const hr = Math.round(min / 60);
  if (hr < 48) return `${hr}h ago`;
  return `${Math.round(hr / 24)} d ago`;
}


export default function IntelligenceFeed() {
  const query = useIntelligenceFeed({ limit: 20 });
  const events: FeedEvent[] = query.data?.events ?? [];
  const status = query.isError ? 'API unreachable'
    : query.isFetching ? 'Live · refreshing…'
    : 'Live · 60s refresh';

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Intelligence Feed</span>
        <span className="panel-meta">{status}</span>
      </div>
      <div className="feed-scroll">
        {query.isLoading && (
          <div className="feed-item feed-item--empty">Loading feed…</div>
        )}
        {!query.isLoading && events.length === 0 && (
          <div className="feed-item feed-item--empty">
            No platform activity in the last 90 days. Run a module scan and
            persist it to populate the feed.
          </div>
        )}
        {events.map((ev, i) => (
          <div key={`${ev.kind}-${ev.observed_at}-${i}`} className="feed-item">
            <div className={`feed-dot ${SEVERITY_DOT_CLASS[ev.severity]}`} />
            <div>
              <div className="feed-text">{ev.title}</div>
              <div className="feed-sub">
                <span className={`tag ${TAG_CLASS[ev.tag]}`}>{ev.tag}</span>
                <span className="feed-source">
                  {ev.tenant_id} · {ev.source}
                </span>
                <span>{fmtAge(ev.observed_at)}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
