import type { Tenant } from '@/data/tenants';

/**
 * Framing a state on a map, shared by EBMap and FarmlandMap.
 *
 * Every map used to fly to a state's centre at one fixed zoom. That cropped
 * Ghana, left FCT a speck in a large frame, and a map that remounted on a state
 * change (its data still loading) jumped instead of flying. The camera is now
 * fitted to the state's own bounds, and flights start from wherever the reader
 * last was, so changing state always reads as travel from one place to another.
 */

export interface Camera {
  center: [number, number];
  zoom: number;
}

type LngLatBounds = [[number, number], [number, number]];

type CameraMap = {
  cameraForBounds: (
    b: LngLatBounds,
    o?: { padding?: number },
  ) => { center?: { lng: number; lat: number } | [number, number]; zoom?: number } | undefined;
  flyTo: (o: Record<string, unknown>) => void;
  jumpTo: (o: Record<string, unknown>) => void;
  getCenter: () => { lng: number; lat: number };
  getZoom: () => number;
  getContainer: () => HTMLElement;
};

/** Room kept between the state and the map edge (legend, overlay, button). */
export const FIT_PADDING = 36;

export function tenantBounds(t: Tenant): LngLatBounds {
  const [w, s, e, n] = t.bbox;
  return [[w, s], [e, n]];
}

/** The camera that frames the whole state, or null while the map has no size
 *  (a map inside a closed <details> measures 0 × 0). */
export function fitCamera(map: unknown, t: Tenant, padding = FIT_PADDING): Camera | null {
  const m = map as CameraMap;
  const box = m.getContainer();
  if (!box || box.clientWidth < 2 * padding + 40 || box.clientHeight < 2 * padding + 40) return null;
  const cam = m.cameraForBounds(tenantBounds(t), { padding });
  if (!cam || cam.center == null || cam.zoom == null || !Number.isFinite(cam.zoom)) return null;
  const c = cam.center;
  return { center: Array.isArray(c) ? [c[0], c[1]] : [c.lng, c.lat], zoom: cam.zoom };
}

const easeInOutCubic = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2);

function km(a: [number, number], b: [number, number]): number {
  const r = Math.PI / 180;
  const dLat = (b[1] - a[1]) * r;
  const dLon = (b[0] - a[0]) * r;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[1] * r) * Math.cos(b[1] * r) * Math.sin(dLon / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(h));
}

/**
 * Fly to the whole state. A longer trip takes a little longer (1.2–2 s) and
 * arcs out and back in (`curve`), so the reader sees where they came from.
 * `essential` is left unset: mapbox turns the flight into a jump for readers
 * who ask their system for reduced motion. Returns the camera it is flying to,
 * or null if the map has no size yet (the caller re-fits on resize).
 */
export function flyToTenant(map: unknown, t: Tenant, padding = FIT_PADDING): Camera | null {
  const m = map as CameraMap;
  const cam = fitCamera(m, t, padding);
  if (!cam) return null;
  const from = m.getCenter();
  const dist = km([from.lng, from.lat], cam.center);
  const duration = Math.round(Math.min(2000, Math.max(1200, 1100 + dist * 0.35)));
  m.flyTo({ center: cam.center, zoom: cam.zoom, pitch: 0, bearing: 0, curve: 1.6, duration, easing: easeInOutCubic });
  return cam;
}

export function jumpToTenant(map: unknown, t: Tenant, padding = FIT_PADDING): Camera | null {
  const cam = fitCamera(map, t, padding);
  if (cam) (map as CameraMap).jumpTo({ center: cam.center, zoom: cam.zoom, pitch: 0, bearing: 0 });
  return cam;
}

/**
 * Where the reader last was, on any map. A map that mounts for a different
 * state (a module whose data loads per state remounts its map) starts here and
 * flies to the new state, instead of appearing already there.
 */
let lastCamera: (Camera & { tenantId: string }) | null = null;

export function rememberCamera(map: unknown, tenantId: string): void {
  const m = map as CameraMap;
  const c = m.getCenter();
  lastCamera = { tenantId, center: [c.lng, c.lat], zoom: m.getZoom() };
}

export function recalledCamera(tenantId: string): Camera | null {
  return lastCamera && lastCamera.tenantId !== tenantId
    ? { center: lastCamera.center, zoom: lastCamera.zoom }
    : null;
}
