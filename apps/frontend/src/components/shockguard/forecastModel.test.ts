import { describe, expect, it } from 'vitest';

import type { ForecastArea } from '@/hooks/useForecast';
import { band, headline, isWet, layerColour, layerValue, mm, RAIN, readingHours, summary } from './forecastModel';

const DAYS = Array.from({ length: 15 }, (_, i) => new Date(Date.UTC(2026, 10, 17 + i)).toISOString().slice(0, 10));
const TODAY = '2026-11-17';

function area(over: Partial<ForecastArea> = {}): ForecastArea {
  return {
    lga: 'Augie', location: null, cells: 9,
    rain_ifs_mm: Array(15).fill(0), rain_ifs_max_mm: Array(15).fill(0), rain_aifs_mm: Array(15).fill(0),
    chance_1mm: Array(10).fill(0), chance_10mm: Array(10).fill(0), chance_25mm: Array(10).fill(0), chance_50mm: Array(10).fill(0),
    temp_dawn_c: [21, 20.6, 21, 22, 21, 21], temp_afternoon_c: [35, 36.2, 35, 35, 34, 35],
    ...over,
  };
}

describe('bands', () => {
  it('leaves under 1 mm clear: a trace is a dry day', () => {
    expect(band(RAIN, 0.9)).toBeNull();
    expect(band(RAIN, 1)).toBe('#1f4f7c');
    expect(band(RAIN, 55)).toBe('#f2b54a');
  });
});

describe('layer values', () => {
  it('sums ten days for the rain summary and reads one day otherwise', () => {
    const a = area({ rain_ifs_mm: [2, 3, ...Array(13).fill(0)] });
    expect(layerValue(a, 'ifs', -1)).toBe(5);
    expect(layerValue(a, 'ifs', 1)).toBe(3);
  });

  it('says not available past the ensemble’s day 10 and the temperature’s day 6', () => {
    expect(layerValue(area(), 'p10', 11)).toBeNull();
    expect(layerValue(area(), 'heat', 7)).toBeNull();
    expect(layerValue(area(), 'heat', -1)).toBe(36.2);
  });

  it('never borrows the physics model when the AI model is missing', () => {
    const a = area({ rain_aifs_mm: null });
    expect(layerValue(a, 'aifs', -1)).toBeNull();
    expect(layerValue(a, 'agree', -1)).toBeNull();
    expect(layerColour(a, 'aifs', -1)).toBeNull();
  });

  it('reads agreement as both, one or neither', () => {
    const both = area({ rain_ifs_mm: [5, ...Array(14).fill(0)], rain_aifs_mm: [4, ...Array(14).fill(0)] });
    const physicsOnly = area({ rain_ifs_mm: [5, ...Array(14).fill(0)] });
    expect(layerValue(both, 'agree', 0)).toBe(3);
    expect(layerValue(physicsOnly, 'agree', 0)).toBe(1);
    expect(layerValue(area(), 'agree', 0)).toBe(0);
    expect(layerColour(area(), 'agree', 0)).toBeNull();
  });
});

describe('sentences', () => {
  it('calls a dry LGA dry, and says when no ensemble forecast expects rain', () => {
    expect(isWet(area())).toBe(false);
    const s = summary(area(), DAYS, TODAY);
    expect(s).toContain('looks dry for the next ten days');
    expect(s).toContain('None of the ensemble forecasts');
    expect(s).toContain('36 °C');
  });

  it('names the likeliest wet day and grades a soaking day honestly', () => {
    const a = area({
      lga: 'Tarkwa Nsuaem',
      rain_ifs_mm: [3.4, 2.4, 4, 2.2, 4.4, 6.6, 5.7, 2.3, 2.4, 0.9, 3.4, 1.7, 1.6, 0.6, 1.3],
      rain_aifs_mm: Array(15).fill(4),
      chance_1mm: [89, 84, 97, 92, 95, 96, 80, 63, 79, 76],
      chance_10mm: [0, 0, 7, 1, 8, 12, 5, 1, 0, 1],
    });
    const s = summary(a, DAYS, TODAY);
    expect(s).toContain('on Thu 19 Nov, when 97%');
    expect(s).toContain('unlikely: the best chance on any day is 12%');
  });

  it('writes the headline from the one wet-day rule', () => {
    const wet = area({ lga: 'Tarkwa Nsuaem', rain_ifs_mm: [3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 0, 0, 0, 0, 0] });
    const drizzle = area({ lga: 'Bole', rain_ifs_mm: [0.5, 0.5, 0.5, ...Array(12).fill(0)] });
    expect(headline('Ghana', 'district', [wet, drizzle])).toBe(
      'Rain reaches 1 of Ghana’s 2 districts in the next ten days; the wettest, Tarkwa Nsuaem, expects about 30 mm.');
    expect(headline('Kebbi State', 'LGA', [area()])).toContain('stays dry');
  });

  it('formats rain and local reading times', () => {
    expect(mm(34.3)).toBe('34');
    expect(mm(0.4)).toBe('0.4');
    expect(mm(0.01)).toBe('0');
    expect(readingHours('kebbi')).toEqual({ afternoon: '4 pm', dawn: '7 am' });
    expect(readingHours('senegal')).toEqual({ afternoon: '3 pm', dawn: '6 am' });
  });
});
