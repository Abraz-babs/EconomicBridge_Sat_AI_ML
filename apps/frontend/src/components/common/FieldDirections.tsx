'use client';

import type { NearestPlace } from '@/lib/places';

/**
 * Field directions for one real point (an alert, a detection, a geotagged
 * photo, a checked plot): the nearest named village, its ward, and how far
 * and which way the point lies from it — "1.0 km SE of Kurmin Kaya ·
 * Libata ward" — plus a Directions link that navigates a field phone to the
 * alert's exact coordinates (Google Maps; works offline with a downloaded area).
 *
 * The village comes from the API (services/places.py → GRID3 settlement names,
 * CC BY 4.0); nothing is looked up in the browser.
 */
export const GRID3_CREDIT = 'Village names © GRID3, CC BY 4.0';

export default function FieldDirections({
  place,
  lat,
  lon,
}: {
  place: NearestPlace | null | undefined;
  lat: number;
  lon: number;
}) {
  if (!place) return null;
  const where = place.direction
    ? `${place.distance_km.toFixed(1)} km ${place.direction} of ${place.name}`
    : `At ${place.name}`;
  const ward = place.ward && place.ward !== place.name ? ` · ${place.ward} ward` : '';
  const how = place.direction
    ? `From ${place.name}, head ${place.direction} for ${place.distance_km.toFixed(1)} km to reach the alert.`
    : `The alert is at ${place.name}.`;
  return (
    <div className="fp-alert-coords fp-directions" title={`${how} ${GRID3_CREDIT}.`}>
      🧭 {where}{ward}
      {' · '}
      <DirectionsLink lat={lat} lon={lon} />
    </div>
  );
}

/** The Directions link on its own — Google Maps navigation to the exact
 *  coordinates. The arrow is drawn, not typed: DM Mono has no ↗, so a
 *  fallback font set it low and apart from the word; the link also never
 *  wraps, so word and arrow always sit together. */
export function DirectionsLink({ lat, lon }: { lat: number; lon: number }) {
  return (
    <a
      href={`https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`}
      target="_blank"
      rel="noopener noreferrer"
      className="fp-directions-link"
      title="Turn-by-turn directions in Google Maps"
    >
      Directions
      <svg viewBox="0 0 12 12" width="9" height="9" aria-hidden="true" focusable="false">
        <path
          d="M4 2.5h5.5V8M9.5 2.5 2.5 9.5"
          fill="none" stroke="currentColor" strokeWidth="1.6"
          strokeLinecap="round" strokeLinejoin="round"
        />
      </svg>
    </a>
  );
}
