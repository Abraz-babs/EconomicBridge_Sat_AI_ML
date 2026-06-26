'use client';

import { useMemo, useState } from 'react';
import { ScatterplotLayer } from '@deck.gl/layers';

import EBMap from '@/components/map/EBMap';
import { useTenant } from '@/context/TenantContext';
import { useFarmCheck, type FarmHealth } from '@/hooks/useFarmCheck';

const HEALTH_STYLE: Record<FarmHealth, { label: string; color: string }> = {
  healthy: { label: 'Healthy', color: '#22c55e' },
  moderate: { label: 'Moderate', color: '#84cc16' },
  stressed: { label: 'Stressed', color: '#eab308' },
  poor: { label: 'Poor', color: '#ef4444' },
  bare: { label: 'Bare soil', color: '#9ca3af' },
  unknown: { label: 'No reading', color: '#9ca3af' },
};

const SIZE_OPTIONS = [
  { label: 'Small (~2.5 ha)', half: 80 },
  { label: 'Medium (~6 ha)', half: 120 },
  { label: 'Large (~25 ha)', half: 250 },
];

// Match the theme (light/cream): --ink text on --surface, like .fp-tenant-select.
const inputStyle: React.CSSProperties = {
  background: 'var(--surface)',
  border: '1px solid var(--border2)',
  borderRadius: '3px',
  color: 'var(--ink)',
  padding: '5px 10px',
  fontSize: '12px',
  fontFamily: "'DM Mono', monospace",
  width: '120px',
};

export default function FarmCheckPanel() {
  const { activeTenant } = useTenant();
  const [lat, setLat] = useState('9.0610');
  const [lon, setLon] = useState('7.4910');
  const [crop, setCrop] = useState('maize');
  const [halfM, setHalfM] = useState(120);
  const check = useFarmCheck();

  const latN = Number(lat);
  const lonN = Number(lon);
  const coordsValid =
    Number.isFinite(latN) && Number.isFinite(lonN) &&
    latN >= -90 && latN <= 90 && lonN >= -180 && lonN <= 180;

  const layers = useMemo(() => {
    if (!coordsValid) return [];
    return [
      new ScatterplotLayer({
        id: 'farm-pin',
        data: [{ position: [lonN, latN] as [number, number] }],
        getPosition: (d: { position: [number, number] }) => d.position,
        getFillColor: [232, 121, 26],
        getLineColor: [255, 255, 255],
        stroked: true,
        lineWidthMinPixels: 2,
        radiusUnits: 'pixels',
        getRadius: 8,
        radiusMinPixels: 8,
      }),
    ];
  }, [coordsValid, lonN, latN]);

  const onMapClick = (lng: number, la: number) => {
    setLon(lng.toFixed(4));
    setLat(la.toFixed(4));
  };

  const runCheck = () => {
    if (!coordsValid || !crop.trim()) return;
    check.mutate({ lat: latN, lon: lonN, crop: crop.trim(), half_m: halfM });
  };

  const r = check.data;
  const hs = r ? HEALTH_STYLE[r.health] : null;

  return (
    <div className="sb-table-wrap" style={{ marginTop: '16px' }}>
      <div className="cg-section-header">Farm Check — pinpoint vegetation health</div>
      <div className="cg-subtitle" style={{ marginBottom: '10px' }}>
        Type a coordinate or click the map, choose the crop, and we read
        Sentinel-2 NDVI + Sentinel-1 SAR for that exact farm.
      </div>

      <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'flex-end', margin: '4px 0 12px' }}>
        <label style={{ fontSize: '12px' }}>
          <div className="fp-tenant-label">Latitude</div>
          <input style={inputStyle} value={lat} onChange={(e) => setLat(e.target.value)} inputMode="decimal" />
        </label>
        <label style={{ fontSize: '12px' }}>
          <div className="fp-tenant-label">Longitude</div>
          <input style={inputStyle} value={lon} onChange={(e) => setLon(e.target.value)} inputMode="decimal" />
        </label>
        <label style={{ fontSize: '12px' }}>
          <div className="fp-tenant-label">Crop</div>
          <input style={inputStyle} value={crop} onChange={(e) => setCrop(e.target.value)} placeholder="e.g. maize" />
        </label>
        <label style={{ fontSize: '12px' }}>
          <div className="fp-tenant-label">Farm size</div>
          <select className="fp-tenant-select" value={halfM} onChange={(e) => setHalfM(Number(e.target.value))}>
            {SIZE_OPTIONS.map((o) => (
              <option key={o.half} value={o.half}>{o.label}</option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="fp-refresh-btn"
          onClick={runCheck}
          disabled={!coordsValid || !crop.trim() || check.isPending}
        >
          {check.isPending ? 'Checking…' : 'Check farm'}
        </button>
      </div>

      <EBMap
        tenant={activeTenant}
        layers={layers}
        height="300px"
        zoom={12}
        ariaLabel="Farm check map — click to drop a pin"
        onMapClick={onMapClick}
        overlay={<span className="ev-map-meta">Click the map to drop a pin</span>}
      />

      {check.isError && (
        <div className="fp-alert-empty" style={{ marginTop: '10px' }}>
          Couldn&apos;t read this farm: {check.error.message}
        </div>
      )}

      {r && (
        <div
          style={{
            marginTop: '12px', padding: '12px 14px', borderRadius: '8px',
            background: 'rgba(255,255,255,0.04)',
            borderLeft: `4px solid ${hs?.color ?? '#9ca3af'}`,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <span style={{
              background: hs?.color, color: '#10130f', fontWeight: 700,
              fontSize: '12px', padding: '3px 10px', borderRadius: '12px',
            }}>{hs?.label}</span>
            <strong style={{ fontSize: '15px' }}>
              NDVI {r.ndvi != null ? r.ndvi.toFixed(2) : '—'}
            </strong>
            <span className="ev-map-meta">
              {r.crop} · {r.ndvi_date ?? 'no optical pass'} · {r.area_ha} ha · ~{r.resolution_m} m/px
            </span>
          </div>
          <div style={{ margin: '8px 0', fontSize: '13.5px' }}>{r.verdict}</div>
          <div className="ev-map-meta">
            All-weather SAR: {r.sar_db != null ? `${r.sar_db} dB` : '—'}
            {r.sar_date ? ` (${r.sar_date})` : ''}
            {r.trend.length > 1 && (
              <> · NDVI trend: {r.trend.map((t) => t.ndvi.toFixed(2)).join(' → ')}</>
            )}
          </div>
          <div className="ev-map-meta" style={{ marginTop: '8px', opacity: 0.85 }}>{r.note}</div>
        </div>
      )}
    </div>
  );
}
