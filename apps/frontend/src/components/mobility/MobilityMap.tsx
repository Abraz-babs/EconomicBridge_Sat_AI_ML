'use client';

import { useEffect, useMemo, useState } from 'react';

import EBMap from '@/components/map/EBMap';
import { haloRadiusPx, haloRows } from '@/components/map/halo';
import type { Tenant } from '@/data/tenants';
import { formatIncome, type MobilityIndicatorRow } from '@/hooks/useEconomicMobility';


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


/** Hover-card text for an LGA marker (Slice 25). */
function tooltipFor(obj: unknown, country: string): string | null {
  const r = obj as MobilityIndicatorRow;
  if (!r?.lga) return null;
  return [
    r.lga,
    `Cost-of-living index: ${r.cost_of_living_index.toFixed(1)} (${r.cost_of_living_band.replace('_', ' ')})`,
    `Avg household income: ${formatIncome(r.avg_household_income_usd, country)}/mo`,
    `Opportunity: ${(r.income_opportunity_score * 100).toFixed(0)}% · Capacity: ${(r.displacement_capacity_index * 100).toFixed(0)}%`,
    `Source: ${r.source}`,
  ].join('\n');
}


interface Props {
  tenant: Tenant;
  indicators: MobilityIndicatorRow[];
}


export default function MobilityMap({ tenant, indicators }: Props) {
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

  // Heartbeat — pulses premium-COL LGAs, falling back to the priciest few so
  // every tenant with data shows a uniform halo (Slice 25 follow-up).
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
      (p) => p.cost_of_living_band === 'premium',
      (p) => p.cost_of_living_index,
    ),
    [indicators],
  );

  const layers = useMemo<unknown[]>(() => {
    if (!layerKit) return [];
    const { ScatterplotLayer, TextLayer } = layerKit;
    return [
        new ScatterplotLayer<MobilityIndicatorRow>({
          id: 'mobility-lga-pulse',
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
        new ScatterplotLayer<MobilityIndicatorRow>({
          id: 'mobility-lga-col',
          data: indicators,
          getPosition: (p) => [p.location.lon, p.location.lat],
          // Radius scales with population so denser LGAs read louder.
          // Tidy meter scale (Slice 25): matches Poverty so dots stay small.
          getRadius: (p) => 4000 + Math.sqrt(p.population) * 40,
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
  }, [layerKit, indicators, pulseRows, pulse]);

  const premium = indicators.filter((i) => i.cost_of_living_band === 'premium').length;
  const below = indicators.filter((i) => i.cost_of_living_band === 'below_avg').length;

  return (
    <EBMap
      tenant={tenant}
      layers={layers}
      getTooltip={(obj) => tooltipFor(obj, tenant.country)}
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
