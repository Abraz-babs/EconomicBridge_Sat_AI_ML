'use client';

import type { NearestPlace } from '@/hooks/useFarmlandAlerts';

/**
 * Field directions for one alert: the nearest named village, its ward, and
 * how far and which way the alert lies from it — "1.0 km SE of Kurmin Kaya ·
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
      <a
        href={`https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`}
        target="_blank"
        rel="noopener noreferrer"
        className="fp-directions-link"
      >
        Directions ↗
      </a>
    </div>
  );
}
