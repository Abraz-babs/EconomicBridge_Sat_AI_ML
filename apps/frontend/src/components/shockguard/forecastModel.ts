/**
 * Pure helpers for ShockGuard's forecast side: bands, per-layer values and the
 * plain sentences. No React, no fetching — unit-tested in forecastModel.test.ts.
 *
 * Wording rules: a forecast, never a measurement; under 1 mm in a day is dry;
 * a missing model stays missing ("not available"), never borrowed.
 */

import type { ForecastArea } from '@/hooks/useForecast';

export const DAYS = 15;
export const CHANCE_DAYS = 10;
export const TEMP_DAYS = 6;
export const TOTAL_DAYS = 10;
export const WET_MM = 1;

export type LayerId = 'ifs' | 'aifs' | 'p10' | 'agree' | 'heat';
/** -1 = the 10-day summary (total, best day or hottest); 0..14 = one day. */
export type DaySel = number;

export interface Scale {
  cuts: number[];
  cols: string[];
  unit: string;
}

// Our own bands — ECMWF's idea of discrete steps, not its colours.
export const RAIN: Scale = { cuts: [1, 5, 10, 25, 50], cols: ['#1f4f7c', '#2f78c0', '#5d63cf', '#a15ed6', '#f2b54a'], unit: 'mm' };
export const CHANCE: Scale = { cuts: [5, 25, 50, 75], cols: ['#16414a', '#1d6b73', '#2aa1a8', '#6fe0d0'], unit: '%' };
export const HEAT: Scale = { cuts: [30, 33, 36, 39], cols: ['#5b3a24', '#94512b', '#d0703a', '#ff6a3d'], unit: '°C' };
export const AGREE_COLS: Record<1 | 2 | 3, string> = { 1: '#f2b54a', 2: '#b27ae6', 3: '#2f78c0' };

export const LAYERS: { id: LayerId; label: string; dot: string }[] = [
  { id: 'ifs', label: 'Rain · physics model (IFS)', dot: '#4f8fd6' },
  { id: 'aifs', label: 'Rain · AI model (AIFS)', dot: '#b27ae6' },
  { id: 'p10', label: 'Chance of 10 mm+', dot: '#2aa1a8' },
  { id: 'agree', label: 'Do the models agree?', dot: '#f2b54a' },
  { id: 'heat', label: 'Afternoon heat', dot: '#f08a4b' },
];

export function band(s: Scale, v: number | null): string | null {
  if (v === null || Number.isNaN(v)) return null;
  let c: string | null = null;
  s.cuts.forEach((cut, i) => { if (v >= cut) c = s.cols[i]; });
  return c;
}

export function hexRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export const sum = (a: number[] | null, n: number): number => (a ?? []).slice(0, n).reduce((s, v) => s + v, 0);
export const maxOf = (a: number[] | null, n = Infinity): number => Math.max(...(a ?? []).slice(0, n), -Infinity);
export function maxAt(a: number[] | null, n: number): number {
  const xs = (a ?? []).slice(0, n);
  return xs.reduce((best, v, i) => (v > xs[best] ? i : best), 0);
}

/** A wet day is 1 mm or more in the day, physics model, next 10 days — the one rule everywhere. */
export const isWet = (a: ForecastArea): boolean => maxOf(a.rain_ifs_mm, TOTAL_DAYS) >= WET_MM;

/** The value one area shows on one layer and day; null = not available that day. */
export function layerValue(a: ForecastArea, layer: LayerId, day: DaySel): number | null {
  if (layer === 'ifs' || layer === 'aifs') {
    const xs = layer === 'ifs' ? a.rain_ifs_mm : a.rain_aifs_mm;
    if (!xs) return null;
    return day < 0 ? sum(xs, TOTAL_DAYS) : xs[day] ?? null;
  }
  if (layer === 'p10') {
    if (!a.chance_10mm || day >= CHANCE_DAYS) return null;
    return day < 0 ? maxOf(a.chance_10mm) : a.chance_10mm[day] ?? null;
  }
  if (layer === 'heat') {
    if (!a.temp_afternoon_c || day >= TEMP_DAYS) return null;
    return day < 0 ? maxOf(a.temp_afternoon_c) : a.temp_afternoon_c[day] ?? null;
  }
  // agree: 0 both dry, 1 physics only, 2 AI only, 3 both have rain
  if (!a.rain_aifs_mm) return null;
  const i = day < 0 ? sum(a.rain_ifs_mm, TOTAL_DAYS) : a.rain_ifs_mm[day];
  const x = day < 0 ? sum(a.rain_aifs_mm, TOTAL_DAYS) : a.rain_aifs_mm[day];
  return (i >= WET_MM ? 1 : 0) + (x >= WET_MM ? 2 : 0);
}

export function layerColour(a: ForecastArea, layer: LayerId, day: DaySel): string | null {
  const v = layerValue(a, layer, day);
  if (v === null) return null;
  if (layer === 'ifs' || layer === 'aifs') return band(RAIN, v);
  if (layer === 'p10') return band(CHANCE, v);
  if (layer === 'heat') return band(HEAT, v);
  return v === 0 ? null : AGREE_COLS[v as 1 | 2 | 3];
}

export function mm(v: number): string {
  if (v >= 10) return String(Math.round(v));
  if (v >= 0.05) return v.toFixed(1);
  return '0';
}

/** Local clock for the 06 and 15 UTC readings: Nigeria is UTC+1, Ghana and Senegal UTC+0. */
export function readingHours(tenantId: string): { afternoon: string; dawn: string } {
  return tenantId === 'ghana' || tenantId === 'senegal'
    ? { afternoon: '3 pm', dawn: '6 am' }
    : { afternoon: '4 pm', dawn: '7 am' };
}

const fmt = (iso: string, opt: Intl.DateTimeFormatOptions): string =>
  new Date(`${iso}T12:00:00Z`).toLocaleDateString('en-GB', { timeZone: 'UTC', ...opt });

export function dayName(iso: string, todayIso: string): string {
  return iso === todayIso ? 'today' : fmt(iso, { weekday: 'short', day: 'numeric', month: 'short' });
}

export const weekday = (iso: string, todayIso: string): string => (iso === todayIso ? 'Today' : fmt(iso, { weekday: 'short' }));
export const dayMonth = (iso: string): string => fmt(iso, { day: 'numeric', month: 'short' });
export const longDay = (iso: string): string => fmt(iso, { weekday: 'long', day: 'numeric', month: 'long' });

/** The deterministic "what this means" sentence for one area. */
export function summary(a: ForecastArea, days: string[], todayIso: string): string {
  const hot = a.temp_afternoon_c ? Math.round(maxOf(a.temp_afternoon_c)) : null;
  const cold = a.temp_dawn_c ? Math.round(Math.min(...a.temp_dawn_c)) : null;
  const tail = hot !== null && cold !== null ? ` Afternoons reach about ${hot} °C and dawns fall to about ${cold} °C.` : '';
  const p1 = a.chance_1mm;
  const p1m = p1 ? maxOf(p1) : null;
  const aiDry = !a.rain_aifs_mm || maxOf(a.rain_aifs_mm, TOTAL_DAYS) < WET_MM;
  if (!isWet(a) && aiDry && (p1m === null || p1m < 10)) {
    const ens = p1m === null ? 'The ensemble chances are not available for this run.'
      : p1m > 0 ? `At most ${p1m}% of the ensemble forecasts expect a wet day.`
        : 'None of the ensemble forecasts expects a wet day.';
    return `${a.lga} looks dry for the next ten days: both models forecast under 1 mm on every day. ${ens}` + tail;
  }
  const ai = a.rain_aifs_mm ? ` and the AI model ${mm(sum(a.rain_aifs_mm, TOTAL_DAYS))} mm` : '';
  const head = `Over ten days the physics model gives ${mm(sum(a.rain_ifs_mm, TOTAL_DAYS))} mm${ai}.`;
  if (!p1 || !a.chance_10mm) return `${head} The ensemble chances are not available for this run.` + tail;
  const d = maxAt(p1, CHANCE_DAYS);
  const p10m = maxOf(a.chance_10mm);
  const soak = p10m >= 50 ? 'likely' : p10m >= 20 ? 'possible' : 'unlikely';
  return `Rain is most likely ${dayName(days[d], todayIso) === 'today' ? 'today' : `on ${dayName(days[d], todayIso)}`}, ` +
    `when ${p1[d]}% of the ensemble expects at least 1 mm. ${head} ` +
    `A soaking day of 10 mm or more is ${soak}: the best chance on any day is ${p10m}%.` + tail;
}

/** The header sentence for a tenant. */
export function headline(name: string, unit: string, areas: ForecastArea[]): string {
  const wet = areas.filter(isWet);
  if (wet.length === 0) return `${name} stays dry for the next ten days: no ${unit} expects even 1 mm of rain.`;
  const top = wet.reduce((b, a) => (sum(a.rain_ifs_mm, TOTAL_DAYS) > sum(b.rain_ifs_mm, TOTAL_DAYS) ? a : b));
  return `Rain reaches ${wet.length} of ${name}’s ${areas.length} ${unit}s in the next ten days; ` +
    `the wettest, ${top.lga}, expects about ${Math.round(sum(top.rain_ifs_mm, TOTAL_DAYS))} mm.`;
}
