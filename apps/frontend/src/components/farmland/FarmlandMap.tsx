'use client';

import { useEffect, useRef, useState } from 'react';

import { haloRadiusPx } from '@/components/map/halo';
import type { Tenant } from '@/data/tenants';
import { formatLatLon } from '@/lib/display';
import {
  hoursAgo,
  newestScene,
  useRecentImagery,
} from '@/hooks/useRecentImagery';
import {
  minutesUntil,
  pickLastPass,
  pickNextPass,
  useSatellitePasses,
} from '@/hooks/useSatellitePasses';

export type AlertSeverity = 'critical' | 'high' | 'medium' | 'low' | 'resolved';

export interface FarmlandAlertPoint {
  id: string;
  location: string;
  longitude: number;
  latitude: number;
  severity: AlertSeverity;
  confidence?: number;
  /** Optional extras shown in the hover tooltip. */
  lga?: string | null;
  zoneName?: string | null;
  alertType?: string | null;
  status?: string | null;
  affectedAreaHa?: number | null;
  livelihoodsAtRisk?: number | null;
  predictedBreachHours?: number | null;
  satelliteSource?: string | null;
}

const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;
const MAPBOX_STYLE = 'mapbox://styles/mapbox/dark-v11';

const SEVERITY_RGB: Record<AlertSeverity, [number, number, number]> = {
  critical: [255, 69, 0],
  high:     [255, 140, 0],
  medium:   [240, 175, 60],
  low:      [82, 183, 136],
  resolved: [82, 183, 136],
};

// Sentinel-1 SAR pass cadence (Copernicus): repeat every ~6 days per ROI, with
// an interleaved descending pass — use a deterministic-from-tenant offset so
// the "Next pass" indicator differs per tenant without being random.
function satelliteCadence(tenant: Tenant): {
  source: string;
  resolution: string;
  coverage: string;
  lastPassMin: number;
  nextPassMin: number;
} {
  const seed = tenant.id.split('').reduce((s, c) => s + c.charCodeAt(0), 0);
  const lastPassMin = 7 + (seed % 53);
  const nextPassMin = 30 + ((seed * 7) % 90);
  const coverage =
    tenant.type === 'ng_state'
      ? `Nigeria — ${tenant.name}`
      : tenant.type === 'ng_fct'
      ? 'Nigeria — FCT (Abuja)'
      : `ECOWAS — ${tenant.name}`;
  const source =
    tenant.conflict_risk === 'critical'
      ? 'Copernicus Sentinel-1 SAR + heat'
      : 'Copernicus Sentinel-1 SAR';
  return {
    source,
    resolution: '10 m / px',
    coverage,
    lastPassMin,
    nextPassMin,
  };
}

function sanitizeMapboxError(message: string | null | undefined): string | null {
  if (!message) return null;
  return message
    .replace(/access_token=[^&\s"']+/gi, 'access_token=[redacted]')
    .replace(/Bearer\s+pk\.[^\s"']+/gi, 'Bearer [redacted]');
}

interface Props {
  alerts: FarmlandAlertPoint[];
  activeLayer: 'heat' | 'ndvi' | 'sar' | 'boundary';
  tenant: Tenant;
}

interface HoverInfo {
  x: number;
  y: number;
  alert: FarmlandAlertPoint;
}

export default function FarmlandMap({ alerts, activeLayer, tenant }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<unknown>(null);
  const overlayRef = useRef<unknown>(null);
  const [mapStatus, setMapStatus] = useState<'loading' | 'ready' | 'error' | 'no-token'>(
    MAPBOX_TOKEN ? 'loading' : 'no-token'
  );
  const [mapError, setMapError] = useState<string | null>(null);
  const [hover, setHover] = useState<HoverInfo | null>(null);
  const [pulse, setPulse] = useState(0);

  // Wall-clock tick that drives the "next pass in X min" countdown. Updates
  // every 30s — finer than that is wasted re-renders for a minute-resolution
  // countdown. Initialised lazily so the first render is correct without a
  // setState-in-effect.
  const [nowMs, setNowMs] = useState<number>(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNowMs(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  // Live satellite-pass schedule from the ingestion service.
  const passesQuery = useSatellitePasses({ tenantId: tenant.id, days: 2 });
  const now = new Date(nowMs);
  const nextPass = pickNextPass(passesQuery.data?.passes, now);
  const lastPass = pickLastPass(passesQuery.data?.passes, now);

  // Live recency: latest optical (Sentinel-2 L2A) + radar (Sentinel-1 GRD)
  // scenes for this tenant. Backed by a 10-min server-side TTL cache so
  // refetches are cheap.
  const opticalQuery = useRecentImagery(tenant.id, 'sentinel-2-l2a');
  const sarQuery = useRecentImagery(tenant.id, 'sentinel-1-grd');
  const latestOptical = newestScene(opticalQuery.data?.scenes);
  const latestSar = newestScene(sarQuery.data?.scenes);

  // Heartbeat for the pulsing critical/high pins. 60ms = ~16fps, plenty for a
  // halo expand/shrink while keeping deck.gl re-renders cheap.
  useEffect(() => {
    if (mapStatus !== 'ready') return;
    const id = window.setInterval(() => setPulse((p) => (p + 2) % 1000), 120);
    return () => window.clearInterval(id);
  }, [mapStatus]);

  // One-time map init.
  useEffect(() => {
    if (!MAPBOX_TOKEN || !containerRef.current) return;
    let cancelled = false;

    (async () => {
      try {
        const [{ default: mapboxgl }, { MapboxOverlay }] = await Promise.all([
          import('mapbox-gl'),
          import('@deck.gl/mapbox'),
        ]);
        if (cancelled || !containerRef.current) return;

        mapboxgl.accessToken = MAPBOX_TOKEN;
        const map = new mapboxgl.Map({
          container: containerRef.current,
          style: MAPBOX_STYLE,
          center: tenant.centroid,
          zoom: 6,
          attributionControl: false,
        });
        mapRef.current = map;

        map.on('error', (e) => {
          if (cancelled) return;
          setMapStatus('error');
          setMapError(sanitizeMapboxError(e?.error?.message) ?? 'Mapbox error');
        });

        map.on('load', () => {
          if (cancelled) return;
          const overlay = new MapboxOverlay({ interleaved: false, layers: [] });
          map.addControl(overlay);
          overlayRef.current = overlay;
          setMapStatus('ready');
        });
      } catch (err) {
        if (cancelled) return;
        setMapStatus('error');
        setMapError(
          sanitizeMapboxError(err instanceof Error ? err.message : null) ??
            'Failed to load map'
        );
      }
    })();

    return () => {
      cancelled = true;
      const overlay = overlayRef.current as { finalize?: () => void } | null;
      overlay?.finalize?.();
      overlayRef.current = null;
      const map = mapRef.current as { remove?: () => void } | null;
      map?.remove?.();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Fly the map to the active tenant when it changes.
  useEffect(() => {
    if (mapStatus !== 'ready') return;
    const map = mapRef.current as
      | { flyTo: (o: { center: [number, number]; zoom: number; duration: number }) => void }
      | null;
    map?.flyTo({ center: tenant.centroid, zoom: 6, duration: 1200 });
    // Clear stale hover tooltip when the active tenant changes — the alert
    // it references no longer belongs to the displayed dataset. This is the
    // canonical "reset local state on a prop change" pattern.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setHover(null);
  }, [tenant.id, tenant.centroid, mapStatus]);

  // Layer composition — recomputed on layer/data/pulse change.
  useEffect(() => {
    if (mapStatus !== 'ready') return;
    const overlay = overlayRef.current as
      | { setProps: (p: { layers: unknown[] }) => void }
      | null;
    if (!overlay) return;

    (async () => {
      const [
        { HeatmapLayer, GridLayer },
        { ScatterplotLayer, PolygonLayer },
      ] = await Promise.all([
        import('@deck.gl/aggregation-layers'),
        import('@deck.gl/layers'),
      ]);

      const layers: unknown[] = [];
      const active = alerts.filter((a) => a.severity !== 'resolved');

      // ── HEAT: orange/red heatmap of active alerts ───────────────────
      if (activeLayer === 'heat') {
        layers.push(
          new HeatmapLayer<FarmlandAlertPoint>({
            id: 'farmland-heat',
            data: active,
            getPosition: (a) => [a.longitude, a.latitude],
            getWeight: (a) =>
              a.severity === 'critical' ? 3 : a.severity === 'high' ? 2 : 1,
            radiusPixels: 70,
            intensity: 1.6,
            threshold: 0.04,
            aggregation: 'SUM',
          })
        );
      }

      // ── NDVI: green vegetation-health grid aggregation ──────────────
      if (activeLayer === 'ndvi') {
        layers.push(
          new GridLayer<FarmlandAlertPoint>({
            id: 'farmland-ndvi',
            data: active,
            getPosition: (a) => [a.longitude, a.latitude],
            getColorWeight: (a) => (a.affectedAreaHa ?? 30) / 100,
            cellSize: 5000,
            extruded: false,
            colorRange: [
              [237, 248, 233],
              [199, 233, 192],
              [161, 217, 155],
              [116, 196, 118],
              [65, 171, 93],
              [35, 139, 69],
            ],
            opacity: 0.55,
          })
        );
      }

      // ── SAR: cool-blue heatmap suggesting radar backscatter ─────────
      if (activeLayer === 'sar') {
        layers.push(
          new HeatmapLayer<FarmlandAlertPoint>({
            id: 'farmland-sar',
            data: active,
            getPosition: (a) => [a.longitude, a.latitude],
            getWeight: (a) => (a.confidence ?? 0.5) * 3,
            radiusPixels: 90,
            intensity: 1.3,
            threshold: 0.03,
            colorRange: [
              [255, 255, 178, 0],
              [161, 218, 215],
              [102, 194, 165],
              [65, 174, 218],
              [44, 127, 184],
              [37, 52, 148],
            ],
          })
        );
      }

      // ── BOUNDARIES: rough ROI polygon around the tenant centroid ────
      if (activeLayer === 'boundary') {
        const [lon, lat] = tenant.centroid;
        // Crude bbox derived from tenant.type — bigger for whole countries
        const w =
          tenant.type === 'ecowas_country'
            ? 3.0
            : tenant.type === 'ng_fct'
            ? 0.6
            : 1.4;
        const polygon = [
          [lon - w, lat - w * 0.8],
          [lon + w, lat - w * 0.8],
          [lon + w, lat + w * 0.8],
          [lon - w, lat + w * 0.8],
          [lon - w, lat - w * 0.8],
        ];
        layers.push(
          new PolygonLayer<typeof polygon>({
            id: 'farmland-boundary',
            data: [polygon],
            getPolygon: (d) => d,
            getFillColor: [120, 180, 255, 28],
            getLineColor: [120, 180, 255, 220],
            lineWidthMinPixels: 1.5,
            stroked: true,
            filled: true,
          })
        );
      }

      // ── Pulsing halo ring on CRITICAL + HIGH pins ────────────────────
      // Sinusoidal radius: oscillates ~3x base size. The updateTriggers
      // entry forces deck.gl to re-evaluate getRadius on each `pulse` tick.
      const pulseAlerts = alerts.filter(
        (a) => a.severity === 'critical' || a.severity === 'high',
      );
      layers.push(
        new ScatterplotLayer<FarmlandAlertPoint>({
          id: 'farmland-pulse',
          data: pulseAlerts,
          getPosition: (a) => [a.longitude, a.latitude],
          // Uniform pixel-pulse halo — identical to Poverty Mapping and every
          // other module (haloRadiusPx → 20–40 px). Severity is conveyed by
          // colour, not size, so halos never balloon or block each other.
          getRadius: () => haloRadiusPx(pulse),
          getFillColor: (a) =>
            [...SEVERITY_RGB[a.severity], 40] as [number, number, number, number],
          radiusUnits: 'pixels',
          stroked: false,
          pickable: false,
          updateTriggers: { getRadius: pulse },
        })
      );

      // ── Static base pins (always visible, pickable) ─────────────────
      layers.push(
        new ScatterplotLayer<FarmlandAlertPoint>({
          id: 'farmland-pins',
          data: alerts,
          getPosition: (a) => [a.longitude, a.latitude],
          getRadius: (a) =>
            a.severity === 'critical' ? 16000 : a.severity === 'high' ? 11000 : 8000,
          getFillColor: (a) =>
            [...SEVERITY_RGB[a.severity], 230] as [number, number, number, number],
          getLineColor: [255, 255, 255, 220],
          lineWidthMinPixels: 1.5,
          radiusUnits: 'meters',
          radiusMinPixels: 6,
          // Uniform base-dot cap (24 px) — matches Poverty Mapping.
          radiusMaxPixels: 24,
          stroked: true,
          pickable: true,
          onHover: (info) => {
            if (info && info.object && info.x !== undefined && info.y !== undefined) {
              setHover({
                x: info.x,
                y: info.y,
                alert: info.object as FarmlandAlertPoint,
              });
            } else {
              setHover(null);
            }
          },
        })
      );

      overlay.setProps({ layers });
    })();
  }, [activeLayer, alerts, mapStatus, pulse, tenant.centroid, tenant.type]);

  const cadence = satelliteCadence(tenant);

  return (
    <div
      className="fp-map-canvas"
      role="application"
      aria-label={`Farmland heat map — ${tenant.name}`}
    >
      <div ref={containerRef} className="map-host" />
      {mapStatus === 'no-token' && <FarmlandMapTokenPlaceholder />}
      {mapStatus === 'loading' && <FarmlandMapLoading />}
      {mapStatus === 'error' && <FarmlandMapError message={mapError} />}

      <div className="fp-map-legend">
        <div className="fp-legend-item">
          <div className="fp-legend-dot fp-legend-dot--critical" />
          Heat encroachment (critical)
        </div>
        <div className="fp-legend-item">
          <div className="fp-legend-dot fp-legend-dot--high" />
          Heat encroachment (warning)
        </div>
        <div className="fp-legend-item">
          <div className="fp-legend-dot fp-legend-dot--resolved" />
          Resolved / mediated
        </div>
      </div>

      <div className="fp-map-overlay">
        {/* Live N2YO data when available, deterministic fallback otherwise. */}
        {nextPass ? (
          <>
            {nextPass.satellite_name} ({nextPass.satellite_group})<br />
            {lastPass
              ? `Last pass: ${Math.abs(minutesUntil(lastPass.start_utc, now))} min ago`
              : 'Last pass: —'}<br />
            Resolution: {cadence.resolution}<br />
            Coverage: {cadence.coverage}<br />
            Next pass: in {minutesUntil(nextPass.start_utc, now)} min · {' '}
            {nextPass.max_elevation_deg.toFixed(0)}° {nextPass.max_azimuth_compass}
          </>
        ) : passesQuery.isError ? (
          <>
            {cadence.source}<br />
            <span className="fp-map-overlay__warn">Live pass feed unavailable</span><br />
            Resolution: {cadence.resolution}<br />
            Coverage: {cadence.coverage}
          </>
        ) : (
          <>
            {cadence.source}<br />
            {passesQuery.isLoading ? 'Loading N2YO schedule…' : 'No upcoming passes in window'}<br />
            Resolution: {cadence.resolution}<br />
            Coverage: {cadence.coverage}
          </>
        )}
        <FreshnessLines
          optical={latestOptical}
          opticalLoading={opticalQuery.isLoading}
          opticalError={opticalQuery.isError}
          sar={latestSar}
          sarLoading={sarQuery.isLoading}
          sarError={sarQuery.isError}
          now={now}
        />
      </div>

      {hover && <HoverTooltip info={hover} />}
    </div>
  );
}

/**
 * Two short lines showing how fresh the most recent Sentinel-2 (optical)
 * and Sentinel-1 (SAR) scenes are for this tenant. Backed by the
 * /api/v1/imagery/recent endpoint's 10-minute server-side cache so the
 * lines are cheap to render on every dashboard load.
 *
 * Each line is "Optical: 14h ago · 12% cloud (T31PEN)" / "SAR: 32h ago".
 * Falls back to "—" while loading and a quiet warning on error.
 */
function FreshnessLines(props: {
  optical: ReturnType<typeof newestScene>;
  opticalLoading: boolean;
  opticalError: boolean;
  sar: ReturnType<typeof newestScene>;
  sarLoading: boolean;
  sarError: boolean;
  now: Date;
}) {
  const { optical, opticalLoading, opticalError, sar, sarLoading, sarError, now } = props;
  return (
    <>
      <br />
      <span className="fp-map-overlay__freshness">
        Optical:{' '}
        {opticalLoading
          ? '—'
          : opticalError
          ? <span className="fp-map-overlay__warn">unavailable</span>
          : optical
          ? <>
              {hoursAgo(optical.captured_at, now)}h ago
              {optical.cloud_cover_pct != null
                ? ` · ${Math.round(optical.cloud_cover_pct)}% cloud`
                : ''}
              {optical.mgrs_tile ? ` (${optical.mgrs_tile})` : ''}
            </>
          : 'no recent scene'}
      </span>
      <br />
      <span className="fp-map-overlay__freshness">
        SAR:{' '}
        {sarLoading
          ? '—'
          : sarError
          ? <span className="fp-map-overlay__warn">unavailable</span>
          : sar
          ? <>{hoursAgo(sar.captured_at, now)}h ago</>
          : 'no recent scene'}
      </span>
    </>
  );
}

function HoverTooltip({ info }: { info: HoverInfo }) {
  const a = info.alert;
  // Only the dynamic position stays inline — the rest lives in globals.css
  // under `.fp-map-tooltip` so it survives theme/dark-mode tweaks centrally.
  const pos = { left: info.x + 14, top: info.y + 14 };
  return (
    <div className="fp-map-tooltip" style={pos}>
      <div className="fp-tt-title">{a.location}</div>
      <div className="fp-tt-sub">
        {a.severity}
        {a.alertType ? ` • ${a.alertType}` : ''}
        {a.status ? ` • ${a.status.replace('_', ' ')}` : ''}
      </div>
      {a.zoneName && <div className="fp-tt-zone">{a.zoneName}</div>}
      <div className="fp-tt-coord">
        {formatLatLon(a.latitude, a.longitude)}
      </div>
      {(a.affectedAreaHa != null || a.livelihoodsAtRisk != null) && (
        <div className="fp-tt-metrics">
          {a.affectedAreaHa != null && <>~{Math.round(a.affectedAreaHa)} ha</>}
          {a.affectedAreaHa != null && a.livelihoodsAtRisk != null && ' • '}
          {a.livelihoodsAtRisk != null && (
            <>{a.livelihoodsAtRisk.toLocaleString()} livelihoods</>
          )}
        </div>
      )}
      {a.predictedBreachHours != null && a.severity !== 'resolved' && (
        <div className="fp-tt-eta">ETA breach: {a.predictedBreachHours}h</div>
      )}
      {a.confidence != null && (
        <div className="fp-tt-conf">Conf: {Math.round(a.confidence * 100)}%</div>
      )}
    </div>
  );
}

function FarmlandMapTokenPlaceholder() {
  return (
    <div className="map-overlay map-overlay--token">
      <div className="map-overlay-title">Mapbox token required</div>
      <div className="map-overlay-body">
        Set <code>NEXT_PUBLIC_MAPBOX_TOKEN</code> in{' '}
        <code>apps/frontend/.env.local</code> and restart the dev server.
      </div>
    </div>
  );
}

function FarmlandMapLoading() {
  return <div className="map-overlay map-overlay--loading">Loading SAR overlay…</div>;
}

function FarmlandMapError({ message }: { message: string | null }) {
  const isFetchFailure = !!message && /failed to fetch|networkerror|load failed/i.test(message);
  return (
    <div className="map-overlay map-overlay--error">
      <div className="map-overlay-title">Map failed to load</div>
      {isFetchFailure ? (
        <div className="map-overlay-body">
          The browser could not reach <code>api.mapbox.com</code>. Likely an
          ad-blocker / privacy extension, firewall, or token URL restriction excluding{' '}
          <code>localhost:3000</code>.
        </div>
      ) : (
        message && <div className="map-overlay-body">{message}</div>
      )}
    </div>
  );
}
