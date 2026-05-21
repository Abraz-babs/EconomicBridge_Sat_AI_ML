'use client';

import { useEffect, useState } from 'react';

import EBMap from '@/components/map/EBMap';
import type { Tenant } from '@/data/tenants';
import type { LgaPoint } from '@/hooks/useAidCoordination';


/** Status colour: red gap → yellow covered-by-one → green well-served. */
function colourFor(point: LgaPoint): [number, number, number, number] {
  if (point.status === 'gap') return [224, 90, 43, 230];           // red
  if (point.status === 'duplicated') return [82, 183, 136, 230];   // green
  return [240, 175, 60, 230];                                       // yellow
}


interface Props {
  tenant: Tenant;
  lgaPoints: LgaPoint[];
}


export default function AidCoverageMap({ tenant, lgaPoints }: Props) {
  const [layers, setLayers] = useState<unknown[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [{ ScatterplotLayer, TextLayer }] = await Promise.all([
        import('@deck.gl/layers'),
      ]);
      if (cancelled) return;

      const built: unknown[] = [
        // Coverage status circles.
        new ScatterplotLayer<LgaPoint>({
          id: 'aid-lga-coverage',
          data: lgaPoints,
          getPosition: (p: LgaPoint) => [p.lon, p.lat],
          getRadius: (p: LgaPoint) =>
            12000 + p.agency_count * 6000,
          getFillColor: (p: LgaPoint) => colourFor(p),
          getLineColor: [255, 255, 255, 220],
          lineWidthMinPixels: 1.5,
          radiusUnits: 'meters',
          radiusMinPixels: 10,
          radiusMaxPixels: 38,
          stroked: true,
          pickable: true,
        }),
        // LGA label badges above each point.
        new TextLayer<LgaPoint>({
          id: 'aid-lga-labels',
          data: lgaPoints,
          getPosition: (p: LgaPoint) => [p.lon, p.lat],
          getText: (p: LgaPoint) =>
            p.status === 'gap' ? `⚠ ${p.lga}` : `${p.lga} (${p.agency_count})`,
          getSize: 12,
          getColor: [255, 255, 255, 240],
          getPixelOffset: [0, -22],
          fontFamily: 'system-ui, sans-serif',
          fontWeight: 600,
          background: true,
          getBackgroundColor: [26, 23, 20, 200],
          backgroundPadding: [4, 2, 4, 2],
        }),
      ];
      setLayers(built);
    })();
    return () => { cancelled = true; };
  }, [lgaPoints]);

  const gapCount = lgaPoints.filter(p => p.status === 'gap').length;
  const dupCount = lgaPoints.filter(p => p.status === 'duplicated').length;

  return (
    <EBMap
      tenant={tenant}
      layers={layers}
      ariaLabel={`Aid agency coverage map — ${tenant.name}`}
      legend={
        <>
          <div className="fp-legend-item">
            <div className="fp-legend-dot fp-legend-dot--critical" />
            Gap — no agency
          </div>
          <div className="fp-legend-item">
            <div className="fp-legend-dot fp-legend-dot--high" />
            Single agency
          </div>
          <div className="fp-legend-item">
            <div className="fp-legend-dot fp-legend-dot--resolved" />
            Multiple agencies
          </div>
        </>
      }
      overlay={
        <>
          {lgaPoints.length} LGAs · {gapCount} gaps · {dupCount} duplications<br />
          Circle size ≈ agency count · colour ≈ coverage status<br />
          <span className="fp-map-overlay__warn">DEV — seed data</span>
        </>
      }
    />
  );
}
