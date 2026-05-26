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
  const [pulse, setPulse] = useState(0);

  // Heartbeat — drives the halo on the worst-served LGAs (no_signal OR
  // learning_gap_index >= 0.7). Both are the "top intervention priority"
  // rule the dashboard exposes via the worst_gap_lga aggregate.
  const isAttention = (p: SkillsIndicatorRow) =>
    p.connectivity_band === 'no_signal' || p.learning_gap_index >= 0.7;
  const hasAttention = indicators.some(isAttention);
  useEffect(() => {
    if (!hasAttention) return;
    const id = window.setInterval(() => setPulse((p) => (p + 1) % 1000), 60);
    return () => window.clearInterval(id);
  }, [hasAttention]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [{ ScatterplotLayer, TextLayer }] = await Promise.all([
        import('@deck.gl/layers'),
      ]);
      if (cancelled) return;
      const pulseRows = indicators.filter(isAttention);
      const pulseScale = 0.4 + 0.6 * (0.5 + 0.5 * Math.sin(pulse * 0.18));
      const built: unknown[] = [
        new ScatterplotLayer<SkillsIndicatorRow>({
          id: 'skills-lga-pulse',
          data: pulseRows,
          getPosition: (p) => [p.location.lon, p.location.lat],
          getRadius: () => 26000 * pulseScale,
          getFillColor: [192, 60, 40, 40],
          radiusUnits: 'meters',
          radiusMinPixels: 14,
          radiusMaxPixels: 80,
          stroked: false,
          pickable: false,
          updateTriggers: { getRadius: pulse },
        }),
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
  }, [indicators, pulse]);

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
