'use client';

import {
  useIntelligenceFeed,
  type FeedEvent,
} from '@/hooks/useIntelligenceFeed';


/**
 * Top-of-page alert ribbon. Pulls the most-recent high/critical event
 * from the unified intelligence feed; falls back to a quiet "no active
 * events" line when nothing is severe enough to surface. Replaces the
 * v0.3 hardcoded Borno-flood ribbon.
 */
export default function AlertBar() {
  const { data, isLoading, isError } = useIntelligenceFeed({
    limit: 30,
    refetchIntervalMs: 60_000,
  });

  if (isLoading) {
    return <div className="alert-bar anim a1">Loading platform alerts…</div>;
  }
  if (isError) {
    return (
      <div className="alert-bar anim a1">
        ⚠ Alert feed unreachable — backend offline or unauthenticated.
      </div>
    );
  }

  const top = pickTop(data?.events ?? []);
  if (!top) {
    return (
      <div className="alert-bar alert-bar--quiet anim a1">
        ✓ No critical events flagged across pilot tenants in the last 90 days.
      </div>
    );
  }

  return (
    <div className="alert-bar anim a1">
      ⚠ <strong>{labelFor(top)}:</strong> {top.title}
      {' · '}
      {top.tenant_id} · {top.source}
    </div>
  );
}


function pickTop(events: FeedEvent[]): FeedEvent | null {
  // Prefer critical, then high. Within a severity tier, prefer Disaster /
  // Encroachment tags (operationally louder) and the most recent timestamp.
  const ranked = events
    .filter((e) => e.severity === 'critical' || e.severity === 'high')
    .sort((a, b) => {
      const sevRank = (e: FeedEvent) => (e.severity === 'critical' ? 0 : 1);
      if (sevRank(a) !== sevRank(b)) return sevRank(a) - sevRank(b);
      const tagRank = (e: FeedEvent) =>
        e.tag === 'Disaster' || e.tag === 'Encroachment' ? 0 : 1;
      if (tagRank(a) !== tagRank(b)) return tagRank(a) - tagRank(b);
      return b.observed_at.localeCompare(a.observed_at);
    });
  return ranked[0] ?? null;
}


function labelFor(ev: FeedEvent): string {
  if (ev.severity === 'critical') return 'CRITICAL';
  if (ev.tag === 'Disaster') return 'ACTIVE';
  if (ev.tag === 'Encroachment') return 'ENCROACHMENT';
  return 'ALERT';
}
