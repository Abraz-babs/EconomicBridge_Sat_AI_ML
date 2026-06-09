'use client';

import { useEffect, useMemo, useState } from 'react';

import EBMap from '@/components/map/EBMap';
import { haloRadiusPx, haloRows } from '@/components/map/halo';
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


/** Hover-card text for an LGA marker (Slice 25). */
function tooltipFor(obj: unknown): string | null {
  const r = obj as SkillsIndicatorRow;
  if (!r?.lga) return null;
  return [
    `${r.lga} · ${r.connectivity_band.replace('_', ' ')}`,
    `Internet: ${r.internet_coverage_pct.toFixed(0)}% · Mobile: ${r.mobile_coverage_pct.toFixed(0)}%`,
    `Schools: ${r.school_count} (${r.school_density_per_10k.toFixed(1)}/10k youth)`,
    `Learning-gap index: ${r.learning_gap_index.toFixed(2)}`,
    `Source: ${r.source}`,
  ].join('\n');
}


interface Props {
  tenant: Tenant;
  indicators: SkillsIndicatorRow[];
}


export default function SkillsMap({ tenant, indicators }: Props) {
  const [pulse, setPulse] = useState(0);

  // deck.gl layer classes are code-split — load once, not on every pulse tick.
  const [layerKit, setLayerKit] = useState<{
    ScatterplotLayer: typeof import('@deck.gl/layers').ScatterplotLayer;
    TextLayer: typeof import('@deck.gl/layers').TextLayer;
  } | null>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const { ScatterplotLayer, TextLayer } = await import('@deck.gl/layers');
      if (!cancelled) setLayerKit({ ScatterplotLayer, TextLayer });
    })();
    return () => { cancelled = true; };
  }, []);

  // Heartbeat — drives the halo on the worst-served LGAs (no_signal OR
  // learning_gap_index >= 0.7). Both are the "top intervention priority"
  // rule the dashboard exposes via the worst_gap_lga aggregate.
  const hasAttention = indicators.length > 0;
  useEffect(() => {
    if (!hasAttention) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === 'visible') setPulse((p) => (p + 2) % 1000);
    }, 120);
    return () => window.clearInterval(id);
  }, [hasAttention]);

  // Stable halo rows — recomputed only when data changes, not each pulse.
  const pulseRows = useMemo(
    () => haloRows(
      indicators,
      (p) => p.connectivity_band === 'no_signal' || p.learning_gap_index >= 0.7,
      (p) => p.learning_gap_index,
    ),
    [indicators],
  );

  const layers = useMemo<unknown[]>(() => {
    if (!layerKit) return [];
    const { ScatterplotLayer, TextLayer } = layerKit;
    return [
        new ScatterplotLayer<SkillsIndicatorRow>({
          id: 'skills-lga-pulse',
          data: pulseRows,
          getPosition: (p) => [p.location.lon, p.location.lat],
          // Uniform pixel-pulse halo (Slice 25 fix): matches Poverty.
          getRadius: () => haloRadiusPx(pulse),
          getFillColor: [192, 60, 40, 40],
          radiusUnits: 'pixels',
          stroked: false,
          pickable: false,
          updateTriggers: { getRadius: pulse },
        }),
        new ScatterplotLayer<SkillsIndicatorRow>({
          id: 'skills-lga-connectivity',
          data: indicators,
          getPosition: (p) => [p.location.lon, p.location.lat],
          // Radius scales with youth pop — bigger circle = more young
          // people affected. Tidy meter scale (Slice 25): matches Poverty.
          getRadius: (p) => 4000 + Math.sqrt(p.youth_population) * 40,
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
  }, [layerKit, indicators, pulseRows, pulse]);

  const noSignal = indicators.filter((i) => i.connectivity_band === 'no_signal').length;
  const broadband = indicators.filter((i) => i.connectivity_band === 'broadband').length;

  return (
    <EBMap
      tenant={tenant}
      layers={layers}
      getTooltip={tooltipFor}
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
