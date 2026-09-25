import { describe, expect, it } from 'vitest';

import { formatLatLon, sourceBadge } from './display';

describe('sourceBadge — the LIVE / DEMO chip on every panel header', () => {
  it('says LOADING and API UNREACHABLE before it says anything about data', () => {
    expect(sourceBadge(['iati_v1'], { loading: true }).label).toBe('LOADING');
    expect(sourceBadge(['iati_v1'], { error: true }).label).toBe('API UNREACHABLE');
  });

  it('says NO DATA when there are no sources', () => {
    expect(sourceBadge([]).label).toBe('NO DATA');
    expect(sourceBadge(undefined).label).toBe('NO DATA');
  });

  it('never calls seed fixtures LIVE', () => {
    const b = sourceBadge(['seed_v1']);
    expect(b.label.startsWith('DEMO')).toBe(true);
    expect(b.cls).toBe('cg-mode-untuned');
  });

  it('is LIVE when at least one real source is present', () => {
    expect(sourceBadge(['iati_v1']).label).toBe('LIVE · iati_v1');
    expect(sourceBadge(['seed_v1', 'worldbank_v1']).label.startsWith('LIVE')).toBe(true);
  });
});

describe('formatLatLon — hemispheres', () => {
  it('labels Nigeria north and east', () => {
    expect(formatLatLon(12.45, 4.2)).toBe('12.4500°N, 4.2000°E');
  });

  it('labels Senegal west, not east', () => {
    expect(formatLatLon(14.589, -16.1266)).toBe('14.5890°N, 16.1266°W');
  });

  it('respects the requested precision', () => {
    expect(formatLatLon(-1.5, 2.25, 1)).toBe('1.5°S, 2.3°E');
  });
});
