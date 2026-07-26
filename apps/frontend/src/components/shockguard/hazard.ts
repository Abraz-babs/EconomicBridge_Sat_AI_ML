/**
 * Hazard-type presentation for ShockGuard.
 *
 * ShockGuard is a rainy-season DISASTER REGISTER, not a flood log. The panel
 * and map used to branch `event_type === 'flood' ? 'flood' : 'drought'`, so any
 * third type silently rendered as drought — a rainstorm that took 100 roofs off
 * in Riyom would have shown a drought icon. One table keeps the timeline and
 * map unified; this module is what keeps the types visually distinct.
 *
 * Keep in sync with schemas/shockguard.py `ShockEventType` and the DB CHECK
 * widened in migration 0036.
 */

export type HazardType =
  | 'flood'
  | 'drought'
  | 'rainstorm'
  | 'windstorm'
  | 'landslide'
  | 'erosion';

export interface HazardStyle {
  icon: string;
  label: string;
  /** Map marker colour, RGB. */
  rgb: [number, number, number];
}

const HAZARD: Record<HazardType, HazardStyle> = {
  flood: { icon: '🌊', label: 'Flood', rgb: [56, 132, 255] },
  drought: { icon: '🔥', label: 'Drought', rgb: [240, 140, 40] },
  rainstorm: { icon: '🌩', label: 'Rainstorm', rgb: [124, 92, 220] },
  windstorm: { icon: '🌪', label: 'Windstorm', rgb: [96, 116, 160] },
  landslide: { icon: '⛰', label: 'Landslide', rgb: [150, 96, 60] },
  erosion: { icon: '🕳', label: 'Erosion', rgb: [176, 124, 84] },
};

/** Unknown types degrade to a neutral marker rather than being mislabelled as
 *  another hazard — a wrong label is worse than a generic one. */
const FALLBACK: HazardStyle = { icon: '⚠', label: 'Hazard', rgb: [148, 163, 184] };

export function hazardStyle(eventType: string | null | undefined): HazardStyle {
  return HAZARD[(eventType ?? '') as HazardType] ?? FALLBACK;
}

export function hazardIcon(eventType: string | null | undefined): string {
  return hazardStyle(eventType).icon;
}

export function hazardLabel(eventType: string | null | undefined): string {
  return hazardStyle(eventType).label;
}
