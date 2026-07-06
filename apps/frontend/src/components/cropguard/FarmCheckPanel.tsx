'use client';

import { useMemo, useState } from 'react';
import { PolygonLayer, ScatterplotLayer } from '@deck.gl/layers';

import EBMap from '@/components/map/EBMap';
import { useTenant } from '@/context/TenantContext';
import { useTenantLgas } from '@/hooks/useCropPredictions';
import {
  useDeleteFarmCheck,
  useFarmCheck,
  useFarmCheckRecords,
  useSaveFarmCheck,
  type FarmHealth,
} from '@/hooks/useFarmCheck';

// Labelled satellite base so state/place names AND the real land are visible.
const FARM_MAP_STYLE = 'mapbox://styles/mapbox/satellite-streets-v12';
// Analysis precision = half the box side in metres. Tight isolates a single
// plot (best for ground-truthing one plantation); Standard averages a larger
// uniform field. The resulting hectares are reported back in the result.
const PRECISION_OPTIONS = [
  { label: 'Tight (~1.4 ha)', half: 60 },
  { label: 'Standard (~5.8 ha)', half: 120 },
];

const STRESS_STYLE: Record<string, { label: string; color: string }> = {
  none: { label: '✓ No stress signal', color: '#22c55e' },
  moderate: { label: '⚠ Mild decline — monitor', color: '#eab308' },
  high: { label: '⚠ Significant decline — investigate', color: '#ef4444' },
  unknown: { label: 'Stress: insufficient history', color: '#9ca3af' },
};

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
export function parseCoord(raw: string): number | null {
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

/** True when the reverse-geocoded place name does NOT sit in the selected
 *  pilot's state — the tell-tale of a mistyped coordinate (e.g. lat pasted
 *  into the longitude box lands 150 km away in the next state). */
export function pilotMismatch(placeName: string | null, pilotName: string): boolean {
  if (!placeName) return false;
  const token = pilotName.replace(/\s+State$/i, '').toLowerCase();
  const place = placeName.toLowerCase();
  // FCT appears in Mapbox names as "Federal Capital Territory" or "Abuja".
  if (token.includes('federal capital')) {
    return !place.includes('federal capital') && !place.includes('abuja');
  }
  return !place.includes(token);
}

/** Reverse-geocode a coordinate to a place name (village / area / district)
 *  via Mapbox, so the result reads "near Kuje, FCT" instead of bare numbers. */
export async function fetchPlaceName(lon: number, lat: number): Promise<string | null> {
  const token = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;
  if (!token) return null;
  try {
    const res = await fetch(
      `https://api.mapbox.com/geocoding/v5/mapbox.places/${lon},${lat}.json` +
        `?access_token=${token}&types=neighborhood,locality,place,district,region&limit=1`,
    );
    if (!res.ok) return null;
    const j = (await res.json()) as { features?: { place_name?: string }[] };
    return j.features?.[0]?.place_name ?? null;
  } catch {
    return null;
  }
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
  const [lga, setLga] = useState('');
  const [owner, setOwner] = useState('');
  const [halfM, setHalfM] = useState(60); // default Tight, for single-plot accuracy
  const [focus, setFocus] = useState<{ lng: number; lat: number; zoom: number } | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [placeName, setPlaceName] = useState<string | null>(null);
  const [showRecords, setShowRecords] = useState(true);
  const [recordSearch, setRecordSearch] = useState('');
  const check = useFarmCheck();
  // Records save + recall to the SELECTED pilot's schema (the state checked).
  const lgasQuery = useTenantLgas(pilotId);
  const save = useSaveFarmCheck(pilotId);
  const records = useFarmCheckRecords(pilotId);
  const removeRecord = useDeleteFarmCheck(pilotId);
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
    save.reset();
    setLga('');
    setOwner('');
    setFocus(null);
    setPlaceName(null);
    setSelectedDate(null);
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
    if (!coordsValid) return;
    save.reset();
    check.mutate(
      // Blank crop → 'general': the satellite grades vigour on its own.
      { lat: latN, lon: lonN, crop: crop.trim() || 'general', half_m: halfM },
      {
        onSuccess: (data) => {
          // Fly to the exact analysed coordinate; default the pass selector to
          // the latest usable pass; reverse-geocode the place name.
          setFocus({ lng: data.lon, lat: data.lat, zoom: 15 });
          setSelectedDate(data.ndvi_date);
          setPlaceName(null);
          fetchPlaceName(data.lon, data.lat).then(setPlaceName).catch(() => {});
        },
      },
    );
  };

  const saveRecord = () => {
    if (!r) return;
    save.mutate({ ...r, lga: lga || undefined, owner_name: owner.trim() || undefined });
  };

  // The pass currently shown (selected from the history, default = latest).
  const passes = r?.passes ?? [];
  const shown = passes.find((p) => p.date === selectedDate) ?? null;
  const dHealth = shown?.health ?? r?.health;
  const dNdvi = shown ? shown.ndvi : r?.ndvi ?? null;
  const dVerdict = shown?.verdict ?? r?.verdict ?? '';
  const dDate = shown?.date ?? r?.ndvi_date ?? null;
  const dCloud = shown?.cloud_affected ?? false;
  const hs = dHealth ? HEALTH_STYLE[dHealth] : null;

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
          <div className="fp-tenant-label">Crop (optional)</div>
          <input style={inputStyle} value={crop} onChange={(e) => setCrop(e.target.value)} placeholder="blank = general" />
        </label>
        <label style={{ fontSize: '12px' }}>
          <div className="fp-tenant-label">Farm owner (for the record)</div>
          <input style={inputStyle} value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="full name" />
        </label>
        <label style={{ fontSize: '12px' }}>
          <div className="fp-tenant-label">LGA (for the record)</div>
          <select className="fp-tenant-select" value={lga} onChange={(e) => setLga(e.target.value)}>
            <option value="">{lgasQuery.isLoading ? 'Loading…' : 'Select LGA…'}</option>
            {(lgasQuery.data ?? []).map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>
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
          disabled={!coordsValid || check.isPending}
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
          {placeName && (
            <div style={{ fontSize: '13px', fontWeight: 600, marginBottom: '8px' }}>
              📍 {placeName}
            </div>
          )}

          {placeName && pilotMismatch(placeName, pilot.name) && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap',
              margin: '0 0 10px', padding: '7px 10px', borderRadius: '6px',
              background: '#ef44441f', border: '1px solid #ef444466',
              fontSize: '12.5px',
            }}>
              <strong style={{ color: '#ef4444' }}>⚠ Coordinate outside {pilot.name}</strong>
              <span className="ev-map-meta">
                This point reverse-geocodes to “{placeName}” — check the latitude/longitude
                (a swapped or mistyped digit lands in the wrong state) before saving.
              </span>
            </div>
          )}

          {passes.length > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px', flexWrap: 'wrap' }}>
              <span className="fp-tenant-label" style={{ margin: 0 }}>Satellite pass</span>
              <select
                className="fp-tenant-select"
                value={selectedDate ?? ''}
                onChange={(e) => setSelectedDate(e.target.value)}
              >
                {[...passes].reverse().map((p) => (
                  <option key={p.date} value={p.date}>
                    {p.date} — {HEALTH_STYLE[p.health].label} (NDVI {p.ndvi.toFixed(2)})
                    {p.cloud_affected ? ' ⚠ cloudy' : ''}
                  </option>
                ))}
              </select>
              <span className="ev-map-meta">
                {passes.length} pass{passes.length > 1 ? 'es' : ''} in 60 days — scrub the field&apos;s history
              </span>
            </div>
          )}

          {r.stress && r.stress.level !== 'unknown' && (() => {
            const ss = STRESS_STYLE[r.stress.level] ?? STRESS_STYLE.unknown;
            return (
              <div style={{
                display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap',
                margin: '0 0 10px', padding: '7px 10px', borderRadius: '6px',
                background: `${ss.color}1f`, border: `1px solid ${ss.color}66`,
              }}>
                <strong style={{ color: ss.color, fontSize: '12.5px' }}>{ss.label}</strong>
                <span className="ev-map-meta">Early-warning · {r.stress.message}</span>
              </div>
            );
          })()}

          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <span style={{
              background: hs?.color, color: '#10130f', fontWeight: 700,
              fontSize: '12px', padding: '3px 10px', borderRadius: '12px',
            }}>{hs?.label}</span>
            <strong style={{ fontSize: '15px' }}>
              NDVI {dNdvi != null ? dNdvi.toFixed(2) : '—'}
            </strong>
            <span className="ev-map-meta">
              {r.crop === 'general' ? 'General (no crop)' : r.crop} · {dDate ?? 'no optical pass'}{dCloud ? ' · partly cloud-affected' : ''}
            </span>
          </div>
          <div style={{ margin: '8px 0', fontSize: '13.5px' }}>{dVerdict}</div>
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

          {/* Keep this reading as a recallable field record. */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', marginTop: '10px' }}>
            <button
              type="button"
              className="fp-refresh-btn"
              onClick={saveRecord}
              disabled={save.isPending || save.isSuccess}
            >
              {save.isPending ? 'Saving…' : save.isSuccess ? '✓ Saved' : 'Save to records'}
            </button>
            {save.isSuccess ? (
              <span className="ev-map-meta" style={{ color: '#16a34a' }}>
                Saved to {pilot.name}
                {owner.trim() ? ` · ${owner.trim()}` : ''}{lga ? ` · ${lga}` : ''} · {r.crop} — recall it below.
              </span>
            ) : (
              <span className="ev-map-meta">
                {lga ? `Records to ${pilot.name} · ${lga}` : `Pick an LGA to tag the record (optional)`}
              </span>
            )}
            {save.isError && (
              <span className="ev-map-meta" style={{ color: '#b45309' }}>
                Couldn&apos;t save: {save.error.message}
              </span>
            )}
          </div>
        </div>
      )}

      {(records.data?.length ?? 0) > 0 && (() => {
        const q = recordSearch.trim().toLowerCase();
        const all = records.data ?? [];
        // Type "Kuje", an owner's name, a crop, or part of a coordinate to filter.
        const visible = q
          ? all.filter((rec) =>
              [rec.owner_name, rec.lga, rec.crop, rec.health,
               `${rec.lat.toFixed(4)}, ${rec.lon.toFixed(4)}`]
                .filter(Boolean)
                .some((v) => String(v).toLowerCase().includes(q)))
          : all;
        return (
          <div style={{ marginTop: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
              <div className="cg-section-header" style={{ marginBottom: 0 }}>
                Saved field checks — {pilot.name} ({all.length})
              </div>
              <button
                type="button"
                className="fp-refresh-btn"
                onClick={() => setShowRecords((s) => !s)}
              >
                {showRecords ? 'Hide records' : 'Show records'}
              </button>
              {showRecords && (
                <input
                  style={{ ...inputStyle, width: '190px' }}
                  value={recordSearch}
                  onChange={(e) => setRecordSearch(e.target.value)}
                  placeholder="Search: Kuje, a name, maize…"
                  aria-label="Search saved farm checks"
                />
              )}
            </div>
            {showRecords && (
              <>
                <div className="cg-subtitle" style={{ margin: '6px 0 8px' }}>
                  Recalled satellite Farm Checks for this state, newest first
                  {q ? ` — ${visible.length} match${visible.length === 1 ? '' : 'es'}` : ''}.
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {visible.map((rec) => {
                    const rhs = HEALTH_STYLE[rec.health] ?? HEALTH_STYLE.unknown;
                    return (
                      <div
                        key={rec.id}
                        style={{
                          display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap',
                          padding: '7px 10px', borderRadius: '6px', background: 'rgba(0,0,0,0.03)',
                          borderLeft: `3px solid ${rhs.color}`, fontSize: '12.5px',
                        }}
                      >
                        <span style={{
                          background: rhs.color, color: '#10130f', fontWeight: 700,
                          fontSize: '11px', padding: '2px 8px', borderRadius: '10px',
                        }}>{rhs.label}</span>
                        {rec.owner_name && <strong>{rec.owner_name}</strong>}
                        <span>{rec.crop === 'general' ? 'General' : rec.crop}</span>
                        <span>NDVI {rec.ndvi != null ? rec.ndvi.toFixed(2) : '—'}</span>
                        {rec.stress && rec.stress.level !== 'none' && rec.stress.level !== 'unknown' && (
                          <span style={{ color: STRESS_STYLE[rec.stress.level]?.color }}>
                            {STRESS_STYLE[rec.stress.level]?.label}
                          </span>
                        )}
                        <span className="ev-map-meta">
                          📍 {[rec.lga, `${rec.lat.toFixed(4)}, ${rec.lon.toFixed(4)}`].filter(Boolean).join(' · ')}
                          {rec.ndvi_date ? ` · ${rec.ndvi_date}` : ''} · saved {rec.created_at.slice(0, 10)}
                        </span>
                        <button
                          type="button"
                          onClick={() => {
                            if (window.confirm(
                              `Remove this record${rec.owner_name ? ` (${rec.owner_name})` : ''}?`,
                            )) removeRecord.mutate(rec.id);
                          }}
                          disabled={removeRecord.isPending}
                          title="Remove from records"
                          aria-label="Remove this saved farm check"
                          style={{
                            marginLeft: 'auto', background: 'transparent',
                            border: '1px solid var(--border2)', borderRadius: '4px',
                            color: '#ef4444', cursor: 'pointer', fontSize: '11px',
                            padding: '2px 8px',
                          }}
                        >
                          ✕ Remove
                        </button>
                      </div>
                    );
                  })}
                  {visible.length === 0 && (
                    <div className="fp-alert-empty">No saved checks match “{recordSearch}”.</div>
                  )}
                </div>
              </>
            )}
          </div>
        );
      })()}
    </div>
  );
}
