'use client';

import { useMemo, useState } from 'react';
import { PolygonLayer, ScatterplotLayer } from '@deck.gl/layers';

import EBMap from '@/components/map/EBMap';
import { useTenant } from '@/context/TenantContext';
import { useFarmCheck, type FarmHealth } from '@/hooks/useFarmCheck';

// Labelled satellite base so state/place names AND the real land are visible.
const FARM_MAP_STYLE = 'mapbox://styles/mapbox/satellite-streets-v12';
// Analysis precision = half the box side in metres. Tight isolates a single
// plot (best for ground-truthing one plantation); Standard averages a larger
// uniform field. The resulting hectares are reported back in the result.
const PRECISION_OPTIONS = [
  { label: 'Tight (~1.4 ha)', half: 60 },
  { label: 'Standard (~5.8 ha)', half: 120 },
];

const HEALTH_STYLE: Record<FarmHealth, { label: string; color: string }> = {
  healthy: { label: 'Healthy', color: '#22c55e' },
  moderate: { label: 'Moderate', color: '#84cc16' },
  stressed: { label: 'Stressed', color: '#eab308' },
  poor: { label: 'Poor', color: '#ef4444' },
  bare: { label: 'Bare soil', color: '#9ca3af' },
  unknown: { label: 'No reading', color: '#9ca3af' },
};

/** The exact analysed box (a square of side 2*halfM m) as a [lng,lat] ring —
 *  matches sources/farm_check.bbox_around so the map shows precisely the ground
 *  the NDVI reading covers (for field ground-truthing). */
function boxRing(lat: number, lon: number, halfM: number): [number, number][] {
  const dlat = halfM / 111_320;
  const dlon = halfM / (111_320 * Math.cos((lat * Math.PI) / 180));
  return [
    [lon - dlon, lat - dlat], [lon + dlon, lat - dlat],
    [lon + dlon, lat + dlat], [lon - dlon, lat + dlat], [lon - dlon, lat - dlat],
  ];
}

/** Parse a coordinate given in decimal degrees ("9.2616", "-2.33") OR DMS
 *  ("9°15'41.6\"N", "7 21 21.4", "2°19'W") into decimal degrees. Returns null
 *  if it can't be parsed. Lets users paste straight from Google Maps / GPS. */
function parseCoord(raw: string): number | null {
  const s = raw.trim();
  if (!s) return null;
  if (/^[+-]?\d+(\.\d+)?$/.test(s)) return Number(s); // plain decimal degrees
  const nums = s.match(/\d+(?:\.\d+)?/g); // degrees, minutes, seconds
  if (!nums || nums.length === 0) return null;
  const deg = parseFloat(nums[0]);
  const min = nums[1] ? parseFloat(nums[1]) : 0;
  const sec = nums[2] ? parseFloat(nums[2]) : 0;
  if (min >= 60 || sec >= 60) return null;
  let val = deg + min / 60 + sec / 3600;
  if (/^-/.test(s) || /[SWsw]/.test(s)) val = -val; // hemisphere / sign
  return val;
}

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
  const { activeTenant, pilotTenants } = useTenant();
  const [pilotId, setPilotId] = useState(activeTenant.id);
  const [lat, setLat] = useState(() => activeTenant.centroid[1].toFixed(4));
  const [lon, setLon] = useState(() => activeTenant.centroid[0].toFixed(4));
  const [crop, setCrop] = useState('maize');
  const [halfM, setHalfM] = useState(60); // default Tight, for single-plot accuracy
  const [focus, setFocus] = useState<{ lng: number; lat: number; zoom: number } | null>(null);
  const check = useFarmCheck();
  const r = check.data;

  const pilot = pilotTenants.find((t) => t.id === pilotId) ?? activeTenant;
  const parsedLat = parseCoord(lat);
  const parsedLon = parseCoord(lon);
  const coordsValid =
    parsedLat != null && parsedLon != null &&
    parsedLat >= -90 && parsedLat <= 90 && parsedLon >= -180 && parsedLon <= 180;
  const latN = parsedLat ?? 0;
  const lonN = parsedLon ?? 0;

  const onPilotChange = (id: string) => {
    setPilotId(id);
    const t = pilotTenants.find((x) => x.id === id);
    if (t) {
      setLon(t.centroid[0].toFixed(4));
      setLat(t.centroid[1].toFixed(4));
    }
    check.reset();
    setFocus(null);
  };

  const layers = useMemo(() => {
    const ls: unknown[] = [];
    // Analysed-area box at the RESULT coordinate — the exact ground the NDVI
    // reading covers (shown after a check, for field ground-truthing).
    if (r) {
      // Derive the box half-side from the analysed area so the drawn box
      // exactly matches what was measured, regardless of the current toggle.
      const halfFromArea = Math.sqrt(r.area_ha * 10_000) / 2;
      ls.push(
        new PolygonLayer({
          id: 'farm-box',
          data: [{ polygon: boxRing(r.lat, r.lon, halfFromArea) }],
          getPolygon: (d: { polygon: [number, number][] }) => d.polygon,
          stroked: true,
          filled: true,
          getFillColor: [232, 121, 26, 45],
          getLineColor: [232, 121, 26, 230],
          getLineWidth: 2,
          lineWidthUnits: 'pixels',
        }),
      );
    }
    // Live pointer at the current input coordinate.
    if (coordsValid) {
      ls.push(
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
      );
    }
    return ls;
  }, [r, coordsValid, lonN, latN]);

  const onMapClick = (lng: number, la: number) => {
    setLon(lng.toFixed(4));
    setLat(la.toFixed(4));
  };

  const runCheck = () => {
    if (!coordsValid || !crop.trim()) return;
    check.mutate(
      { lat: latN, lon: lonN, crop: crop.trim(), half_m: halfM },
      {
        // Fly to the exact analysed coordinate so the pointer + area box are
        // centred and the ~5.76 ha box is visible at this zoom.
        onSuccess: (data) => setFocus({ lng: data.lon, lat: data.lat, zoom: 15 }),
      },
    );
  };

  const hs = r ? HEALTH_STYLE[r.health] : null;

  return (
    <div className="sb-table-wrap" style={{ marginTop: '16px' }}>
      <div className="cg-section-header">Farm Check — pinpoint vegetation health</div>
      <div className="cg-subtitle" style={{ marginBottom: '10px' }}>
        Pick a pilot, then type a coordinate or click the map to drop a pin and
        choose the crop. We read Sentinel-2 NDVI + Sentinel-1 SAR for that exact
        farm and report the area analysed.
      </div>

      <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'flex-end', margin: '4px 0 12px' }}>
        <label style={{ fontSize: '12px' }}>
          <div className="fp-tenant-label">Pilot</div>
          <select className="fp-tenant-select" value={pilotId} onChange={(e) => onPilotChange(e.target.value)}>
            {pilotTenants.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        </label>
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
          <div className="fp-tenant-label">Precision</div>
          <select className="fp-tenant-select" value={halfM} onChange={(e) => setHalfM(Number(e.target.value))}>
            {PRECISION_OPTIONS.map((o) => (
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

      <div className="ev-map-meta" style={{ marginBottom: '8px' }}>
        {coordsValid
          ? `Decimal: ${latN.toFixed(5)}, ${lonN.toFixed(5)} — accepts decimal (9.2616) or DMS (9°15'41.6"N)`
          : 'Enter a coordinate — decimal (9.2616) or DMS (9°15\'41.6"N) both work'}
      </div>

      <EBMap
        tenant={pilot}
        layers={layers}
        height="320px"
        zoom={9}
        mapStyle={FARM_MAP_STYLE}
        focus={focus}
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
            background: 'rgba(0,0,0,0.03)',
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
              {r.crop} · {r.ndvi_date ?? 'no optical pass'}
            </span>
          </div>
          <div style={{ margin: '8px 0', fontSize: '13.5px' }}>{r.verdict}</div>
          <div style={{ fontSize: '12.5px', marginBottom: '4px' }}>
            <strong>Area analysed: {r.area_ha} ha</strong>
            <span className="ev-map-meta"> · ~{r.resolution_m} m/pixel · {r.sample_count} pixels at {r.lat.toFixed(4)}, {r.lon.toFixed(4)}</span>
          </div>
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
