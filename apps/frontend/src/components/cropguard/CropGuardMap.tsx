'use client';

import { useEffect, useMemo, useState } from 'react';

import EBMap from '@/components/map/EBMap';
import { haloRadiusPx, haloRows } from '@/components/map/halo';
import type { Tenant } from '@/data/tenants';
import { formatLatLon } from '@/lib/display';
import type { CropPredictionRow } from '@/hooks/useCropPredictions';


/** Disease severity → red ramp; healthy → green. */
function colourFor(row: CropPredictionRow): [number, number, number, number] {
  const isHealthy = row.predicted_class.endsWith('_healthy');
  if (isHealthy) return [82, 183, 136, 220];
  if (row.prediction >= 0.80) return [255, 69, 0, 230];     // critical
  if (row.prediction >= 0.65) return [255, 140, 0, 220];    // high
  return [240, 175, 60, 220];                                // medium
}


function hashString(s: string): number {
  let h = 5381;
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

/**
 * Deterministic position fallback when a prediction row has no lat/lon
 * attached. Jitter is hashed from the prediction id so the same row
 * always lands at the same fake-coord. Marked clearly via
 * `synthetic_location` in the consumer.
 */
function syntheticPosition(
  id: string,
  centroid: [number, number],
): [number, number] {
  const h = hashString(id);
  const angle = ((h % 360) * Math.PI) / 180;
  const radius = 0.25 + ((h >> 8) % 60) / 100;  // 0.25..0.85 degrees
  return [
    centroid[0] + Math.cos(angle) * radius,
    centroid[1] + Math.sin(angle) * radius * 0.85,
  ];
}


export interface PositionedPrediction extends CropPredictionRow {
  /** Always set — real coords when row carries them, synthesised otherwise. */
  position: [number, number];
  synthetic_location: boolean;
}


/** Hover-card text for a prediction marker (Slice 25).
 *  Leads with the target area (LGA + coordinates) so an authority reading the
 *  halo knows exactly where to deploy. */
function tooltipFor(obj: unknown): string | null {
  const p = obj as PositionedPrediction;
  if (!p?.predicted_class) return null;
  const [lon, lat] = p.position;
  const lines = [
    p.predicted_class.replace(/_/g, ' '),
    `Target area: ${p.lga ?? '—'}`,
    `Coordinates: ${formatLatLon(lat, lon)}`,
    `Disease prob: ${(p.prediction * 100).toFixed(0)}% · Confidence: ${(p.confidence * 100).toFixed(0)}%`,
  ];
  if (p.requires_human_review) lines.push('Flagged for human review');
  if (p.synthetic_location) lines.push('⚠ synthesised position (no GPS)');
  return lines.join('\n');
}

/** True for a disease prediction the analyst should look at first. */
function isHighSeverity(p: PositionedPrediction): boolean {
  return !p.predicted_class.endsWith('_healthy') && p.prediction >= 0.80;
}

/** Halo-fallback ranking: healthy rows sink, diseased rows sort by probability. */
function severityFor(p: PositionedPrediction): number {
  return p.predicted_class.endsWith('_healthy') ? -1 : p.prediction;
}


interface Props {
  tenant: Tenant;
  predictions: CropPredictionRow[];
}


export default function CropGuardMap({ tenant, predictions }: Props) {
  const positioned = useMemo<PositionedPrediction[]>(
    () => predictions.map((row) => {
      const realCoord = row.location;
      if (realCoord) {
        return {
          ...row,
          position: [realCoord.lon, realCoord.lat],
          synthetic_location: false,
        };
      }
      return {
        ...row,
        position: syntheticPosition(row.id, tenant.centroid),
        synthetic_location: true,
      };
    }),
    [predictions, tenant.centroid],
  );

  const [layers, setLayers] = useState<unknown[]>([]);
  const [pulse, setPulse] = useState(0);

  // Heartbeat — pulses high-severity disease detections (prob >= 0.80),
  // falling back to the most-likely-diseased few so every tenant with
  // predictions shows a uniform halo (Slice 25).
  const hasAttention = positioned.length > 0;
  useEffect(() => {
    if (!hasAttention) return;
    const id = window.setInterval(() => setPulse((p) => (p + 2) % 1000), 120);
    return () => window.clearInterval(id);
  }, [hasAttention]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [{ ScatterplotLayer }, { HeatmapLayer }] = await Promise.all([
        import('@deck.gl/layers'),
        import('@deck.gl/aggregation-layers'),
      ]);
      if (cancelled) return;

      const diseasePoints = positioned.filter(
        (p) => !p.predicted_class.endsWith('_healthy'),
      );
      const pulseRows = haloRows(positioned, isHighSeverity, severityFor);

      const built: unknown[] = [
        // Disease-density heatmap.
        new HeatmapLayer<PositionedPrediction>({
          id: 'cropguard-disease-heat',
          data: diseasePoints,
          getPosition: (p) => p.position,
          getWeight: (p) => p.prediction * 2,
          radiusPixels: 70,
          intensity: 1.4,
          threshold: 0.05,
          colorRange: [
            [82, 183, 136, 0],
            [240, 175, 60],
            [255, 140, 0],
            [255, 69, 0],
          ],
        }),
        // Pulse halo on high-severity disease.
        new ScatterplotLayer<PositionedPrediction>({
          id: 'cropguard-pulse',
          data: pulseRows,
          getPosition: (p) => p.position,
          // Uniform pixel-pulse halo (Slice 25 fix): matches Poverty.
          getRadius: () => haloRadiusPx(pulse),
          getFillColor: [255, 69, 0, 40],
          radiusUnits: 'pixels',
          stroked: false,
          // Pickable so hovering the halo ring (not just the centre pin)
          // surfaces the LGA + coordinates tooltip.
          pickable: true,
          updateTriggers: { getRadius: pulse },
        }),
        // Per-prediction pin.
        new ScatterplotLayer<PositionedPrediction>({
          id: 'cropguard-predictions',
          data: positioned,
          getPosition: (p) => p.position,
          // Tidy meter scale (Slice 25): comparable band to Poverty.
          getRadius: (p) => 4000 + p.confidence * 8000,
          getFillColor: (p) => colourFor(p),
          getLineColor: (p) =>
            p.synthetic_location ? [180, 180, 180, 220] : [255, 255, 255, 220],
          lineWidthMinPixels: 1.5,
          radiusUnits: 'meters',
          radiusMinPixels: 6,
          // Uniform base-dot cap (Slice 25): 24px, matches Poverty.
          radiusMaxPixels: 24,
          stroked: true,
          pickable: true,
        }),
      ];
      setLayers(built);
    })();
    return () => { cancelled = true; };
  }, [positioned, pulse]);

  const realCount = positioned.filter((p) => !p.synthetic_location).length;
  const syntheticCount = positioned.length - realCount;
  const diseaseCount = positioned.filter(
    (p) => !p.predicted_class.endsWith('_healthy'),
  ).length;

  return (
    <EBMap
      tenant={tenant}
      layers={layers}
      getTooltip={tooltipFor}
      ariaLabel={`CropGuard predictions map — ${tenant.name}`}
      legend={
        <>
          <div className="fp-legend-item">
            <div className="fp-legend-dot fp-legend-dot--critical" />
            Disease (high severity)
          </div>
          <div className="fp-legend-item">
            <div className="fp-legend-dot fp-legend-dot--high" />
            Disease (medium)
          </div>
          <div className="fp-legend-item">
            <div className="fp-legend-dot fp-legend-dot--resolved" />
            Healthy
          </div>
        </>
      }
      overlay={
        <>
          {positioned.length} predictions · {diseaseCount} disease-flagged<br />
          {realCount > 0 && <>{realCount} geolocated</>}
          {syntheticCount > 0 && (
            <>
              {realCount > 0 ? ' · ' : ''}
              <span className="fp-map-overlay__warn">
                {syntheticCount} synthesised position{syntheticCount === 1 ? '' : 's'}
              </span>
            </>
          )}<br />
          Sources: ResNet-50 + uploaded leaf photos
        </>
      }
    />
  );
}
