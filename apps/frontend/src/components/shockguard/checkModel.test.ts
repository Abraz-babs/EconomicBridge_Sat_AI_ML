import { describe, expect, it } from 'vitest';

import type { CheckDayArea, ForecastCheck } from '@/hooks/useForecastCheck';
import {
  agreed, brierSkill, calibration, caught, confirmed, daySentence, headline, heavyCaught, heldFrom, leadChip, leadLabel,
  outcome, signed, totalBias, typicalMiss,
} from './checkModel';

function area(over: Partial<CheckDayArea> = {}): CheckDayArea {
  return {
    lga: 'Tarkwa Nsuaem', location: null, measured_mm: 30.1, measured_max_mm: 37.5, wet_share_1mm: 1, wet_share_10mm: 0.9,
    ifs_mm: Array(15).fill(null), aifs_mm: Array(15).fill(null),
    chance_1mm: Array(10).fill(null), chance_10mm: Array(10).fill(null),
    ...over,
  };
}

// [hits, false alarms, misses, correct dry, forecast mm, measured mm, abs err, wet pairs, heavy x4]
const C = [60, 40, 15, 85, 900, 600, 300, 115, 10, 5, 10, 175];

describe('outcomes', () => {
  it('splits a day four ways at 1 mm', () => {
    expect(outcome(5, 3)).toBe('hit');
    expect(outcome(0.4, 12)).toBe('miss');
    expect(outcome(2, 0.2)).toBe('false');
    expect(outcome(0, 0.9)).toBe('dry');
  });
  it('leaves a missing run missing, never dry', () => {
    expect(outcome(null, 12)).toBeNull();
  });
});

describe('ratios keep their sample', () => {
  it('caught, confirmed and agreed come from the counts', () => {
    expect(caught(C)).toEqual({ pct: 80, num: 60, den: 75 });
    expect(confirmed(C)).toEqual({ pct: 60, num: 60, den: 100 });
    expect(agreed(C)).toEqual({ pct: 52, num: 60, den: 115 });
    expect(heavyCaught(C)).toEqual({ pct: 50, num: 10, den: 20 });
  });
  it('an empty sample is no number at all, not 0%', () => {
    expect(caught([0, 0, 0, 10, 0, 0, 0, 0]).pct).toBeNull();
  });
  it('totals and typical miss', () => {
    expect(totalBias(C)).toBe(50);
    expect(signed(totalBias(C))).toBe('+50%');
    expect(signed(-12)).toBe('−12%');
    expect(typicalMiss(C)).toBeCloseTo(300 / 115);
  });
});

describe('leads', () => {
  it('reads as days before the day', () => {
    expect(leadLabel(0)).toBe('the same morning');
    expect(leadLabel(1)).toBe('the day before');
    expect(leadLabel(7)).toBe('7 days before');
    expect(leadChip(0)).toBe('Same morning');
    expect(leadChip(5)).toBe('5');
  });
  it('finds how far ahead rain was held without a break', () => {
    const a = area({ ifs_mm: [20, 18, 9, 3, 0.2, 6, ...Array(9).fill(0)] });
    expect(heldFrom(a, 'ifs')).toBe(3);
    expect(heldFrom(area({ ifs_mm: [0.1, ...Array(14).fill(5)] }), 'ifs')).toBe(-1);
  });
});

describe('sentences', () => {
  it('says measured by satellites and never "accuracy"', () => {
    const a = area({ ifs_mm: [25, 12, 10, ...Array(12).fill(0)] });
    const s = daySentence(a, 'ifs', 1, '2026-11-16');
    expect(s).toContain('NASA’s satellites measured 30 mm');
    expect(s).toContain('rain called and confirmed, under by 18 mm');
    expect(s).toContain('Every run from 2 days before onwards had rain here.');
    expect(s.toLowerCase()).not.toContain('accura');
  });
  it('a missed day and a missing run read plainly', () => {
    expect(daySentence(area({ ifs_mm: [0, 0.3, ...Array(13).fill(0)] }), 'ifs', 1, '2026-11-16')).toContain('the rain was not forecast');
    expect(daySentence(area(), 'aifs', 3, '2026-11-16')).toContain('No AI model run from 3 days before is stored');
  });
  it('the headline needs enough rain days to speak', () => {
    const s = { first_day: '2026-05-01', scorecard: { all: { ifs: [C, C] } } } as unknown as ForecastCheck;
    expect(headline('Ghana', s)).toBe(
      'A day ahead, ECMWF’s physics model caught 80% of the rain days NASA’s satellites measured over Ghana since 1 May, ' +
      'and the satellites confirmed 60% of its rain calls.');
    const thin = { first_day: '2026-11-17', scorecard: { all: { ifs: [C, [1, 0, 2, 9]] } } } as unknown as ForecastCheck;
    expect(headline('Kebbi', thin)).toContain('Too few rain days');
  });
});

describe('ensemble chances', () => {
  it('draws only bins with enough pairs and averages them', () => {
    const ch = { brier: [[100, 0.1, 0.2], [0, null, null]], bins: { '0-2': [[5, 25, 1], [40, 800, 8], [0, 0, 0]] } };
    const pts = calibration(ch, '0-2', [0, 10, 30, 50]);
    expect(pts).toHaveLength(1);
    expect(pts[0]).toMatchObject({ lo: 10, hi: 30, n: 40, said: 20, got: 20 });
    expect(brierSkill(ch)).toEqual([0.5, null]);
  });
});
