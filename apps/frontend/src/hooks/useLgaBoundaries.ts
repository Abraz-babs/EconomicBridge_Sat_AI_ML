'use client';

/**
 * LGA boundaries for the Nigerian pilot states, for shading LGAs on a module
 * map. A static file (public/geo/lga-boundaries-ng.json, ~200 KB): geoBoundaries
 * ADM2 (CC BY 4.0), simplified, each shape matched to our own LGA name by the
 * shape that contains the LGA's centroid. Fetched once and cached.
 */

import { useQuery } from '@tanstack/react-query';

export interface LgaFeature {
  type: 'Feature';
  properties: { tenant: string; lga: string };
  geometry: { type: 'Polygon' | 'MultiPolygon'; coordinates: unknown };
}

interface LgaCollection {
  type: 'FeatureCollection';
  features: LgaFeature[];
}

export function useLgaBoundaries(tenantId: string) {
  return useQuery<LgaCollection, Error, LgaFeature[]>({
    queryKey: ['lga-boundaries-ng'],
    queryFn: async () => {
      const res = await fetch('/geo/lga-boundaries-ng.json');
      if (!res.ok) throw new Error(`LGA boundaries: ${res.status}`);
      return res.json();
    },
    staleTime: Infinity,
    gcTime: Infinity,
    select: (fc) => fc.features.filter((f) => f.properties.tenant === tenantId),
  });
}
