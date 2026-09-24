'use client';

import { useEffect, useMemo, useState } from 'react';

import EBMap from '@/components/map/EBMap';
import type { Tenant } from '@/data/tenants';
import type { VillagePoint } from '@/hooks/useVillageLight';

/**
 * Night map — every real village of the state as a point: lit villages glow,
 * villages with no detectable light are rust rings that grow with the number
 * of people living there. Static layers (no pulse), so the deck.gl data
 * references stay stable and nothing re-aggregates on a heartbeat.
 */

export type Season = 'dry' | 'wet';

const UNLIT = 0;
const DIM = 1;
const LIT = 2;

function tooltipFor(obj: unknown): string | null {
  const p = obj as VillagePoint | undefined;
  if (!Array.isArray(p)) return null;
  const cls = p[2] === UNLIT ? 'No light at night' : p[2] === DIM ? 'Dim at night' : p[2] === LIT ? 'Lit at night' : 'No reading';
  return `${cls}\n~${Math.round(p[4]).toLocaleString()} people`;
}

interface Props {
  tenant: Tenant;
  points: VillagePoint[];
  season: Season;
  focus?: { lng: number; lat: number; zoom?: number } | null;
}

export default function VillageLightMap({ tenant, points, season, focus }: Props) {
  const [layers, setLayers] = useState<unknown[]>([]);
  const col = season === 'dry' ? 2 : 3;
  // Split once per data/season change — the layers key their buffers off these.
  const { unlit, glowing } = useMemo(() => ({
    unlit: points.filter((p) => p[col] === UNLIT),
    glowing: points.filter((p) => p[col] === DIM || p[col] === LIT),
  }), [points, col]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const { ScatterplotLayer } = await import('@deck.gl/layers');
      if (cancelled) return;
      setLayers([
        new ScatterplotLayer<VillagePoint>({
          id: 'village-unlit',
          data: unlit,
          getPosition: (p) => [p[0], p[1]],
          getRadius: (p) => Math.max(1.5, Math.min(8, Math.sqrt(p[4]) / 11)),
          radiusUnits: 'pixels',
          filled: false,
          stroked: true,
          getLineColor: [224, 87, 42, 150],
          lineWidthMinPixels: 1,
          pickable: true,
        }),
        new ScatterplotLayer<VillagePoint>({
          id: 'village-glow',
          data: glowing,
          getPosition: (p) => [p[0], p[1]],
          getRadius: (p) => (p[col] === LIT ? 7 : 5),
          radiusUnits: 'pixels',
          getFillColor: (p) => (p[col] === LIT ? [255, 214, 107, 60] : [232, 163, 60, 50]),
          pickable: false,
        }),
        new ScatterplotLayer<VillagePoint>({
          id: 'village-lit',
          data: glowing,
          getPosition: (p) => [p[0], p[1]],
          getRadius: 2,
          radiusUnits: 'pixels',
          getFillColor: (p) => (p[col] === LIT ? [255, 214, 107, 240] : [232, 163, 60, 230]),
          pickable: true,
        }),
      ]);
    })();
    return () => { cancelled = true; };
  }, [unlit, glowing, col]);

  return (
    <EBMap
      tenant={tenant}
      layers={layers}
      height="460px"
      focus={focus}
      getTooltip={tooltipFor}
      ariaLabel={`Night map of every named village — ${tenant.name}`}
      legend={
        <>
          <div className="fp-legend-item"><div className="fp-legend-dot" style={{ background: '#ffd66b', borderRadius: '50%' }} />Lit at night</div>
          <div className="fp-legend-item"><div className="fp-legend-dot" style={{ background: '#e8a33c', borderRadius: '50%' }} />Dim</div>
          <div className="fp-legend-item"><div className="fp-legend-dot" style={{ background: 'transparent', border: '1.5px solid #e0572a', borderRadius: '50%' }} />No light · size = people</div>
        </>
      }
      overlay={
        <>
          {points.length.toLocaleString()} named villages<br />
          {season === 'dry' ? 'Dry-season' : 'Wet-season'} night light · NASA VIIRS
        </>
      }
    />
  );
}
