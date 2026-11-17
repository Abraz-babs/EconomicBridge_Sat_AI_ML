'use client';

/**
 * The list beside the forecast map. When rain is coming: where, wettest first,
 * with a ten-day spark. When the whole state is dry (half the year), the list
 * still earns its place: the hottest afternoons and coldest dawns.
 */

import type { ForecastArea } from '@/hooks/useForecast';
import { dayName, isWet, maxAt, maxOf, mm, readingHours, sum, TEMP_DAYS, TOTAL_DAYS } from './forecastModel';

const LIST_MAX = 40;

export default function ForecastList({ areas, days, todayIso, selected, onSelect, unit, tenantId }: {
  areas: ForecastArea[]; days: string[]; todayIso: string; selected: string | null;
  onSelect: (lga: string) => void; unit: string; tenantId: string;
}) {
  const wet = areas.filter(isWet).sort((x, y) => sum(y.rain_ifs_mm, TOTAL_DAYS) - sum(x.rain_ifs_mm, TOTAL_DAYS));
  const drizzle = areas.filter((a) => !isWet(a) && sum(a.rain_ifs_mm, TOTAL_DAYS) >= 1).length;
  const hours = readingHours(tenantId);

  if (wet.length) {
    return (
      <div className="sgr-listcol">
        <h3 className="sgr-h2">Where rain is coming</h3>
        <p className="fc-listnote">
          {wet.length} {unit}s with at least one wet day (1 mm+), wettest first · 10-day total from the physics model ·
          bars = each of the next 10 days{drizzle ? ` · ${drizzle} more get only drizzle, under 1 mm a day` : ''}
        </p>
        {wet.slice(0, LIST_MAX).map((a) => {
          const first = a.rain_ifs_mm.findIndex((v) => v >= 1);
          const top = Math.max(1, maxOf(a.rain_ifs_mm, TOTAL_DAYS));
          return (
            <button key={a.lga} type="button" className={`sgr-card ${selected === a.lga ? 'is-on' : ''}`}
              aria-pressed={selected === a.lga} onClick={() => onSelect(a.lga)}>
              <span className="sgr-card-lga">{a.lga}</span>
              <span className="sgr-card-mm">{mm(sum(a.rain_ifs_mm, TOTAL_DAYS))}<small> mm</small></span>
              <span className="sgr-card-body">
                <span className="fc-spark" aria-hidden="true">
                  {a.rain_ifs_mm.slice(0, TOTAL_DAYS).map((v, i) => (
                    <i key={days[i] ?? i} className={v < 1 ? 'dry' : ''} style={{ height: `${Math.max(6, (v / top) * 100)}%` }} />
                  ))}
                </span>
                <span>
                  <span className="sgr-card-strong">{first >= 0 ? `First wet day ${dayName(days[first], todayIso)}` : 'Light rain only'}</span>
                  {a.rain_aifs_mm ? ` · AI model ${mm(sum(a.rain_aifs_mm, TOTAL_DAYS))} mm` : ' · AI model not available'}
                </span>
                {a.chance_1mm && a.chance_10mm && (
                  <span>Chance of a wet day up to {maxOf(a.chance_1mm)}% · of 10 mm+ up to {maxOf(a.chance_10mm)}%</span>
                )}
              </span>
            </button>
          );
        })}
        {wet.length > LIST_MAX && <p className="fc-listnote">{wet.length - LIST_MAX} more {unit}s with lighter rain — click them on the map.</p>}
      </div>
    );
  }

  const hot = areas.filter((a) => a.temp_afternoon_c).sort((x, y) => maxOf(y.temp_afternoon_c) - maxOf(x.temp_afternoon_c));
  return (
    <div className="sgr-listcol">
      <h3 className="sgr-h2">Dry for ten days — hottest afternoons</h3>
      <p className="fc-listnote">
        No {unit} expects a wet day. With rain off the table, heat and cold dawns are what move: ranked by the hottest {hours.afternoon} in the next 6 days.
      </p>
      {hot.map((a) => (
        <button key={a.lga} type="button" className={`sgr-card ${selected === a.lga ? 'is-on' : ''}`}
          aria-pressed={selected === a.lga} onClick={() => onSelect(a.lga)}>
          <span className="sgr-card-lga">{a.lga}</span>
          <span className="sgr-card-mm is-heat">{Math.round(maxOf(a.temp_afternoon_c))}<small> °C</small></span>
          <span className="sgr-card-body">
            <span>
              <span className="sgr-card-strong">Hottest {dayName(days[maxAt(a.temp_afternoon_c, TEMP_DAYS)], todayIso)}</span>
              {a.temp_dawn_c && ` · dawn as low as ${Math.round(Math.min(...a.temp_dawn_c))} °C at ${hours.dawn}`}
            </span>
            <span>
              Rain: {mm(sum(a.rain_ifs_mm, TOTAL_DAYS))} mm physics
              {a.rain_aifs_mm ? ` · ${mm(sum(a.rain_aifs_mm, TOTAL_DAYS))} mm AI` : ''}
              {a.chance_1mm ? ` · wet-day chance ≤ ${maxOf(a.chance_1mm)}%` : ''}
            </span>
          </span>
        </button>
      ))}
    </div>
  );
}
