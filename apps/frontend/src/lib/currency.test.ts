import { describe, expect, it } from 'vitest';

import { fmtMoneyCompact, fmtUsdCompact, formatLocalAndUsd, localCurrencyFor } from './currency';

describe('dual-currency display — USD is the anchor, local currency derived', () => {
  it('shows naira first for Nigeria, with the USD it came from', () => {
    expect(formatLocalAndUsd(750, 'nigeria')).toBe('₦1.20M ($750)');
  });

  it('uses each country\'s own currency', () => {
    expect(formatLocalAndUsd(300, 'ghana')).toBe('GH₵5K ($300)');
    expect(formatLocalAndUsd(800, 'senegal')).toBe('CFA 486K ($800)');
  });

  it('falls back to USD alone for an unknown country, and a dash for no value', () => {
    expect(formatLocalAndUsd(297, 'kenya')).toBe('$297');
    expect(formatLocalAndUsd(null, 'nigeria')).toBe('—');
  });

  it('looks up currencies case-insensitively and tolerates no country', () => {
    expect(localCurrencyFor('Nigeria')?.code).toBe('NGN');
    expect(localCurrencyFor(null)).toBeNull();
  });

  it('compacts at the documented thresholds', () => {
    expect(fmtMoneyCompact(999, '₦')).toBe('₦999');
    expect(fmtMoneyCompact(4_600, 'GH₵')).toBe('GH₵5K');
    expect(fmtUsdCompact(9_999)).toBe('$9,999');
    expect(fmtUsdCompact(12_345)).toBe('$12.3K');
  });
});
