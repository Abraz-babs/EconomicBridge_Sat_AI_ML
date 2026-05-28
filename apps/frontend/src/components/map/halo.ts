/**
 * Rows to pulse with the attention halo.
 *
 * Returns every row that crosses the module's severity threshold. If none do
 * (e.g. a tenant with no "critical" rows), falls back to the top-N most severe
 * so the map still shows a uniform heartbeat instead of a dead, halo-less view.
 * Keeps halo behaviour consistent across all modules (Slice 25 follow-up).
 */
export function haloRows<T>(
  rows: T[],
  passesThreshold: (row: T) => boolean,
  severity: (row: T) => number,
  topN = 3,
): T[] {
  const flagged = rows.filter(passesThreshold);
  if (flagged.length > 0) return flagged;
  return [...rows].sort((a, b) => severity(b) - severity(a)).slice(0, topN);
}

/**
 * Pulsing halo radius in PIXELS — a zoom-independent heartbeat.
 *
 * Earlier the halo used `radiusUnits: 'meters'` (~30 km), which at the
 * default zoom-6 view (~2.4 km/px) rendered to only ~5–12 px and was then
 * pinned flat by `radiusMinPixels`, so the pulse was invisible. Driving the
 * radius directly in pixels makes every module breathe the same 20→40 px
 * ring at any zoom. `pulse` is the monotonic tick from the 60 ms interval.
 */
export function haloRadiusPx(pulse: number): number {
  const t = 0.5 + 0.5 * Math.sin(pulse * 0.18);
  return 20 + 20 * t;
}
