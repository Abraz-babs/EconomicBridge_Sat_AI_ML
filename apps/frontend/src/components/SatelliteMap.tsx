'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { KEBBI_CENTER, RISK_RGB, TENANTS, type Tenant } from '@/data/tenants';

const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;
const MAPBOX_STYLE = 'mapbox://styles/mapbox/dark-v11';

type LayerKey = 'Poverty' | 'Disaster' | 'Crops' | 'All Layers';
const LAYERS: LayerKey[] = ['Poverty', 'Disaster', 'Crops', 'All Layers'];

function filterTenants(layer: LayerKey): Tenant[] {
  if (layer === 'Disaster') {
    return TENANTS.filter((t) => t.conflict_risk === 'critical' || t.conflict_risk === 'high');
  }
  return TENANTS;
}

function sanitizeMapboxError(message: string | null | undefined): string | null {
  if (!message) return null;
  return message
    .replace(/access_token=[^&\s"']+/gi, 'access_token=[redacted]')
    .replace(/Bearer\s+pk\.[^\s"']+/gi, 'Bearer [redacted]');
}

// ── Active-coverage overlay (added; mirrors the :8090 cover page exactly) ──
// Green pulsing ring blinkers on every active pilot + dashed BLUE links
// converging on the Abuja hub — the same technique used on the landing page.
// Purely additive: HTML markers float over the base map; the deck.gl tenant
// dots, layer toggles, zoom and behaviour are all unchanged.
const COVERAGE_HUB: [number, number] = [7.49, 9.06]; // FCT · Abuja
const COVERAGE_BLINK = '#36d39a';
const COVERAGE_LINK = '#3ea6ff';
// The real covered pilots (the 3-country set). NOT t.active — Ghana & Senegal
// are deployment-phase 2 (active:false) but ARE covered, so select by id.
const COVERAGE_PILOT_IDS = new Set([
  'kebbi', 'benue', 'plateau', 'kaduna', 'niger', 'zamfara', 'nasarawa', 'fct',
  'ghana', 'senegal',
]);
const COVERAGE_PULSE_CSS =
  '@keyframes eb-cov-pulse{0%{box-shadow:0 0 0 0 rgba(54,211,154,.6)}' +
  '70%{box-shadow:0 0 0 14px rgba(54,211,154,0)}' +
  '100%{box-shadow:0 0 0 0 rgba(54,211,154,0)}}';

export default function SatelliteMap() {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<unknown>(null);
  const overlayRef = useRef<unknown>(null);
  const coverageStopRef = useRef<(() => void) | null>(null);

  const [activeLayer, setActiveLayer] = useState<LayerKey>('All Layers');
  const [selectedTenant, setSelectedTenant] = useState<Tenant | null>(null);
  const [mapStatus, setMapStatus] = useState<'idle' | 'loading' | 'ready' | 'error' | 'no-token'>(
    MAPBOX_TOKEN ? 'loading' : 'no-token'
  );
  const [mapError, setMapError] = useState<string | null>(null);

  useEffect(() => {
    if (!MAPBOX_TOKEN || !containerRef.current) return;

    let cancelled = false;
    let resizeObserver: ResizeObserver | null = null;

    (async () => {
      try {
        const [{ default: mapboxgl }, { ScatterplotLayer }, { MapboxOverlay }] = await Promise.all([
          import('mapbox-gl'),
          import('@deck.gl/layers'),
          import('@deck.gl/mapbox'),
        ]);

        if (cancelled || !containerRef.current) return;

        mapboxgl.accessToken = MAPBOX_TOKEN;
        const map = new mapboxgl.Map({
          container: containerRef.current,
          style: MAPBOX_STYLE,
          center: KEBBI_CENTER,
          zoom: 5.2,
          attributionControl: false,
          // Avoid retaining a full WebGL drawing buffer for the overview map.
          // The map host is already on its own compositing layer in CSS.
          preserveDrawingBuffer: false,
        });
        mapRef.current = map;

        // Keep the canvas filling its (flex) container — the overview map grows
        // to match the sidebar height, and the sidebar grows as data loads.
        resizeObserver = new ResizeObserver(() => {
          try { map.resize(); } catch { /* torn down */ }
        });
        resizeObserver.observe(containerRef.current);

        map.on('error', (e) => {
          if (cancelled) return;
          setMapStatus('error');
          setMapError(sanitizeMapboxError(e?.error?.message) ?? 'Mapbox error');
        });

        map.on('load', () => {
          if (cancelled) return;
          const overlay = new MapboxOverlay({
            interleaved: false,
            // Cap deck rendering to CSS pixels — a full-DPR canvas on 4K screens
            // can exhaust GPU memory and blank on scroll.
            useDevicePixels: false,
            layers: [
              new ScatterplotLayer<Tenant>({
                id: 'tenants-scatter',
                data: filterTenants('All Layers'),
                getPosition: (t) => [t.centroid[0], t.centroid[1]],
                getRadius: (t) => (t.active ? 22000 : 14000),
                getFillColor: (t) => [...RISK_RGB[t.conflict_risk], 200] as [number, number, number, number],
                getLineColor: [255, 255, 255, 90],
                lineWidthMinPixels: 1,
                radiusUnits: 'meters',
                radiusMinPixels: 5,
                radiusMaxPixels: 28,
                stroked: true,
                pickable: true,
                onClick: (info) => {
                  setSelectedTenant((info.object as Tenant | null) ?? null);
                },
              }),
            ],
          });
          map.addControl(overlay);
          overlayRef.current = overlay;

          // Added: green pulsing coverage blinkers + dashed links converging on
          // the Abuja hub — matches the :8090 cover page. Markers float over the
          // base map; deck dots stay interactive. Cleaned up on teardown.
          if (!document.getElementById('eb-cov-pulse-css')) {
            const css = document.createElement('style');
            css.id = 'eb-cov-pulse-css';
            css.textContent = COVERAGE_PULSE_CSS;
            document.head.appendChild(css);
          }
          const covPilots = TENANTS.filter((t) => COVERAGE_PILOT_IDS.has(t.id));
          map.addSource('coverage-links', {
            type: 'geojson',
            data: {
              type: 'FeatureCollection',
              features: covPilots.map((p) => ({
                type: 'Feature' as const,
                geometry: {
                  type: 'LineString' as const,
                  coordinates: [p.centroid, COVERAGE_HUB],
                },
                properties: {},
              })),
            },
          });
          map.addLayer({
            id: 'coverage-links',
            type: 'line',
            source: 'coverage-links',
            paint: {
              'line-color': COVERAGE_LINK,
              'line-width': 1,
              'line-opacity': 0.35,
              'line-dasharray': [2, 3], // dotted
            },
          });
          const covMarkers = covPilots.map((p) => {
            const el = document.createElement('div');
            el.style.cssText =
              `width:10px;height:10px;border-radius:50%;background:${COVERAGE_BLINK};` +
              'box-shadow:0 0 0 0 rgba(54,211,154,.6);animation:eb-cov-pulse 2.1s infinite';
            return new mapboxgl.Marker({ element: el }).setLngLat(p.centroid).addTo(map);
          });
          coverageStopRef.current = () => {
            covMarkers.forEach((m) => m.remove());
            try {
              if (map.getLayer('coverage-links')) map.removeLayer('coverage-links');
              if (map.getSource('coverage-links')) map.removeSource('coverage-links');
            } catch {
              /* map already torn down — ignore */
            }
          };

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
      resizeObserver?.disconnect();
      resizeObserver = null;
      coverageStopRef.current?.();
      coverageStopRef.current = null;
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

    const pushLayers = async () => {
      if (document.visibilityState === 'hidden') {
        overlay.setProps({ layers: [] });
        return;
      }
      const { ScatterplotLayer } = await import('@deck.gl/layers');
      overlay.setProps({
        layers: [
          new ScatterplotLayer<Tenant>({
            id: 'tenants-scatter',
            data: filterTenants(activeLayer),
            getPosition: (t) => [t.centroid[0], t.centroid[1]],
            getRadius: (t) => (t.active ? 22000 : 14000),
            getFillColor: (t) => [...RISK_RGB[t.conflict_risk], 200] as [number, number, number, number],
            getLineColor: [255, 255, 255, 90],
            lineWidthMinPixels: 1,
            radiusUnits: 'meters',
            radiusMinPixels: 5,
            radiusMaxPixels: 28,
            stroked: true,
            pickable: true,
            onClick: (info) => setSelectedTenant((info.object as Tenant | null) ?? null),
          }),
        ],
      });
    };

    const onVisibilityChange = () => { void pushLayers(); };
    void pushLayers();
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => document.removeEventListener('visibilitychange', onVisibilityChange);
  }, [activeLayer, mapStatus]);

  // Detail strip: a user click pins a tenant; otherwise rotate through the
  // active pilots so the strip reads as the live intel ticker it is — not a
  // hardcoded "Kebbi" line. Paused while the tab is hidden (project pattern).
  const [rotateIdx, setRotateIdx] = useState(0);
  const activePilots = useMemo(() => TENANTS.filter((t) => t.active), []);
  useEffect(() => {
    if (selectedTenant || activePilots.length === 0) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === 'visible') {
        setRotateIdx((i) => (i + 1) % activePilots.length);
      }
    }, 7000);
    return () => window.clearInterval(id);
  }, [selectedTenant, activePilots.length]);
  const detailTenant =
    selectedTenant ??
    activePilots[rotateIdx % Math.max(activePilots.length, 1)] ??
    TENANTS.find((t) => t.id === 'kebbi')!;

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Satellite Intelligence Map</span>
        <span className="panel-meta">
          {mapStatus === 'ready'
            ? `${filterTenants(activeLayer).length} tenants · centred on Kebbi`
            : '52 tenants · West Africa coverage'}
        </span>
      </div>

      <div className="map-area">
        <div className="layer-btns">
          {LAYERS.map((l) => (
            <button
              key={l}
              className={`lbtn ${activeLayer === l ? 'active' : ''}`}
              onClick={() => setActiveLayer(l)}
              type="button"
            >
              {l}
            </button>
          ))}
        </div>

        <div className="map-canvas" role="application" aria-label="Satellite intelligence map">
          <div ref={containerRef} className="map-host" />
          {mapStatus === 'no-token' && <MapTokenPlaceholder />}
          {mapStatus === 'loading' && <MapLoadingOverlay />}
          {mapStatus === 'error' && <MapErrorOverlay message={mapError} />}
        </div>

        <div className="map-legend">
          <div className="legend-row">
            <div className="ldot" data-risk-color="critical" />
            Critical risk
          </div>
          <div className="legend-row">
            <div className="ldot" data-risk-color="high" />
            High risk
          </div>
          <div className="legend-row">
            <div className="ldot" data-risk-color="medium" />
            Medium risk
          </div>
          <div className="legend-row">
            <div className="ldot" data-risk-color="low" />
            Low risk
          </div>
        </div>
      </div>

      <div className="map-detail">
        <span className="map-detail-name">
          {detailTenant.name} — {detailTenant.capital}
        </span>
        &nbsp;·&nbsp;
        <span className={`map-detail-risk map-detail-risk--${detailTenant.conflict_risk}`}>
          {detailTenant.conflict_risk.toUpperCase()} RISK
        </span>
        &nbsp;·&nbsp;
        <span className={detailTenant.active ? 'map-detail-active' : 'map-detail-planned'}>
          {detailTenant.active ? 'ACTIVE' : 'PLANNED'}
        </span>
        {selectedTenant && (
          <>
            &nbsp;·{' '}
            <button
              type="button"
              onClick={() => setSelectedTenant(null)}
              className="map-detail-clear"
            >
              clear
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function MapTokenPlaceholder() {
  return (
    <div className="map-overlay map-overlay--token">
      <div className="map-overlay-title">Mapbox token required</div>
      <div className="map-overlay-body">
        Set <code>NEXT_PUBLIC_MAPBOX_TOKEN</code> in{' '}
        <code>apps/frontend/.env.local</code> and restart the dev server. See{' '}
        <code>.env.local.example</code> for the format.
      </div>
      <div className="map-overlay-hint">Free public tokens: account.mapbox.com → Tokens</div>
    </div>
  );
}

function MapLoadingOverlay() {
  return <div className="map-overlay map-overlay--loading">Loading satellite layer…</div>;
}

function MapErrorOverlay({ message }: { message: string | null }) {
  const isFetchFailure = !!message && /failed to fetch|networkerror|load failed/i.test(message);
  return (
    <div className="map-overlay map-overlay--error">
      <div className="map-overlay-title">Map failed to load</div>
      {isFetchFailure ? (
        <div className="map-overlay-body">
          The browser could not reach <code>api.mapbox.com</code>. Common causes: an
          ad-blocker / privacy extension is blocking Mapbox, a corporate firewall or VPN
          is blocking the host, or the token has URL referrer restrictions that exclude{' '}
          <code>localhost:3000</code>.
        </div>
      ) : (
        message && <div className="map-overlay-body">{message}</div>
      )}
    </div>
  );
}
