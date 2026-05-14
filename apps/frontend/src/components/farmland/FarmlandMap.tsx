'use client';

import { useEffect, useRef, useState } from 'react';

export type AlertSeverity = 'critical' | 'high' | 'medium' | 'resolved';

export interface FarmlandAlertPoint {
  id: string;
  location: string;
  longitude: number;
  latitude: number;
  severity: AlertSeverity;
  confidence?: number;
}

const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;
const MAPBOX_STYLE = 'mapbox://styles/mapbox/dark-v11';

// NW Nigeria + middle belt — covers Kebbi, Zamfara, Kaduna, Plateau alert LGAs
const NW_NIGERIA_CENTER: [number, number] = [6.8, 10.8];
const NW_NIGERIA_ZOOM = 5.7;

const SEVERITY_RGB: Record<AlertSeverity, [number, number, number]> = {
  critical: [255, 69, 0],
  high:     [255, 140, 0],
  medium:   [82, 183, 136],
  resolved: [82, 183, 136],
};

function sanitizeMapboxError(message: string | null | undefined): string | null {
  if (!message) return null;
  return message
    .replace(/access_token=[^&\s"']+/gi, 'access_token=[redacted]')
    .replace(/Bearer\s+pk\.[^\s"']+/gi, 'Bearer [redacted]');
}

interface Props {
  alerts: FarmlandAlertPoint[];
  activeLayer: 'heat' | 'ndvi' | 'sar' | 'boundary';
}

export default function FarmlandMap({ alerts, activeLayer }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<unknown>(null);
  const overlayRef = useRef<unknown>(null);
  const [mapStatus, setMapStatus] = useState<'loading' | 'ready' | 'error' | 'no-token'>(
    MAPBOX_TOKEN ? 'loading' : 'no-token'
  );
  const [mapError, setMapError] = useState<string | null>(null);

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
          center: NW_NIGERIA_CENTER,
          zoom: NW_NIGERIA_ZOOM,
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
  }, []);

  useEffect(() => {
    if (mapStatus !== 'ready') return;
    const overlay = overlayRef.current as
      | { setProps: (p: { layers: unknown[] }) => void }
      | null;
    if (!overlay) return;

    (async () => {
      const [{ HeatmapLayer }, { ScatterplotLayer }] = await Promise.all([
        import('@deck.gl/aggregation-layers'),
        import('@deck.gl/layers'),
      ]);

      const layers: unknown[] = [];

      const showHeat = activeLayer === 'heat' || activeLayer === 'sar';
      if (showHeat) {
        layers.push(
          new HeatmapLayer<FarmlandAlertPoint>({
            id: 'farmland-heat',
            data: alerts.filter((a) => a.severity !== 'resolved'),
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

      // Pins are always visible so the alert positions are anchored
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
          radiusMaxPixels: 26,
          stroked: true,
          pickable: true,
        })
      );

      overlay.setProps({ layers });
    })();
  }, [activeLayer, alerts, mapStatus]);

  return (
    <div
      className="fp-map-canvas"
      role="application"
      aria-label="Northwest Nigeria farmland heat map"
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
        Copernicus Sentinel-1 SAR<br />
        N2YO Pass: 14 min ago<br />
        Resolution: 10m/px<br />
        Coverage: NW Nigeria<br />
        Next pass: 47 min
      </div>
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
