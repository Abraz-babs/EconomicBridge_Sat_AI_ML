'use client';

import { useEffect, useState } from 'react';

import EBMap from '@/components/map/EBMap';
import type { Tenant } from '@/data/tenants';
import type { PovertyVillage } from '@/hooks/usePovertyVillages';


/** Severity colour ramp — green (low) → red (critical). */
function colourFor(score: number): [number, number, number, number] {
  if (score >= 0.80) return [255, 69, 0, 220];       // critical
  if (score >= 0.65) return [255, 140, 0, 220];      // high
  if (score >= 0.50) return [240, 175, 60, 220];     // medium
  return [82, 183, 136, 220];                         // low
}


/** Hover-card text for a village marker (Slice 25). */
function tooltipFor(obj: unknown): string | null {
  const v = obj as PovertyVillage;
  if (!v?.settlement_name) return null;
  const lines = [
    `${v.lga} · ${v.settlement_name}`,
    `Poverty score: ${v.poverty_score.toFixed(2)}`,
    `Population: ${v.population.toLocaleString()}`,
  ];
  if (v.households_unreached > 0) {
    lines.push(`${v.households_unreached.toLocaleString()} households unreached`);
  }
  lines.push(`Source: ${v.source}`);
  return lines.join('\n');
}


interface Props {
  tenant: Tenant;
  villages: PovertyVillage[];
}


export default function PovertyMap({ tenant, villages }: Props) {
  const [layers, setLayers] = useState<unknown[]>([]);
  const [pulse, setPulse] = useState(0);

  // Heartbeat — pulses critical-poverty villages (score >= 0.80) so the
  // eye lands on the highest-need settlements first, even when the
  // heatmap is dense.
  const hasAttention = villages.some((v) => v.poverty_score >= 0.80);
  useEffect(() => {
    if (!hasAttention) return;
    const id = window.setInterval(() => setPulse((p) => (p + 1) % 1000), 60);
    return () => window.clearInterval(id);
  }, [hasAttention]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [{ ScatterplotLayer, TextLayer }, { HeatmapLayer }] = await Promise.all([
        import('@deck.gl/layers'),
        import('@deck.gl/aggregation-layers'),
      ]);
      if (cancelled) return;

      const pulseRows = villages.filter((v) => v.poverty_score >= 0.80);
      const pulseScale = 0.4 + 0.6 * (0.5 + 0.5 * Math.sin(pulse * 0.18));
      const built: unknown[] = [
        new HeatmapLayer<PovertyVillage>({
          id: 'poverty-heatmap',
          data: villages,
          getPosition: (v: PovertyVillage) => [v.location.lon, v.location.lat],
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
        new ScatterplotLayer<PovertyVillage>({
          id: 'poverty-pulse',
          data: pulseRows,
          getPosition: (v: PovertyVillage) => [v.location.lon, v.location.lat],
          getRadius: () => 30000 * pulseScale,
          getFillColor: [255, 69, 0, 40],
          radiusUnits: 'meters',
          radiusMinPixels: 14,
          radiusMaxPixels: 80,
          stroked: false,
          pickable: false,
          updateTriggers: { getRadius: pulse },
        }),
        new ScatterplotLayer<PovertyVillage>({
          id: 'poverty-villages',
          data: villages,
          getPosition: (v: PovertyVillage) => [v.location.lon, v.location.lat],
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
        new TextLayer<PovertyVillage>({
          id: 'poverty-village-labels',
          data: villages,
          getPosition: (v: PovertyVillage) => [v.location.lon, v.location.lat],
          getText: (v: PovertyVillage) => `${v.lga} · ${v.settlement_name}`,
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
  }, [villages, pulse]);

  const sources = Array.from(new Set(villages.map((v) => v.source)));

  return (
    <EBMap
      tenant={tenant}
      layers={layers}
      getTooltip={tooltipFor}
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
          {villages.length} vulnerable settlements<br />
          Pin size ≈ population · colour ≈ poverty score<br />
          {sources.length > 0 && <>Sources: {sources.join(', ')}</>}
        </>
      }
    />
  );
}
