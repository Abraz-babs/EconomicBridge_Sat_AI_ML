'use client';

import { useEffect, useState } from 'react';

import EBMap from '@/components/map/EBMap';
import type { Tenant } from '@/data/tenants';
import type { MobilityIndicatorRow } from '@/hooks/useEconomicMobility';


/** Cost-of-living band → [r, g, b, a]. Below_avg = green (affordable),
 * premium = deep red (capital-tier expensive). */
function colourFor(row: MobilityIndicatorRow): [number, number, number, number] {
  switch (row.cost_of_living_band) {
    case 'below_avg': return [82, 183, 136, 220];
    case 'near_avg':  return [240, 175, 60, 220];
    case 'above_avg': return [224, 130, 50, 230];
    case 'premium':   return [192, 60, 40, 240];
  }
}


interface Props {
  tenant: Tenant;
  indicators: MobilityIndicatorRow[];
}


export default function MobilityMap({ tenant, indicators }: Props) {
  const [layers, setLayers] = useState<unknown[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [{ ScatterplotLayer, TextLayer }] = await Promise.all([
        import('@deck.gl/layers'),
      ]);
      if (cancelled) return;
      const built: unknown[] = [
        new ScatterplotLayer<MobilityIndicatorRow>({
          id: 'mobility-lga-col',
          data: indicators,
          getPosition: (p) => [p.location.lon, p.location.lat],
          // Radius scales with population so denser LGAs read louder.
          getRadius: (p) => 8000 + Math.sqrt(p.population) * 80,
          getFillColor: (p) => colourFor(p),
          getLineColor: [255, 255, 255, 220],
          lineWidthMinPixels: 1.5,
          radiusUnits: 'meters',
          radiusMinPixels: 10,
          radiusMaxPixels: 40,
          stroked: true,
          pickable: true,
        }),
        new TextLayer<MobilityIndicatorRow>({
          id: 'mobility-lga-labels',
          data: indicators,
          getPosition: (p) => [p.location.lon, p.location.lat],
          getText: (p) =>
            `${p.lga} · COL ${p.cost_of_living_index.toFixed(0)}`,
          getSize: 11,
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
  }, [indicators]);

  const premium = indicators.filter((i) => i.cost_of_living_band === 'premium').length;
  const below = indicators.filter((i) => i.cost_of_living_band === 'below_avg').length;

  return (
    <EBMap
      tenant={tenant}
      layers={layers}
      ariaLabel={`Economic mobility map — ${tenant.name}`}
      legend={
        <>
          <div className="fp-legend-item">
            <div className="fp-legend-dot fp-legend-dot--col-below" />
            Below average
          </div>
          <div className="fp-legend-item">
            <div className="fp-legend-dot fp-legend-dot--col-near" />
            Near average
          </div>
          <div className="fp-legend-item">
            <div className="fp-legend-dot fp-legend-dot--col-above" />
            Above average
          </div>
          <div className="fp-legend-item">
            <div className="fp-legend-dot fp-legend-dot--col-premium" />
            Premium
          </div>
        </>
      }
      overlay={
        <>
          {indicators.length} LGAs · {below} affordable · {premium} premium<br />
          Circle size ≈ population · colour = cost-of-living band
        </>
      }
    />
  );
}
