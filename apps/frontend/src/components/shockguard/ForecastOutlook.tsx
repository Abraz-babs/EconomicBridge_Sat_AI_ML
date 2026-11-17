'use client';

/**
 * The 15-day outlook for one LGA — our answer to ECMWF's ensemble meteogram.
 * Rain from both models as paired bars, the ensemble's chances as a ladder
 * (1, 10, 25, 50 mm+), and the dawn-to-afternoon temperature range. Days
 * 11-15 are hatched: a single-run outlook with lower skill.
 */

import type { ForecastArea } from '@/hooks/useForecast';
import { band, CHANCE, CHANCE_DAYS, DAYS, dayMonth, mm, readingHours, summary, TEMP_DAYS, weekday } from './forecastModel';

const LADDER: { key: 'chance_1mm' | 'chance_10mm' | 'chance_25mm' | 'chance_50mm'; label: string; sub: string }[] = [
  { key: 'chance_1mm', label: '1 mm+', sub: 'a wet day' },
  { key: 'chance_10mm', label: '10 mm+', sub: 'a soaking day' },
  { key: 'chance_25mm', label: '25 mm+', sub: 'heavy' },
  { key: 'chance_50mm', label: '50 mm+', sub: 'very heavy' },
];
const BAR_PX = 92;
const TEMP_H = 104;
const TEMP_PAD = 16;

export default function ForecastOutlook({ area, days, todayIso, tenantId, stateLabel }: {
  area: ForecastArea; days: string[]; todayIso: string; tenantId: string; stateLabel: string;
}) {
  const hours = readingHours(tenantId);
  const top = Math.max(5, ...area.rain_ifs_mm, ...(area.rain_aifs_mm ?? []));
  const cls = (d: number) => `og-c${d >= CHANCE_DAYS ? ' is-outlook' : ''}`;
  const tmin = area.temp_dawn_c ?? [];
  const tmax = area.temp_afternoon_c ?? [];
  const lo = tmin.length ? Math.floor(Math.min(...tmin)) - 2 : 0;
  const hi = tmax.length ? Math.ceil(Math.max(...tmax)) + 2 : 1;
  const y = (c: number) => TEMP_PAD + (1 - (c - lo) / (hi - lo)) * (TEMP_H - 2 * TEMP_PAD);

  return (
    <div className="fc-outlook" id="fc-outlook">
      <div className="fc-outlook-head">
        <div>
          <h3 className="sgr-h2">15-day outlook</h3>
          <div className="fc-outlook-title">{area.lga} · {stateLabel}</div>
        </div>
        <div className="fc-key" aria-hidden="true">
          <span><i style={{ background: '#4f8fd6' }} />Physics model (IFS)</span>
          <span><i style={{ background: '#b27ae6' }} />AI model (AIFS)</span>
          <span><i style={{ background: '#2aa1a8' }} />Ensemble chance</span>
        </div>
      </div>
      <p className="fc-outlook-sum">{summary(area, days, todayIso)}</p>
      <div className="og-scroll">
        <div className="og" role="table" aria-label={`15-day outlook for ${area.lga}`}>
          <div className="og-lab" />
          {days.slice(0, DAYS).map((d, i) => (
            <div key={d} className={`og-h ${cls(i)}${d === todayIso ? ' is-today' : ''}`}>{weekday(d, todayIso)}<b>{dayMonth(d)}</b></div>
          ))}

          <div className="og-lab"><b>Rain, mm</b>physics · AI<br />scale to {mm(top)} mm</div>
          {days.slice(0, DAYS).map((d, i) => {
            const ifs = area.rain_ifs_mm[i] ?? 0;
            const ai = area.rain_aifs_mm?.[i];
            const dry = ifs < 0.05 && (ai ?? 0) < 0.05;
            return (
              <div key={d} className={`${cls(i)} og-rain`}>
                {dry ? <em className="dry">·</em> : (
                  <em><span className="og-ifs">{mm(ifs)}</span><br /><span className="og-ai">{ai == null ? '—' : mm(ai)}</span></em>
                )}
                <i className="ifs" style={{ height: `${Math.max(ifs > 0.05 ? 2 : 0, (ifs / top) * BAR_PX)}px` }} title={`Physics ${mm(ifs)} mm`} />
                {ai != null && <i className="aifs" style={{ height: `${Math.max(ai > 0.05 ? 2 : 0, (ai / top) * BAR_PX)}px` }} title={`AI ${mm(ai)} mm`} />}
              </div>
            );
          })}

          {LADDER.map((row) => (
            <Ladder key={row.key} label={row.label} sub={row.sub} values={area[row.key]} days={days} cls={cls} />
          ))}

          <div className="og-lab"><b>Temperature, °C</b>{hours.afternoon} ↑ · {hours.dawn} ↓<br />first 6 days</div>
          {days.slice(0, DAYS).map((d, i) => (
            <div key={d} className={`${cls(i)} og-t`}>
              {i < TEMP_DAYS && tmax[i] != null && tmin[i] != null ? (
                <>
                  <span className="hi" style={{ top: `${y(tmax[i]) - 14}px` }}>{Math.round(tmax[i])}°</span>
                  <span className="rng" style={{ top: `${y(tmax[i])}px`, height: `${Math.max(2, y(tmin[i]) - y(tmax[i]))}px` }} />
                  <span className="lo" style={{ top: `${y(tmin[i]) + 2}px` }}>{Math.round(tmin[i])}°</span>
                </>
              ) : <span className="na">—</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Ladder({ label, sub, values, days, cls }: {
  label: string; sub: string; values: number[] | null; days: string[]; cls: (d: number) => string;
}) {
  return (
    <>
      <div className="og-lab"><b>Chance of {label}</b>{sub}</div>
      {days.slice(0, DAYS).map((d, i) => {
        const p = i < CHANCE_DAYS ? values?.[i] : undefined;
        if (p == null) return <div key={d} className={`${cls(i)} og-p na`}>—</div>;
        const c = band(CHANCE, p);
        return (
          <div key={d} className={`${cls(i)} og-p`} style={c ? { background: c, color: p >= 75 ? '#0d141b' : '#e8eef3' } : undefined}>
            {p > 0 ? `${p}%` : '0'}
          </div>
        );
      })}
    </>
  );
}
