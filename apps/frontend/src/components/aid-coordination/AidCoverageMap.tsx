'use client';

import { useEffect, useState } from 'react';

import EBMap from '@/components/map/EBMap';
import { haloRadiusPx, haloRows } from '@/components/map/halo';
import type { Tenant } from '@/data/tenants';
import type { LgaPoint } from '@/hooks/useAidCoordination';


/** Status colour: red gap → yellow covered-by-one → green well-served. */
function colourFor(point: LgaPoint): [number, number, number, number] {
  if (point.status === 'gap') return [224, 90, 43, 230];           // red
  if (point.status === 'duplicated') return [82, 183, 136, 230];   // green
  return [240, 175, 60, 230];                                       // yellow
}


/** Hover-card text for an LGA coverage marker (Slice 25). */
function tooltipFor(obj: unknown): string | null {
  const p = obj as LgaPoint;
  if (!p?.lga) return null;
  const label =
    p.status === 'gap' ? 'Coverage gap — no agency'
    : p.status === 'duplicated' ? 'Multiple agencies'
    : 'Single agency';
  const lines = [
    `${p.lga} · ${label}`,
    `${p.agency_count} agenc${p.agency_count === 1 ? 'y' : 'ies'}`,
  ];
  if (p.agency_slugs.length > 0) lines.push(p.agency_slugs.join(', '));
  return lines.join('\n');
}


interface Props {
  tenant: Tenant;
  lgaPoints: LgaPoint[];
}


export default function AidCoverageMap({ tenant, lgaPoints }: Props) {
  const [layers, setLayers] = useState<unknown[]>([]);
  const [pulse, setPulse] = useState(0);

  // Heartbeat — pulses coverage gaps (LGAs with no agency), falling back to
  // the most under-served few so every tenant shows a uniform halo (Slice 25).
  const hasAttention = lgaPoints.length > 0;
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

      const pulseRows = haloRows(
        lgaPoints,
        (p) => p.status === 'gap',
        (p) => -p.agency_count,
      );
      const built: unknown[] = [
        // Pulse halo on coverage gaps.
        new ScatterplotLayer<LgaPoint>({
          id: 'aid-lga-pulse',
          data: pulseRows,
          getPosition: (p: LgaPoint) => [p.lon, p.lat],
          // Uniform pixel-pulse halo (Slice 25 fix): matches Poverty.
          getRadius: () => haloRadiusPx(pulse),
          getFillColor: [224, 90, 43, 40],
          radiusUnits: 'pixels',
          stroked: false,
          pickable: false,
          updateTriggers: { getRadius: pulse },
        }),
        // Coverage status circles.
        new ScatterplotLayer<LgaPoint>({
          id: 'aid-lga-coverage',
          data: lgaPoints,
          getPosition: (p: LgaPoint) => [p.lon, p.lat],
          // Tidy meter scale (Slice 25): matches Poverty so dots stay small.
          getRadius: (p: LgaPoint) =>
            4000 + p.agency_count * 4000,
          getFillColor: (p: LgaPoint) => colourFor(p),
          getLineColor: [255, 255, 255, 220],
          lineWidthMinPixels: 1.5,
          radiusUnits: 'meters',
          radiusMinPixels: 6,
          // Uniform base-dot cap (Slice 25): 24px, matches Poverty.
          radiusMaxPixels: 24,
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
  }, [lgaPoints, pulse]);

  const gapCount = lgaPoints.filter(p => p.status === 'gap').length;
  const dupCount = lgaPoints.filter(p => p.status === 'duplicated').length;

  return (
    <EBMap
      tenant={tenant}
      layers={layers}
      getTooltip={tooltipFor}
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
