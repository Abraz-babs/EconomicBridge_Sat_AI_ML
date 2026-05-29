/**
 * Shared display helpers for the module panels.
 *
 * Two concerns that were getting hand-rolled (and drifting) per panel:
 *  - an HONEST data-provenance badge (don't label seed/mock data "LIVE")
 *  - hemisphere-aware coordinate formatting (Ghana/Senegal are west of the
 *    prime meridian, so a hardcoded "°E" was wrong)
 */

/**
 * Source tags that are demonstration / mock data TODAY. When a connector is
 * wired to its real upstream, remove its tag here and the badge flips to LIVE
 * automatically. `worldbank_v1` (real WB API) + `wfp_scope_v1` (operator CSV
 * upload) + the satellite tags are treated as real.
 */
const DEMO_SOURCES = new Set([
  "seed_v1",
  "giga_v1",        // GIGA/ITU client is mock-fallback until keys land
  "nbs_col_v1",     // NBS client is mock-fallback (no public API)
  "ecowas_stat_v1", // ECOWAS STAT client is mock-fallback
]);

export interface SourceBadge {
  label: string;
  /** CSS modifier on `.cg-mode-badge`. */
  cls: string;
}

/**
 * Build the provenance badge for a panel header. Returns a DEMO badge (amber)
 * when every source is demonstration/mock, a LIVE badge (green) when at least
 * one real source is present, and loading/error/empty states otherwise.
 */
export function sourceBadge(
  sources: string[] | undefined,
  opts: { loading?: boolean; error?: boolean } = {},
): SourceBadge {
  if (opts.loading) return { label: "LOADING", cls: "cg-mode-untuned" };
  if (opts.error) return { label: "API UNREACHABLE", cls: "cg-mode-untuned" };
  const s = sources ?? [];
  if (s.length === 0) return { label: "NO DATA", cls: "cg-mode-untuned" };
  const allDemo = s.every((x) => DEMO_SOURCES.has(x));
  if (allDemo) return { label: `DEMO · ${s.join(" + ")}`, cls: "cg-mode-untuned" };
  return { label: `LIVE · ${s.join(" + ")}`, cls: "cg-mode-trained" };
}

/**
 * Format a lat/lon pair with correct hemisphere suffixes, e.g.
 * `12.4500°N, 4.2000°E` (Nigeria) or `14.5890°N, 16.1266°W` (Senegal).
 * Replaces the hardcoded `°N, °E` that mislabelled western/southern points.
 */
export function formatLatLon(lat: number, lon: number, dp = 4): string {
  const ns = lat >= 0 ? "N" : "S";
  const ew = lon >= 0 ? "E" : "W";
  return `${Math.abs(lat).toFixed(dp)}°${ns}, ${Math.abs(lon).toFixed(dp)}°${ew}`;
}
