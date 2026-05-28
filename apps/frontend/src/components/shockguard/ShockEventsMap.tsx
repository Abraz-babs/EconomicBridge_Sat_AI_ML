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


/** Hover-card text for an event marker (Slice 25). */
function tooltipFor(obj: unknown): string | null {
  const e = obj as PositionedEvent;
  if (!e?.event_type) return null;
  const icon = e.event_type === 'flood' ? '🌊' : '🔥';
  return [
    `${icon} ${e.event_type.toUpperCase()} · ${e.severity}`,
    `Location: ${e.lga ?? '—'}`,
    `~${Math.round(e.population_at_risk).toLocaleString()} at risk · ${e.affected_area_km2.toFixed(0)} km²`,
    `Onset in ${e.projected_onset_hours}h · ${e.confidence_band}`,
    `${e.detector_name} ${e.detector_version}`,
  ].join('\n');
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
  const [pulse, setPulse] = useState(0);

  // Heartbeat — pulses critical + high severity events. Two-tier scaling so
  // critical events read louder than high (same convention as FarmlandMap).
  const hasAttention = positioned.some(
    (p) => p.severity === 'critical' || p.severity === 'high',
  );
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
      const pulseRows = positioned.filter(
        (p) => p.severity === 'critical' || p.severity === 'high',
      );
      const pulseScale = 0.4 + 0.6 * (0.5 + 0.5 * Math.sin(pulse * 0.18));
      const built: unknown[] = [
        new ScatterplotLayer<PositionedEvent>({
          id: 'shock-events-pulse',
          data: pulseRows,
          getPosition: (p) => p.position,
          // Uniform halo (Slice 25): 30000m / 80px, matches Poverty.
          // Severity is conveyed by colour, not size.
          getRadius: () => 30000 * pulseScale,
          getFillColor: (p) => {
            const c = colourFor(p);
            return [c[0], c[1], c[2], 40] as [number, number, number, number];
          },
          radiusUnits: 'meters',
          radiusMinPixels: 14,
          radiusMaxPixels: 80,
          stroked: false,
          pickable: false,
          updateTriggers: { getRadius: pulse },
        }),
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
          radiusMinPixels: 6,
          // Uniform base-dot cap (Slice 25): 24px, matches Poverty.
          radiusMaxPixels: 24,
          stroked: true,
          pickable: true,
        }),
        new TextLayer<PositionedEvent>({
          id: 'shock-event-labels',
          data: positioned,
          getPosition: (p) => p.position,
          getText: (p) => {
            const icon = p.event_type === 'flood' ? '🌊' : '🔥';
            const label = p.lga ?? tenant.name;
            return `${icon} ${label} · ${p.severity}`;
          },
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
  }, [positioned, tenant.name, pulse]);

  const floodCount = positioned.filter((p) => p.event_type === 'flood').length;
  const droughtCount = positioned.length - floodCount;

  return (
    <EBMap
      tenant={tenant}
      layers={layers}
      getTooltip={tooltipFor}
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
