/**
 * Currency model for the dashboard's dual-currency indicators.
 *
 * USD is the UNIVERSAL ANCHOR: every tenant carries a real USD figure (World
 * Bank GNI-derived, comparable across countries). Each country additionally
 * shows its LOCAL currency, derived from the USD anchor at the market rate
 * below — so the displayed pair is always internally consistent at a
 * real-world rate.
 *
 * Why not use World Bank's local-currency series directly? For Nigeria its
 * official/Atlas rate badly understates the Naira (~₦919/$ vs the ~₦1,600/$
 * market rate), which is what produced the wrong "₦273K ($297)". Anchoring on
 * USD and converting at the market rate keeps every country consistent.
 *
 * To add a country: add ONE entry keyed by its `country` slug (matches
 * Tenant.country). Rates are market mid-rates — update here in one place.
 */
export interface Currency {
  /** ISO 4217 code. */
  code: string;
  /** Display symbol/prefix. */
  symbol: string;
  /** Local-currency units per 1 USD (market mid-rate). */
  perUsd: number;
}

export const LOCAL_CURRENCY: Record<string, Currency> = {
  nigeria: { code: 'NGN', symbol: '₦', perUsd: 1600 },
  ghana: { code: 'GHS', symbol: 'GH₵', perUsd: 15.5 },
  senegal: { code: 'XOF', symbol: 'CFA ', perUsd: 607 },
};

/** Naira per USD — reused by CropGuard market prices (stored in NGN/kg). */
export const NGN_PER_USD = LOCAL_CURRENCY.nigeria.perUsd;

/** Local currency for a tenant's `country` slug, or null (→ show USD only). */
export function localCurrencyFor(country?: string | null): Currency | null {
  if (!country) return null;
  return LOCAL_CURRENCY[country.toLowerCase()] ?? null;
}

/** Compact money with a currency symbol: ₦1.20M / GH₵4.6K / CFA 480K / $297. */
export function fmtMoneyCompact(amount: number, symbol: string): string {
  if (amount >= 1_000_000) return `${symbol}${(amount / 1_000_000).toFixed(2)}M`;
  if (amount >= 1_000) return `${symbol}${Math.round(amount / 1_000)}K`;
  return `${symbol}${Math.round(amount).toLocaleString()}`;
}

/** Compact USD: $1.2K above ten-thousand, else the plain figure ($297). */
export function fmtUsdCompact(usd: number): string {
  if (usd >= 10_000) return `$${(usd / 1_000).toFixed(1)}K`;
  return `$${Math.round(usd).toLocaleString()}`;
}

/**
 * Dual-currency display anchored on the real USD figure. Renders
 * `<local> ($USD)` for a known country, or `$USD` alone otherwise.
 */
export function formatLocalAndUsd(
  usd: number | null | undefined,
  country?: string | null,
): string {
  if (usd == null) return '—';
  const local = localCurrencyFor(country);
  if (!local) return fmtUsdCompact(usd);
  return `${fmtMoneyCompact(usd * local.perUsd, local.symbol)} (${fmtUsdCompact(usd)})`;
}
