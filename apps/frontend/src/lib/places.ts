import { apiFetch, type SuccessEnvelope } from '@/lib/api';

/** The named village nearest a real point on the ground — mirrors
 *  apps/api/schemas/places.py NearestPlace. GRID3 settlement names, CC BY 4.0.
 *
 *  The API attaches one ONLY to real points (a detection's measured box, a
 *  geotagged photo, a checked plot) — never to an LGA centroid standing in for
 *  an area — so a missing value means "no exact point", not "unknown village".
 *  `direction` runs FROM the village TO the point; null when it is at it. */
export interface NearestPlace {
  name: string;
  ward: string | null;
  lga: string | null;
  distance_km: number;
  direction: string | null;
  location: { lon: number; lat: number };
}


/** '1.0 km SE of Kurmin Kaya, Libata ward' — the same wording as the cards. */
export function describePlace(p: NearestPlace | null | undefined): string | null {
  if (!p) return null;
  const at = p.direction
    ? `${p.distance_km.toFixed(1)} km ${p.direction} of ${p.name}`
    : `at ${p.name}`;
  return p.ward && p.ward !== p.name ? `${at}, ${p.ward} ward` : at;
}

/** Nearest village for coordinates a person typed or checked (Farm Check,
 *  a bulk sheet). GET /geo/nearest-places — a GET on purpose so a lookup is
 *  never audited as an action. Resolves to nulls on any failure: directions
 *  are extra and must never fail the check they accompany. */
export async function fetchNearestPlaces(
  points: { lon: number; lat: number }[],
): Promise<(NearestPlace | null)[]> {
  if (points.length === 0) return [];
  const q = points.map((p) => `${p.lon.toFixed(6)},${p.lat.toFixed(6)}`).join(';');
  try {
    const env: SuccessEnvelope<{ places: (NearestPlace | null)[] }> =
      await apiFetch<{ places: (NearestPlace | null)[] }>(
        `/geo/nearest-places?points=${encodeURIComponent(q)}`,
      );
    return env.data.places;
  } catch {
    return points.map(() => null);
  }
}
