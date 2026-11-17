'use client';

/**
 * The day strip above the forecast map. ECMWF steps through valid times with a
 * slider; this is a strip you can read at a glance — each day shows the
 * highest LGA value on the current layer — and it plays.
 */

import { useEffect } from 'react';

import type { ForecastArea } from '@/hooks/useForecast';
import { DAYS, CHANCE_DAYS, dayMonth, layerValue, mm, weekday, type DaySel, type LayerId } from './forecastModel';

const BAR: Record<string, string> = { ifs: '#4f8fd6', aifs: '#b27ae6', p10: '#2aa1a8', heat: '#f08a4b' };
const PLAY_MS = 1000;

export default function ForecastRibbon({ areas, days, todayIso, layer, day, onDay, playing, onPlaying, unit }: {
  areas: ForecastArea[]; days: string[]; todayIso: string; layer: LayerId; day: DaySel;
  onDay: (d: DaySel) => void; playing: boolean; onPlaying: (p: boolean) => void; unit: string;
}) {
  const L: LayerId = layer === 'agree' ? 'ifs' : layer;

  useEffect(() => {
    if (!playing) return undefined;
    const t = setInterval(() => {
      const next = day + 1;
      if (next >= DAYS) { onPlaying(false); onDay(-1); } else onDay(next);
    }, PLAY_MS);
    return () => clearInterval(t);
  }, [playing, day, onDay, onPlaying]);

  const highest = (d: DaySel): number | null => {
    const vs = areas.map((a) => layerValue(a, L, d)).filter((v): v is number => v !== null);
    return vs.length ? Math.max(...vs) : null;
  };
  const vals = days.slice(0, DAYS).map((_, d) => highest(d));
  const top = Math.max(1, ...vals.filter((v): v is number => v !== null));
  const text = (v: number | null): string => {
    if (v === null) return '—';
    if (L === 'ifs' || L === 'aifs') return v < 1 ? 'dry' : `${mm(v)} mm`;
    if (L === 'p10') return `${v}%`;
    return `${Math.round(v)}°`;
  };
  const pct = (v: number | null): number => {
    if (v === null) return 0;
    if (L === 'heat') return Math.max(4, ((v - 20) / 22) * 100);
    return Math.max(v > 0 ? 4 : 0, (v / top) * 100);
  };
  const total = highest(-1);
  const totalText = total === null ? '—'
    : L === 'ifs' || L === 'aifs' ? (total < 1 ? 'dry everywhere' : `up to ${mm(total)} mm`)
      : L === 'p10' ? `best ${total}%` : `up to ${Math.round(total)} °C`;

  return (
    <>
      <div className="fc-ribbon-wrap">
        <button
          type="button"
          className="fc-play"
          aria-label={playing ? 'Pause' : 'Play through the days'}
          onClick={() => { if (!playing && (day < 0 || day >= DAYS - 1)) onDay(0); onPlaying(!playing); }}
        >
          {playing ? '❚❚' : '▶'}
        </button>
        <div className="fc-ribbon" role="group" aria-label="Forecast day">
          <button type="button" className="fc-day fc-day--total" aria-pressed={day === -1} onClick={() => { onPlaying(false); onDay(-1); }}>
            <span className="fc-day-w">{L === 'heat' ? 'Next 6 days' : 'Next 10 days'}</span>
            <span className="fc-day-d">{L === 'p10' ? 'Best day' : L === 'heat' ? 'Hottest' : 'Total'}</span>
            <span className="fc-day-v">{totalText}</span>
          </button>
          {days.slice(0, DAYS).map((d, i) => (
            <button
              key={d}
              type="button"
              className={`fc-day${i >= CHANCE_DAYS ? ' is-outlook' : ''}`}
              aria-pressed={day === i}
              onClick={() => { onPlaying(false); onDay(i); }}
            >
              <span className="fc-day-w">{weekday(d, todayIso)}</span>
              <span className="fc-day-d">{dayMonth(d)}</span>
              <span className="fc-day-bar"><i style={{ width: `${pct(vals[i])}%`, background: BAR[L] }} /></span>
              <span className="fc-day-v">{text(vals[i])}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="fc-ribbon-note">
        <span>Bars: the highest {unit} value each day · {L === 'heat' ? 'afternoon temperature' : L === 'p10' ? 'chance of 10 mm+' : 'rain'}</span>
        <span>Hatched days 11–15: outlook, lower skill</span>
      </div>
    </>
  );
}
