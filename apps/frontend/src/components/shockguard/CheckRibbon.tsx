'use client';

/**
 * The strip of checked days above the forecast-check map: the season record
 * first, then the last 30 measured days. Each day's bar is how the LGAs split
 * between rain caught, rain missed and rain forecast that was not measured, for
 * the chosen model and lead. It plays, like the forecast ribbon.
 */

import { useEffect, useRef } from 'react';

import type { CheckDay, CheckModel, Counts } from '@/hooks/useForecastCheck';
import { caught, OUTCOME_COL, pctText } from './checkModel';
import { dayMonth } from './forecastModel';

const PLAY_MS = 1000;

const weekday = (iso: string): string => new Date(`${iso}T12:00:00Z`).toLocaleDateString('en-GB', { timeZone: 'UTC', weekday: 'short' });

export default function CheckRibbon({ days, sel, onSel, model, leadIdx, season, seasonFrom, playing, onPlaying, unit }: {
  days: CheckDay[]; sel: string; onSel: (s: string) => void; model: CheckModel; leadIdx: number;
  season: Counts | null; seasonFrom: string | null; playing: boolean; onPlaying: (p: boolean) => void; unit: string;
}) {
  const strip = useRef<HTMLDivElement>(null);
  const at = days.findIndex((d) => d.day === sel);

  useEffect(() => {
    // Open on the newest day: the strip scrolls, and the right end is "now".
    const el = strip.current;
    if (el) el.scrollLeft = el.scrollWidth;
  }, [days.length]);

  useEffect(() => {
    if (!playing) return undefined;
    const t = setInterval(() => {
      const next = at + 1;
      if (next >= days.length || next <= 0) onPlaying(false);
      else onSel(days[next].day);
    }, PLAY_MS);
    return () => clearInterval(t);
  }, [playing, at, days, onSel, onPlaying]);

  return (
    <>
      <div className="fc-ribbon-wrap">
        <button
          type="button"
          className="fc-play"
          aria-label={playing ? 'Pause' : 'Play through the checked days'}
          onClick={() => { if (!playing && (at < 0 || at >= days.length - 1)) onSel(days[0]?.day ?? sel); onPlaying(!playing); }}
        >
          {playing ? '❚❚' : '▶'}
        </button>
        <div className="fc-ribbon ck-ribbon" role="group" aria-label="Checked day" ref={strip}>
          <button type="button" className="fc-day fc-day--total" aria-pressed={sel === 'season'}
            onClick={() => { onPlaying(false); onSel('season'); }}>
            <span className="fc-day-w">Season record</span>
            <span className="fc-day-d">{seasonFrom ? `since ${dayMonth(seasonFrom)}` : '—'}</span>
            <span className="fc-day-v">{season ? `${pctText(caught(season))} of rain days caught` : '—'}</span>
          </button>
          {days.map((d) => {
            const c = (model === 'ifs' ? d.ifs : d.aifs)[leadIdx] ?? [0, 0, 0, 0];
            const [hit, fa, miss] = c;
            const w = (n: number) => `${(100 * n) / Math.max(1, d.lgas)}%`;
            return (
              <button key={d.day} type="button" className="fc-day" aria-pressed={sel === d.day}
                title={`${dayMonth(d.day)}: ${d.wet} of ${d.lgas} ${unit}s wet by satellite · ${hit} caught · ${miss} missed · ${fa} forecast but not measured`}
                onClick={() => { onPlaying(false); onSel(d.day); }}>
                <span className="fc-day-w">{weekday(d.day)}</span>
                <span className="fc-day-d">{dayMonth(d.day)}</span>
                <span className="fc-day-bar ck-bar">
                  <i style={{ width: w(hit), background: OUTCOME_COL.hit }} />
                  <i style={{ width: w(miss), background: OUTCOME_COL.miss }} />
                  <i style={{ width: w(fa), background: OUTCOME_COL.false }} />
                </span>
                <span className="fc-day-v">{d.wet ? `${d.wet} wet` : 'dry'}</span>
              </button>
            );
          })}
        </div>
      </div>
      <div className="fc-ribbon-note">
        <span>
          Bars: share of {unit}s · <i className="ck-key" style={{ background: OUTCOME_COL.hit }} /> rain caught ·{' '}
          <i className="ck-key" style={{ background: OUTCOME_COL.miss }} /> missed ·{' '}
          <i className="ck-key" style={{ background: OUTCOME_COL.false }} /> forecast, not measured
        </span>
        <span>“wet” = {unit}s with 1 mm+ measured</span>
      </div>
    </>
  );
}
