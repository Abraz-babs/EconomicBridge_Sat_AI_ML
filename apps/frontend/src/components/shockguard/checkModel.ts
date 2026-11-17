/**
 * Pure helpers for ShockGuard's forecast check: outcomes, ratios that keep
 * their sample, colours and the plain sentences. No React, no fetching —
 * unit-tested in checkModel.test.ts.
 *
 * Wording rules. IMERG is a satellite estimate, not a rain gauge, so the page
 * says "measured by NASA's satellites" and "confirmed by the satellites" —
 * never "accuracy", "truth" or "wrong". Every percentage carries its sample.
 * A wet day is 1 mm or more of area-average rain, as in the forecast room.
 */

import type { CheckChance, CheckDayArea, CheckModel, Counts, ForecastCheck } from '@/hooks/useForecastCheck';
import { dayMonth, mm, type Scale } from './forecastModel';

export const WET = 1;
export const HEAVY = 10;
/** An LGA with fewer measured rain days than this is shown, not scored. */
export const MIN_RAIN_DAYS = 5;
/** A calibration point needs this many pairs before it is drawn. */
export const MIN_BIN_PAIRS = 30;

export type Outcome = 'hit' | 'miss' | 'false' | 'dry';
export type DayLayer = 'outcome' | 'measured' | 'forecast';

export const OUTCOME_COL: Record<Exclude<Outcome, 'dry'>, string> = { hit: '#2fb5a6', miss: '#f2b54a', false: '#d4607a' };
export const OUTCOME_TEXT: Record<Outcome, string> = {
  hit: 'rain forecast and measured',
  miss: 'rain measured, not forecast',
  false: 'rain forecast, none measured',
  dry: 'dry forecast, dry measured',
};
export const MODEL_LABEL: Record<CheckModel, string> = { ifs: 'Physics model (IFS)', aifs: 'AI model (AIFS)' };
export const MODEL_SHORT: Record<CheckModel, string> = { ifs: 'physics model', aifs: 'AI model' };
export const MODEL_COL: Record<CheckModel, string> = { ifs: '#4f8fd6', aifs: '#b27ae6' };

/** Season layer: on days either side had rain, the share where both did. */
export const AGREE: Scale = { cuts: [0, 20, 35, 50, 65], cols: ['#1b2f3a', '#1d4d57', '#22727a', '#2aa1a8', '#6fe0d0'], unit: '%' };

export const UNIT: Record<string, string> = { ghana: 'district', senegal: 'department' };
export const unitFor = (tenantId: string): string => UNIT[tenantId] ?? 'LGA';

export interface Ratio { pct: number | null; num: number; den: number }

export const ratio = (num: number, den: number): Ratio => ({ pct: den > 0 ? Math.round((100 * num) / den) : null, num, den });
/** Of the rain days the satellites measured, how many the forecast had called. */
export const caught = (c: Counts): Ratio => ratio(c[0], c[0] + c[2]);
/** Of the forecast's rain calls, how many the satellites confirmed. */
export const confirmed = (c: Counts): Ratio => ratio(c[0], c[0] + c[1]);
/** Of the days either side had rain, how many both did (critical success index). */
export const agreed = (c: Counts): Ratio => ratio(c[0], c[0] + c[1] + c[2]);
export const heavyCaught = (c: Counts): Ratio => ratio(c[8] ?? 0, (c[8] ?? 0) + (c[10] ?? 0));
export const heavyConfirmed = (c: Counts): Ratio => ratio(c[8] ?? 0, (c[8] ?? 0) + (c[9] ?? 0));

/** How often rain (1 mm+) fell at all, over the pairs in these counts. The yardstick for
 *  "caught" and "confirmed": a forecast of rain every day catches every rain day and is
 *  confirmed exactly this often. */
export const wetShare = (c: Counts): Ratio => ratio(c[0] + c[2], c[0] + c[1] + c[2] + c[3]);

/** Skill beyond chance: the equitable threat score. Hits are counted only beyond those a
 *  forecast making the same number of rain calls at random would get. 0 = no better than
 *  chance, 1 = perfect. `heavy` scores soaking days (10 mm+). */
export function ets(c: Counts, heavy = false): number | null {
  const [a, b, m, d] = heavy ? [c[8], c[9], c[10], c[11]] : [c[0], c[1], c[2], c[3]];
  if (a === undefined || b === undefined || m === undefined || d === undefined) return null;
  const n = a + b + m + d;
  if (!n) return null;
  const luck = ((a + b) * (a + m)) / n;
  const den = a + b + m - luck;
  return den > 0 ? (a - luck) / den : null;
}

/** Forecast rain total against measured, as a signed percentage. */
export function totalBias(c: Counts): number | null {
  return c[5] > 0 ? Math.round(100 * (c[4] / c[5] - 1)) : null;
}

/** Mean absolute difference in mm on days either side was wet. */
export function typicalMiss(c: Counts): number | null {
  return c[7] > 0 ? c[6] / c[7] : null;
}

export const pctText = (r: Ratio): string => (r.pct === null ? '—' : `${r.pct}%`);
export const signed = (v: number | null): string => (v === null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : '±'}${Math.abs(v)}%`);

export function leadLabel(k: number): string {
  return k === 0 ? 'the same morning' : k === 1 ? 'the day before' : `${k} days before`;
}

/** The lead picker reads "Forecast made [Same morning] [1] [2] … days before". */
export function leadChip(k: number): string {
  return k === 0 ? 'Same morning' : String(k);
}

export function forecastAt(a: CheckDayArea, model: CheckModel, lead: number): number | null {
  const v = (model === 'ifs' ? a.ifs_mm : a.aifs_mm)[lead];
  return v === undefined ? null : v;
}

export function outcome(f: number | null, o: number): Outcome | null {
  if (f === null) return null;
  const fw = f >= WET;
  const ow = o >= WET;
  if (fw && ow) return 'hit';
  if (fw) return 'false';
  return ow ? 'miss' : 'dry';
}

/** How many days ahead the forecast held rain without a break: every run from
 *  k days before up to the same morning called the day wet. -1 if none did. */
export function heldFrom(a: CheckDayArea, model: CheckModel): number {
  const xs = model === 'ifs' ? a.ifs_mm : a.aifs_mm;
  let k = -1;
  for (let j = 0; j < xs.length; j += 1) {
    const v = xs[j];
    if (v === null) continue;
    if (v < WET) break;
    k = j;
  }
  return k;
}

export function lgaCounts(l: { ifs: Counts[]; aifs: Counts[] }, model: CheckModel, leadIdx: number): Counts | null {
  return (model === 'ifs' ? l.ifs : l.aifs)[leadIdx] ?? null;
}

const fmtDay = (iso: string): string =>
  new Date(`${iso}T12:00:00Z`).toLocaleDateString('en-GB', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short' });

/** The header sentence: the physics model, forecasts made the day before, the whole record —
 *  with how often it rained at all beside it, so "caught" cannot read as more than it is. */
export function headline(name: string, unit: string, s: ForecastCheck): string {
  const c = s.scorecard.all?.ifs?.[1];
  if (!c || !s.first_day) return `No forecast has been checked for ${name} yet.`;
  const k = caught(c);
  const f = confirmed(c);
  if (k.den < 20) {
    return `Too few rain days measured over ${name} since ${dayMonth(s.first_day)} to score the forecast yet (${k.den}).`;
  }
  return `Since ${dayMonth(s.first_day)}, a day ahead, ECMWF’s physics model caught ${k.pct}% of ${name}’s measured ` +
    `rain days and ${f.pct}% of its rain calls were confirmed — with rain on ${pctText(wetShare(c))} of ${unit}-days in all.`;
}

/** The deterministic sentence for one area on one day. */
export function daySentence(a: CheckDayArea, model: CheckModel, lead: number, dayIso: string): string {
  const f = forecastAt(a, model, lead);
  const o = a.measured_mm;
  const seen = `NASA’s satellites measured ${mm(o)} mm over ${a.lga} on ${fmtDay(dayIso)}`;
  if (f === null) return `${seen}. No ${MODEL_SHORT[model]} run from ${leadLabel(lead)} is stored for this day.`;
  const who = `the ${MODEL_SHORT[model]}’s forecast from ${leadLabel(lead)} gave ${mm(f)} mm`;
  const held = heldFrom(a, model);
  const lead2 = held >= 2 ? ` Every run from ${held} days before onwards had rain here.` : '';
  switch (outcome(f, o)) {
    case 'hit': {
      const off = Math.abs(f - o) >= 5 ? `, ${f > o ? 'over' : 'under'} by ${mm(Math.abs(f - o))} mm` : '';
      return `${seen}; ${who}: rain called and confirmed${off}.${lead2}`;
    }
    case 'miss':
      return `${seen}; ${who}, under the 1 mm a wet day needs: the rain was not forecast.`;
    case 'false':
      return `${seen}, under 1 mm; ${who}: the rain it forecast was not measured.${lead2}`;
    default:
      return `${seen}; ${who}: a dry day, called dry.`;
  }
}

export interface CalPoint { lo: number; hi: number; n: number; said: number; got: number }

/** Calibration of the ensemble's chances for one lead group: mean chance said
 *  against the mean share of the area that got the rain, per bin. */
export function calibration(ch: CheckChance | undefined, group: string, edges: number[]): CalPoint[] {
  const rows = ch?.bins[group] ?? [];
  return rows
    .map(([n, sumP, sumO], i) => ({ lo: edges[i], hi: Math.min(100, edges[i + 1] ?? 100), n, said: n ? sumP / n : 0, got: n ? (100 * sumO) / n : 0 }))
    .filter((p) => p.n >= MIN_BIN_PAIRS);
}

/** Brier skill against the sample's own base rate, per lead: + is better than always saying the usual share. */
export function brierSkill(ch: CheckChance | undefined): (number | null)[] {
  return (ch?.brier ?? []).map(([n, bs, ref]) => (n && bs !== null && ref ? Math.round(100 * (1 - bs / ref)) / 100 : null));
}
