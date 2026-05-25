'use client';

import { useEffect, useState } from 'react';

import EBMap from '@/components/map/EBMap';
import type { Tenant } from '@/data/tenants';
import type { SkillsIndicatorRow } from '@/hooks/useSkillsBridge';


/** Connectivity band → [r, g, b, a]. no_signal = deep red (worst),
 * broadband = green (best). */
function colourFor(row: SkillsIndicatorRow): [number, number, number, number] {
  switch (row.connectivity_band) {
    case 'no_signal': return [192, 60, 40, 240];
    case 'limited':   return [224, 130, 50, 230];
    case 'basic':     return [240, 175, 60, 220];
    case 'broadband': return [82, 183, 136, 220];
  }
}


interface Props {
  tenant: Tenant;
  indicators: SkillsIndicatorRow[];
}


export default function SkillsMap({ tenant, indicators }: Props) {
  const [layers, setLayers] = useState<unknown[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [{ ScatterplotLayer, TextLayer }] = await Promise.all([
        import('@deck.gl/layers'),
      ]);
      if (cancelled) return;
      const built: unknown[] = [
        new ScatterplotLayer<SkillsIndicatorRow>({
          id: 'skills-lga-connectivity',
          data: indicators,
          getPosition: (p) => [p.location.lon, p.location.lat],
          // Radius scales with youth pop — bigger circle = more young
          // people affected by the local connectivity gap.
          getRadius: (p) => 7000 + Math.sqrt(p.youth_population) * 90,
          getFillColor: (p) => colourFor(p),
          getLineColor: [255, 255, 255, 220],
          lineWidthMinPixels: 1.5,
          radiusUnits: 'meters',
          radiusMinPixels: 10,
          radiusMaxPixels: 40,
          stroked: true,
          pickable: true,
        }),
        new TextLayer<SkillsIndicatorRow>({
          id: 'skills-lga-labels',
          data: indicators,
          getPosition: (p) => [p.location.lon, p.location.lat],
          getText: (p) =>
            `${p.lga} · ${p.internet_coverage_pct.toFixed(0)}%`,
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

  const noSignal = indicators.filter((i) => i.connectivity_band === 'no_signal').length;
  const broadband = indicators.filter((i) => i.connectivity_band === 'broadband').length;

  return (
    <EBMap
      tenant={tenant}
      layers={layers}
      ariaLabel={`SkillsBridge connectivity map — ${tenant.name}`}
      legend={
        <>
          <div className="fp-legend-item">
            <div className="fp-legend-dot fp-legend-dot--conn-none" />
            No signal
          </div>
          <div className="fp-legend-item">
            <div className="fp-legend-dot fp-legend-dot--conn-limited" />
            Limited
          </div>
          <div className="fp-legend-item">
            <div className="fp-legend-dot fp-legend-dot--conn-basic" />
            Basic
          </div>
          <div className="fp-legend-item">
            <div className="fp-legend-dot fp-legend-dot--conn-broadband" />
            Broadband
          </div>
        </>
      }
      overlay={
        <>
          {indicators.length} LGAs · {noSignal} unserved · {broadband} broadband<br />
          Circle size ≈ youth pop · colour = connectivity band
        </>
      }
    />
  );
}
