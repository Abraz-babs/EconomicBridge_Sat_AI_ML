'use client';

import { useEffect, useRef, useState } from 'react';
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

// ── Active-coverage overlay (added, mirrors the landing-page viz) ──────────
// Synchronised blinking green halos over the covered pilot points + dotted
// connectivity lines from the Abuja hub out to Ghana and Senegal. Purely
// additive (Mapbox-native circle/line layers); sits beneath the deck.gl
// tenant dots and never touches the existing layers/behaviour.
const COVERAGE_HEX = '#40dc82';
const ABUJA_HUB: [number, number] = [7.49, 9.06];
const GHANA_PT: [number, number] = [-1.03, 7.95];
const SENEGAL_PT: [number, number] = [-14.45, 14.5];

/** Minimal slice of the Mapbox GL map we touch — avoids a hard type import. */
interface CoverageMap {
  addSource: (id: string, src: unknown) => void;
  addLayer: (layer: unknown) => void;
  getLayer: (id: string) => unknown;
  setPaintProperty: (layer: string, prop: string, value: unknown) => void;
}

/**
 * Add the blinking-halo + dotted-link coverage overlay to a loaded map.
 * Returns a stop() that cancels the blink animation on teardown.
 */
function addCoverageOverlay(map: CoverageMap): () => void {
  const points = TENANTS.filter((t) => t.active).map((t) => ({
    type: 'Feature' as const,
    geometry: { type: 'Point' as const, coordinates: t.centroid },
    properties: {},
  }));
  const links = [
    [ABUJA_HUB, GHANA_PT],
    [ABUJA_HUB, SENEGAL_PT],
  ].map(([s, e]) => ({
    type: 'Feature' as const,
    geometry: { type: 'LineString' as const, coordinates: [s, e] },
    properties: {},
  }));

  map.addSource('coverage-links', {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: links },
  });
  map.addLayer({
    id: 'coverage-links',
    type: 'line',
    source: 'coverage-links',
    paint: {
      'line-color': COVERAGE_HEX,
      'line-width': 1.4,
      'line-opacity': 0.6,
      'line-dasharray': [2, 2], // dotted
    },
  });

  map.addSource('coverage-points', {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: points },
  });
  map.addLayer({
    id: 'coverage-glow',
    type: 'circle',
    source: 'coverage-points',
    paint: {
      'circle-radius': 10,
      'circle-color': COVERAGE_HEX,
      'circle-opacity': 0.28,
      'circle-blur': 0.6,
    },
  });
  map.addLayer({
    id: 'coverage-core',
    type: 'circle',
    source: 'coverage-points',
    paint: {
      'circle-radius': 3,
      'circle-color': COVERAGE_HEX,
      'circle-opacity': 0.95,
    },
  });

  // Synchronised blink — every halo pulses together (one shared phase).
  const now = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());
  const t0 = now();
  let raf = 0;
  const tick = () => {
    const p = 0.5 + 0.5 * Math.sin((now() - t0) / 480); // 0..1, ~3s cycle
    try {
      if (map.getLayer('coverage-glow')) {
        map.setPaintProperty('coverage-glow', 'circle-radius', 9 + 11 * p);
        map.setPaintProperty('coverage-glow', 'circle-opacity', 0.12 + 0.3 * (1 - p));
      }
    } catch {
      /* map torn down mid-frame — ignore */
    }
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(raf);
}

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
        });
        mapRef.current = map;

        map.on('error', (e) => {
          if (cancelled) return;
          setMapStatus('error');
          setMapError(sanitizeMapboxError(e?.error?.message) ?? 'Mapbox error');
        });

        map.on('load', () => {
          if (cancelled) return;
          const overlay = new MapboxOverlay({
            interleaved: false,
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
          // Added: blinking green coverage halos + dotted Abuja→Ghana/Senegal
          // links. Beneath the deck tenant dots; everything else unchanged.
          coverageStopRef.current = addCoverageOverlay(map as unknown as CoverageMap);
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

    (async () => {
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
    })();
  }, [activeLayer, mapStatus]);

  const detailTenant = selectedTenant ?? TENANTS.find((t) => t.id === 'kebbi')!;

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
        Phase {detailTenant.deployment_phase} · Priority {detailTenant.priority} ·{' '}
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
