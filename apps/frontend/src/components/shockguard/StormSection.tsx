'use client';

import { useStorms, type StormRow } from '@/hooks/useShockGuard';


/** Storms reconstructed from half-hourly rainfall.
 *
 *  WHY THIS EXISTS
 *  Abuja flooded on 2026-08-30/31 and the platform said nothing. The daily
 *  rainfall product accumulates over a calendar day in UTC; the storm ran
 *  21:00-00:30 WAT and was split across two granules that each looked
 *  ordinary. This section reports storms as storms.
 *
 *  WHAT IT MUST NOT SAY
 *  Not a flood forecast. Whether rain floods a place depends on drainage,
 *  soil saturation and how much ground is concrete - none of which we
 *  observe. Every label here is about what fell, never about what flooded.
 */

const SEV_TONE: Record<string, string> = {
  critical: '#ef4444', high: '#f97316', medium: '#eab308', low: '#94a3b8',
};

const MUTED = 'var(--text-secondary, #94a3b8)';

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

/** A rank is meaningless without the sample behind it. A 99th percentile over
 *  21 days is a statement about three weeks, and it must read that way. */
function rankPhrase(s: StormRow): string | null {
  const pct = s.percentile_1h ?? s.percentile_3h;
  if (pct == null || !s.baseline_days) return null;
  return `${pct.toFixed(0)}th percentile of ${s.baseline_days} days recorded here`;
}


export default function StormSection({ tenantId }: { tenantId: string }) {
  const q = useStorms({ tenantId, limit: 8 });
  const d = q.data;

  if (q.isLoading) {
    return <div className="fp-empty">Loading storm intensity...</div>;
  }
  if (q.isError || !d) return null;

  // Coverage is governed by PER-PLACE history, not by how many calendar days
  // of archive we hold. A place records a day only when rain fell there, so a
  // dry district can sit on 4 days of its own record while the archive holds
  // 29. Reporting the archive figure alone would read as "record complete"
  // while most of the territory was still unrankable.
  const partialCoverage = d.knownLgas > 0 && d.rateableLgas < d.knownLgas;
  const partial = d.measured.filter(
    (m) => m.slices_seen > 0 && m.slices_seen < m.slices_expected,
  ).length;

  return (
    <section style={{ margin: '18px 0 6px' }}>
      <div
        style={{
          display: 'flex', alignItems: 'baseline',
          justifyContent: 'space-between',
          gap: '10px', flexWrap: 'wrap', marginBottom: '8px',
        }}
      >
        <h3 style={{ fontSize: '14px', margin: 0, letterSpacing: '0.02em' }}>
          Storm intensity
        </h3>
        <span style={{ fontSize: '11.5px', color: MUTED }}>
          GPM IMERG half-hourly &middot; rolling 1h/3h totals, not calendar days
        </span>
      </div>

      {/* The record has to be deep enough before a rank means anything. Say so
          rather than rendering an empty list that reads as "no storms". */}
      {partialCoverage && (
        <div
          style={{
            padding: '9px 12px', borderRadius: '6px', fontSize: '12.5px',
            background: 'rgba(148,163,184,0.10)',
            border: '1px solid rgba(148,163,184,0.35)',
            color: MUTED, marginBottom: '10px',
          }}
        >
          <strong>Building the local record</strong>
          {' · '}
          {d.baselineDays} days of archive.{' '}
          <strong>{d.rateableLgas}</strong> of {d.knownLgas} areas can be
          ranked so far. An area becomes rankable once it has{' '}
          {d.minBaselineDays} days with measurable rain of its own to be
          judged against, which takes longer in drier districts. Storms
          elsewhere are still measured and stored, just not ranked.
        </div>
      )}

      {d.storms.length > 0 ? (
        <div style={{ display: 'grid', gap: '7px' }}>
          {d.storms.map((s) => {
            const tone = SEV_TONE[s.severity ?? 'low'] ?? '#94a3b8';
            const rank = rankPhrase(s);
            return (
              <div
                key={s.id}
                style={{
                  padding: '10px 12px', borderRadius: '6px',
                  fontSize: '12.5px',
                  background: `${tone}14`, border: `1px solid ${tone}4D`,
                }}
              >
                <div
                  style={{
                    display: 'flex', gap: '8px', alignItems: 'center',
                    flexWrap: 'wrap',
                  }}
                >
                  <span
                    aria-hidden
                    style={{
                      width: '8px', height: '8px', borderRadius: '50%',
                      background: tone, flexShrink: 0,
                    }}
                  />
                  <strong>{s.lga}</strong>
                  {s.severity && (
                    <span
                      style={{
                        color: tone, textTransform: 'uppercase',
                        fontSize: '10.5px', letterSpacing: '0.06em',
                      }}
                    >
                      {s.severity}
                    </span>
                  )}
                  <span style={{ marginLeft: 'auto', color: MUTED }}>
                    {fmtWhen(s.started_at)}
                  </span>
                </div>
                <div
                  style={{
                    marginTop: '5px', color: MUTED,
                    fontVariantNumeric: 'tabular-nums',
                  }}
                >
                  peak <strong>{fmtRate(s.peak_mm_hr)}</strong>
                  {' · '}1h {fmtMm(s.max_1h_mm)}
                  {' · '}3h {fmtMm(s.max_3h_mm)}
                  {' · '}over {fmtDur(s.duration_h)}
                </div>
                {rank && (
                  <div style={{ marginTop: '3px', color: MUTED }}>{rank}</div>
                )}
                {/* The single most informative flag on this panel: this storm
                    is one a calendar-day total would have cut in half. */}
                {s.crosses_midnight_utc && (
                  <div style={{ marginTop: '3px', color: tone }}>
                    Ran through midnight UTC &mdash; a daily total would have
                    split this storm across two days.
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        /* An empty list is a finding only if we say what was looked at. */
        <div
          style={{
            padding: '10px 12px', borderRadius: '6px', fontSize: '12.5px',
            background: 'rgba(148,163,184,0.08)',
            border: '1px solid rgba(148,163,184,0.25)',
            color: MUTED,
          }}
        >
          {d.measuredLgaCount > 0 ? (
            <>
              Scanned <strong>{d.measuredLgaCount}</strong>{' '}
              {d.measuredLgaCount === 1 ? 'area' : 'areas'} with rain
              {d.measuredDay ? ` on ${d.measuredDay}` : ''} &mdash; nothing
              reached this location&rsquo;s own alerting threshold.
            </>
          ) : d.lastScanAt ? (
            <>
              Scanned{d.measuredDay ? ` on ${d.measuredDay}` : ''} &mdash; no
              measurable rain anywhere in this territory.
            </>
          ) : (
            <>Not yet scanned. This is not a report of calm weather.</>
          )}
        </div>
      )}

      {/* Wettest measured places, shown whether or not anything was rated -
          it is the evidence that the scan reached the ground it claims to. */}
      {d.measured.length > 0 && (
        <details style={{ marginTop: '8px', fontSize: '12px' }}>
          <summary style={{ cursor: 'pointer', color: MUTED }}>
            Wettest areas measured
            {d.measuredDay ? ` · ${d.measuredDay}` : ''}
          </summary>
          <div style={{ display: 'grid', gap: '3px', marginTop: '6px' }}>
            {d.measured.map((m) => (
              <div
                key={`${m.lga}-${m.day}`}
                style={{
                  display: 'flex', gap: '10px', color: MUTED,
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                <span style={{ flex: 1 }}>{m.lga}</span>
                <span>1h {fmtMm(m.max_1h_mm)}</span>
                <span>peak {fmtRate(m.peak_mm_hr)}</span>
              </div>
            ))}
          </div>
          {/* A partly-observed day understates every accumulation on it. */}
          {partial > 0 && (
            <div style={{ marginTop: '6px', color: '#eab308' }}>
              {partial} of these days were only partly observed &mdash; the
              figures above are lower bounds.
            </div>
          )}
        </details>
      )}

      {/* Stated once, plainly, on the panel itself - not left to a footnote. */}
      <p
        style={{
          marginTop: '9px', fontSize: '11.5px', lineHeight: 1.5, color: MUTED,
        }}
      >
        Measures rainfall, not flooding. Whether a storm floods somewhere also
        depends on drainage, ground saturation and paved area, which satellite
        rainfall does not observe. Satellite rainfall averages over roughly
        11&nbsp;km, so intense local downpours read lower than a rain gauge
        would record.
      </p>
    </section>
  );
}
