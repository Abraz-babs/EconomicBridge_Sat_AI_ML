'use client';

import { useEffect, useState } from 'react';

import EBMap from '@/components/map/EBMap';
import type { Tenant } from '@/data/tenants';
import type { PovertyVillage } from '@/data/povertySeed';


/** Severity colour ramp — green (low) → red (critical). */
function colourFor(score: number): [number, number, number, number] {
  if (score >= 0.80) return [255, 69, 0, 220];       // critical
  if (score >= 0.65) return [255, 140, 0, 220];      // high
  if (score >= 0.50) return [240, 175, 60, 220];     // medium
  return [82, 183, 136, 220];                         // low
}


interface Props {
  tenant: Tenant;
  villages: PovertyVillage[];
}


export default function PovertyMap({ tenant, villages }: Props) {
  const [layers, setLayers] = useState<unknown[]>([]);

  // Build layers lazily on the client (deck.gl is browser-only).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [{ ScatterplotLayer }, { HeatmapLayer }] = await Promise.all([
        import('@deck.gl/layers'),
        import('@deck.gl/aggregation-layers'),
      ]);
      if (cancelled) return;

      const built: unknown[] = [
        // Vulnerability heatmap underneath the pins.
        new HeatmapLayer<PovertyVillage>({
          id: 'poverty-heatmap',
          data: villages,
          getPosition: (v: PovertyVillage) => [v.lon, v.lat],
          getWeight: (v: PovertyVillage) => v.poverty_score * v.population,
          radiusPixels: 60,
          intensity: 1.2,
          threshold: 0.05,
          colorRange: [
            [82, 183, 136, 0],
            [240, 175, 60],
            [255, 140, 0],
            [255, 69, 0],
          ],
        }),
        // Village pins on top.
        new ScatterplotLayer<PovertyVillage>({
          id: 'poverty-villages',
          data: villages,
          getPosition: (v: PovertyVillage) => [v.lon, v.lat],
          getRadius: (v: PovertyVillage) => 4000 + Math.sqrt(v.population) * 40,
          getFillColor: (v: PovertyVillage) => colourFor(v.poverty_score),
          getLineColor: [255, 255, 255, 220],
          lineWidthMinPixels: 1.5,
          radiusUnits: 'meters',
          radiusMinPixels: 6,
          radiusMaxPixels: 24,
          stroked: true,
          pickable: true,
        }),
      ];
      setLayers(built);
    })();
    return () => { cancelled = true; };
  }, [villages]);

  return (
    <EBMap
      tenant={tenant}
      layers={layers}
      ariaLabel={`Poverty intensity map — ${tenant.name}`}
      legend={
        <>
          <div className="fp-legend-item">
            <div className="fp-legend-dot fp-legend-dot--critical" />
            Critical (poverty score ≥ 0.80)
          </div>
          <div className="fp-legend-item">
            <div className="fp-legend-dot fp-legend-dot--high" />
            High (0.65–0.79)
          </div>
          <div className="fp-legend-item">
            <div className="fp-legend-dot fp-legend-dot--resolved" />
            Low/medium (&lt; 0.65)
          </div>
        </>
      }
      overlay={
        <>
          VIIRS Nightlight + WorldPop · {villages.length} vulnerable settlements<br />
          Pin size ≈ population estimate · colour ≈ poverty score<br />
          <span className="fp-map-overlay__warn">DEV — seed data</span>
        </>
      }
    />
  );
}
