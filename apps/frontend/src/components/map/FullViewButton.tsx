'use client';

import { useEffect, useState, type RefObject } from 'react';

/**
 * "Back to full map" — the way home after the map has flown in to one alert,
 * village or checked plot ("Show on map", a Farm Check), or after the reader
 * zoomed or panned by hand. Shared by FarmlandMap and EBMap, so every module
 * map has the same control in the same corner (bottom-right; the legend owns
 * bottom-left, the pass/freshness overlay top-right).
 */

type MovableMap = {
  getCenter: () => { lng: number; lat: number };
  getZoom: () => number;
  on: (type: 'moveend', listener: () => void) => void;
  off: (type: 'moveend', listener: () => void) => void;
};

/** True once the map has come to rest away from the tenant's full view.
 *  Only moves are watched — the map starts at the full view, and flying back
 *  there (the button, or a tenant switch) ends in a move that clears it. */
export function useAwayFromFullView(
  mapRef: RefObject<unknown>,
  ready: boolean,
  center: [number, number],
  zoom: number,
): boolean {
  const [away, setAway] = useState(false);
  const [lng, lat] = center;
  useEffect(() => {
    const map = mapRef.current as MovableMap | null;
    if (!ready || !map) return;
    const onMoveEnd = () => {
      const c = map.getCenter();
      setAway(
        Math.abs(map.getZoom() - zoom) > 0.25
          || Math.abs(c.lng - lng) > 0.15
          || Math.abs(c.lat - lat) > 0.15,
      );
    };
    map.on('moveend', onMoveEnd);
    return () => map.off('moveend', onMoveEnd);
  }, [mapRef, ready, lng, lat, zoom]);
  return away;
}

export default function FullViewButton({
  areaName,
  onClick,
}: {
  /** The tenant's name, for the accessible label ("Kebbi State"). */
  areaName: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className="eb-map-fullview"
      onClick={onClick}
      aria-label={`Back to the full map of ${areaName}`}
    >
      <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true" focusable="false">
        <path
          d="M1.5 4.5v-3h3M10.5 4.5v-3h-3M1.5 7.5v3h3M10.5 7.5v3h-3"
          fill="none" stroke="currentColor" strokeWidth="1.4"
          strokeLinecap="round" strokeLinejoin="round"
        />
      </svg>
      Back to full map
    </button>
  );
}
