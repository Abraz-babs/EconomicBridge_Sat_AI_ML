'use client';

import { useEffect, useMemo, useState } from 'react';

import EBMap from '@/components/map/EBMap';
import type { Tenant } from '@/data/tenants';
import type { ShockEventRow } from '@/hooks/useShockGuard';


/** Deterministic offset around the tenant centroid for events without lat/lon. */
function syntheticPosition(
  id: string,
  centroid: [number, number],
): [number, number] {
  let h = 5381;
  for (let i = 0; i < id.length; i++) h = ((h << 5) + h + id.charCodeAt(i)) | 0;
  h = Math.abs(h);
  const angle = ((h % 360) * Math.PI) / 180;
  const radius = 0.3 + ((h >> 8) % 60) / 100;
  return [
    centroid[0] + Math.cos(angle) * radius,
    centroid[1] + Math.sin(angle) * radius * 0.85,
  ];
}

interface PositionedEvent extends ShockEventRow {
  position: [number, number];
}


function colourFor(ev: ShockEventRow): [number, number, number, number] {
  if (ev.event_type === 'flood') {
    // Blue ramp for floods
    if (ev.severity === 'critical') return [37, 52, 148, 230];
    if (ev.severity === 'high')     return [65, 174, 218, 220];
    return [102, 194, 165, 200];
  }
  // Drought = red/orange ramp
  if (ev.severity === 'critical') return [224, 90, 43, 230];
  if (ev.severity === 'high')     return [255, 140, 0, 220];
  return [240, 175, 60, 200];
}


interface Props {
  tenant: Tenant;
  events: ShockEventRow[];
}


export default function ShockEventsMap({ tenant, events }: Props) {
  const positioned = useMemo<PositionedEvent[]>(
    () => events.map((ev) => ({
      ...ev,
      position: syntheticPosition(ev.id, tenant.centroid),
    })),
    [events, tenant.centroid],
  );

  const [layers, setLayers] = useState<unknown[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [{ ScatterplotLayer }] = await Promise.all([
        import('@deck.gl/layers'),
      ]);
      if (cancelled) return;
      const built: unknown[] = [
        new ScatterplotLayer<PositionedEvent>({
          id: 'shock-events',
          data: positioned,
          getPosition: (p) => p.position,
          // Radius scales with affected area
          getRadius: (p) => Math.max(8000, Math.sqrt(p.affected_area_km2) * 4000),
          getFillColor: (p) => colourFor(p),
          getLineColor: [255, 255, 255, 220],
          lineWidthMinPixels: 1.5,
          radiusUnits: 'meters',
          radiusMinPixels: 10,
          radiusMaxPixels: 40,
          stroked: true,
          pickable: true,
        }),
      ];
      setLayers(built);
    })();
    return () => { cancelled = true; };
  }, [positioned]);

  const floodCount = positioned.filter((p) => p.event_type === 'flood').length;
  const droughtCount = positioned.length - floodCount;

  return (
    <EBMap
      tenant={tenant}
      layers={layers}
      ariaLabel={`Shock events map — ${tenant.name}`}
      legend={
        <>
          <div className="fp-legend-item">
            <div className="fp-legend-dot fp-legend-dot--flood" />
            Flood
          </div>
          <div className="fp-legend-item">
            <div className="fp-legend-dot fp-legend-dot--critical" />
            Drought
          </div>
        </>
      }
      overlay={
        <>
          {positioned.length} event{positioned.length === 1 ? '' : 's'} ·{' '}
          {floodCount} flood · {droughtCount} drought<br />
          Circle size ≈ affected area · synthesised positions until real
          event-geometry lands
        </>
      }
    />
  );
}
