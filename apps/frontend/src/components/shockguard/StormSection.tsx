'use client';

import { useStorms, type StormRow } from '@/hooks/useShockGuard';


/** Storms reconstructed from half-hourly rainfall.
 *
 *  WHY THIS EXISTS
 *  Abuja flooded on 2026-08-30/31 and the platform said nothing. The daily
 *  rainfall product accumulates over a calendar day in UTC; the storm ran
 *  21:00-00:30 WAT and was split across two granules that each looked
 *  ordinary. This reports storms as storms.
 *
 *  WHAT IT MUST NOT SAY
 *  Not a flood forecast. Whether rain floods a place depends on drainage,
 *  soil saturation and how much ground is concrete - none of which we
 *  observe. Every label here is about what fell, never about what flooded.
 *
 *  PRESENTATION
 *  Renders as rows INSIDE the existing alerts column, using the panel's own
 *  fp-alert-* classes. It is a second view of that column, not a new block on
 *  the dashboard: the layout it sits in is not ours to change.
 */

function fmtMm(v: number | null | undefined): string {
  return v == null ? '—' : `${v.toFixed(1)} mm`;
}

function fmtRate(v: number | null | undefined): string {
  return v == null ? '—' : `${v.toFixed(1)} mm/hr`;
}

function fmtDur(h: number | null): string {
  if (h == null) return '—';
  if (h < 1) return `${Math.round(h * 60)} min`;
  return `${h.toFixed(1)} h`;
}

/** UTC instant as local wall-clock - the reader is on the ground, and a storm
 *  reported at 23:30 when they remember 00:30 reads as the wrong storm. */
function fmtWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  });
}

/** 1st / 2nd / 3rd / 4th, with the 11-13 exception. Rendering "92th" in front
 *  of a government client undermines every number beside it. */
function ordinal(n: number): string {
  const v = Math.round(n);
  const rem100 = v % 100;
  if (rem100 >= 11 && rem100 <= 13) return `${v}th`;
  switch (v % 10) {
    case 1: return `${v}st`;
    case 2: return `${v}nd`;
    case 3: return `${v}rd`;
    default: return `${v}th`;
  }
}

/** A rank is meaningless without the sample behind it. A 99th percentile over
 *  21 days is a statement about three weeks, and it must read that way. */
function rankPhrase(s: StormRow): string | null {
  const pct = s.percentile_1h ?? s.percentile_3h;
  if (pct == null || !s.baseline_days) return null;
  return `${ordinal(pct)} pctile of ${s.baseline_days}d`;
}

function sevClass(s: string | null): string {
  const map: Record<string, string> = {
    critical: 'fp-sev-crit', high: 'fp-sev-high',
    medium: 'fp-sev-med', low: 'fp-sev-med',
  };
  return `fp-sev ${map[s ?? 'low'] ?? 'fp-sev-med'}`;
}


export default function StormSection({ tenantId }: { tenantId: string }) {
  const q = useStorms({ tenantId, limit: 12 });
  const d = q.data;

  if (q.isLoading) {
    return <div className="fp-alert-empty">Loading storm intensity…</div>;
  }
  if (q.isError || !d) {
    return <div className="fp-alert-error">Storm feed unavailable.</div>;
  }

  const partialCoverage = d.knownLgas > 0 && d.rateableLgas < d.knownLgas;

  return (
    <>
      {d.storms.map((s) => {
        const rank = rankPhrase(s);
        return (
          <div key={s.id} className="fp-alert-item">
            <div className="fp-alert-top">
              <span className="fp-alert-location">
                🌧 STORM · {s.lga}
              </span>
              {s.severity && (
                <span className={sevClass(s.severity)}>
                  {s.severity.charAt(0).toUpperCase() + s.severity.slice(1)}
                </span>
              )}
            </div>
            <div className="fp-alert-desc">
              peak {fmtRate(s.peak_mm_hr)} · 1h {fmtMm(s.max_1h_mm)} · 3h{' '}
              {fmtMm(s.max_3h_mm)} · over {fmtDur(s.duration_h)}
              {/* The single most informative flag here: a storm a calendar-day
                  total would have cut in half. */}
              {s.crosses_midnight_utc && (
                <>
                  {' '}· ran through midnight UTC, which a daily total would
                  have split in two
                </>
              )}
            </div>
            <div className="fp-alert-meta">
              <span>GPM IMERG half-hourly</span>
              {rank && <span>{rank}</span>}
              <span>{fmtWhen(s.started_at)}</span>
            </div>
          </div>
        );
      })}

      {d.storms.length === 0 && (
        /* An empty list is a finding only if we say what was looked at. */
        <div className="fp-alert-empty">
          {d.measuredLgaCount > 0 ? (
            <>
              Scanned {d.measuredLgaCount}{' '}
              {d.measuredLgaCount === 1 ? 'area' : 'areas'} with rain
              {d.measuredDay ? ` on ${d.measuredDay}` : ''} — nothing reached
              this location&rsquo;s own alerting threshold.
            </>
          ) : d.lastScanAt ? (
            <>
              Scanned{d.measuredDay ? ` on ${d.measuredDay}` : ''} — no
              measurable rain anywhere in this territory.
            </>
          ) : (
            <>Not yet scanned. This is not a report of calm weather.</>
          )}
        </div>
      )}

      {/* Coverage and limits, stated once at the foot of the column rather
          than as a banner sitting above the data. */}
      <div
        className="fp-alert-empty"
        style={{ borderTop: '1px solid var(--border)' }}
      >
        {partialCoverage && (
          <>
            {d.baselineDays} days of archive · {d.rateableLgas} of{' '}
            {d.knownLgas} areas rankable. An area becomes rankable after{' '}
            {d.minBaselineDays} days with measurable rain of its own; drier
            districts take longer. Storms elsewhere are still measured and
            stored.{' '}
          </>
        )}
        Measures rainfall, not flooding — drainage, ground saturation and paved
        area are not observed. Averaged over ~11 km, so local downpours read
        lower than a gauge would record. Severity is limited by record depth.
      </div>
    </>
  );
}
