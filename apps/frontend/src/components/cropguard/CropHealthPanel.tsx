'use client';

import { useMemo } from 'react';
import { ScatterplotLayer } from '@deck.gl/layers';

import EBMap from '@/components/map/EBMap';
import { useTenant } from '@/context/TenantContext';
import { useCropHealth, type CropHealth, type CropHealthRow } from '@/hooks/useCropHealth';

const HEALTH_STYLE: Record<CropHealth, { label: string; rgb: [number, number, number] }> = {
  healthy: { label: 'Healthy', rgb: [34, 197, 94] },
  moderate: { label: 'Moderate', rgb: [163, 201, 86] },
  stressed: { label: 'Stressed', rgb: [234, 179, 8] },
  poor: { label: 'Poor', rgb: [239, 68, 68] },
  bare: { label: 'Bare soil', rgb: [148, 163, 184] },
  unknown: { label: 'No reading', rgb: [148, 163, 184] },
};

const ORDER: CropHealth[] = ['healthy', 'moderate', 'stressed', 'poor', 'bare'];

export default function CropHealthPanel() {
  const { activeTenantId, activeTenant } = useTenant();
  const { data, isLoading } = useCropHealth(activeTenantId);
  const rows = useMemo(() => data ?? [], [data]);

  const layers = useMemo<unknown[]>(() => {
    if (!rows.length) return [];
    return [
      new ScatterplotLayer<CropHealthRow>({
        id: 'crop-health-lga',
        data: rows,
        getPosition: (r) => [r.lon, r.lat],
        getFillColor: (r) =>
          [...(HEALTH_STYLE[r.health]?.rgb ?? [148, 163, 184]), 225] as [number, number, number, number],
        getLineColor: [255, 255, 255, 200],
        lineWidthMinPixels: 1,
        radiusUnits: 'meters',
        getRadius: 7000,
        radiusMinPixels: 5,
        radiusMaxPixels: 16,
        stroked: true,
        pickable: true,
      }),
    ];
  }, [rows]);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of rows) c[r.health] = (c[r.health] ?? 0) + 1;
    return c;
  }, [rows]);

  const tooltip = (o: unknown): string | null => {
    const r = o as CropHealthRow;
    if (!r?.lga) return null;
    return [
      r.lga,
      `${HEALTH_STYLE[r.health]?.label ?? r.health} · NDVI ${r.ndvi != null ? r.ndvi.toFixed(2) : '—'}`,
      r.verdict,
    ].filter(Boolean).join('\n');
  };

  return (
    <div className="sb-table-wrap" style={{ marginTop: '16px' }}>
      <div className="cg-section-header">Statewide Crop Health — every LGA (Sentinel-2 NDVI)</div>
      <div className="cg-subtitle" style={{ marginBottom: '8px' }}>
        Each LGA&apos;s current vegetation health from live Sentinel-2 NDVI, refreshed
        on the satellite revisit. (Disease <em>diagnosis</em> is the leaf-photo /
        Farm Check layer above — satellite shows where stress is; a photo shows which disease.)
      </div>

      <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', margin: '4px 0 10px' }}>
        {ORDER.map((h) => (
          <span key={h} style={{ fontSize: '12px', display: 'inline-flex', alignItems: 'center', gap: '5px' }}>
            <span style={{ width: '10px', height: '10px', borderRadius: '50%', background: `rgb(${HEALTH_STYLE[h].rgb.join(',')})` }} />
            {HEALTH_STYLE[h].label}: <strong>{counts[h] ?? 0}</strong>
          </span>
        ))}
        <span className="ev-map-meta">{rows.length} LGAs covered</span>
      </div>

      {isLoading && <div className="fp-alert-empty">Loading crop health…</div>}
      {!isLoading && rows.length === 0 && (
        <div className="fp-alert-empty">
          No crop-health readings yet for {activeTenant.name}. The per-LGA NDVI sweep populates this.
        </div>
      )}
      {rows.length > 0 && (
        <EBMap
          tenant={activeTenant}
          layers={layers}
          height="360px"
          zoom={6}
          getTooltip={tooltip}
          ariaLabel={`Crop health by LGA — ${activeTenant.name}`}
        />
      )}
    </div>
  );
}
