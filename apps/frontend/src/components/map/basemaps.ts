/**
 * Map styles a viewer can switch between on every module map (operator's
 * standing rule, 2026-09-26): real satellite imagery, a dark field for glowing
 * data, and a light field for print-like reading. Data layers sit on top of
 * whichever is chosen.
 */

export type Basemap = 'satellite' | 'dark' | 'light';

export const BASEMAPS: Basemap[] = ['satellite', 'dark', 'light'];

export const BASEMAP_LABEL: Record<Basemap, string> = {
  satellite: 'Satellite',
  dark: 'Dark',
  light: 'Light',
};

export const BASEMAP_STYLE: Record<Basemap, string> = {
  satellite: 'mapbox://styles/mapbox/satellite-streets-v12',
  dark: 'mapbox://styles/mapbox/dark-v11',
  light: 'mapbox://styles/mapbox/light-v11',
};

/** Fill opacity (0–255) for area layers: lighter on satellite so fields show. */
export function fillAlpha(basemap: Basemap): number {
  return basemap === 'satellite' ? 120 : 195;
}
