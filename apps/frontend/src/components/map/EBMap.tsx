'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';

import type { Tenant } from '@/data/tenants';


const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;
const MAPBOX_STYLE = 'mapbox://styles/mapbox/dark-v11';


type MapStatus = 'loading' | 'ready' | 'error' | 'no-token';


export interface EBMapProps {
  /** Active tenant — drives initial centroid + flyTo on change. */
  tenant: Tenant;
  /**
   * Deck.gl layers to render. Plain `unknown[]` so callers can build
   * the layer instances inline without importing deck types here.
   * `updateTriggers` is the right escape hatch for layers whose props
   * change on every tick.
   */
  layers: unknown[];
  /** CSS height (default 420px). */
  height?: string;
  /** Initial zoom (default 6). */
  zoom?: number;
  /** ARIA label for screen readers. */
  ariaLabel?: string;
  /** JSX rendered top-right (e.g., pass countdown, freshness lines). */
  overlay?: ReactNode;
  /** JSX rendered bottom-left (e.g., color legend). */
  legend?: ReactNode;
  /**
   * Custom error placeholder. Defaults to the standard
   * "Mapbox failed to load" copy; callers can override for module-
   * specific hints. */
  errorOverlay?: ReactNode;
  /**
   * Hover-tooltip formatter (Slice 25). Given the picked layer object,
   * return the tooltip text (newline-separated lines) or null for no
   * tooltip. Wired into the Deck.gl overlay's `getTooltip` so every
   * module gets a hover card from one place. Text is rendered via
   * deck.gl's `{text}` return (no innerHTML) so there's no XSS surface
   * even though the values come from the DB.
   */
  getTooltip?: (object: unknown) => string | null;
}


/**
 * Shared map container used by every EO module (Farmland, Poverty,
 * Aid Coordination, CropGuard).
 *
 * Module-specific concerns (legend copy, overlay text, layer choice)
 * are slot-injected — the map itself stays generic. Each module
 * imports the deck.gl layer types it needs, builds an array of
 * layer instances, and passes them via the `layers` prop.
 *
 * Why a separate component instead of extending FarmlandMap:
 *  * FarmlandMap carries farmland-specific UI (heat/SAR/boundary
 *    toggle, hover tooltip, severity-pulse halo) that the other
 *    modules don't need.
 *  * Pulling that out into options would balloon the API surface.
 *  * Two components, one shared concern: lower coupling, more
 *    obvious ownership.
 */
export default function EBMap(props: EBMapProps) {
  const {
    tenant, layers,
    height = '420px',
    zoom = 6,
    ariaLabel = `Satellite intelligence map — ${tenant.name}`,
    overlay, legend, errorOverlay, getTooltip,
  } = props;

  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<unknown>(null);
  const overlayRef = useRef<unknown>(null);
  // Keep the latest formatter in a ref so the overlay's getTooltip
  // closure (built once at init) always calls the current one without
  // recreating the overlay when the prop identity changes per render.
  const tooltipRef = useRef<EBMapProps['getTooltip']>(getTooltip);
  useEffect(() => {
    tooltipRef.current = getTooltip;
  }, [getTooltip]);
  const [status, setStatus] = useState<MapStatus>(
    MAPBOX_TOKEN ? 'loading' : 'no-token',
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

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
          zoom,
          attributionControl: false,
          // Keep the rendered buffer so the canvas doesn't blank when scrolled
          // off-screen and back (the GPU would otherwise evict the surface).
          preserveDrawingBuffer: true,
        });
        mapRef.current = map;

        map.on('error', (e) => {
          if (cancelled) return;
          setStatus('error');
          setErrorMessage(sanitiseMapboxError(e?.error?.message) ?? 'Mapbox error');
        });

        map.on('load', () => {
          if (cancelled) return;
          const overlay = new MapboxOverlay({
            interleaved: false,
            // Cap deck rendering to CSS pixels (not device pixels). On hi-DPI /
            // 4K screens a full-DPR deck canvas + HeatmapLayer can exhaust GPU
            // memory and make the browser's GPU process drop/blank on scroll.
            useDevicePixels: false,
            layers: [],
            // Hover card — reads the current module formatter via ref.
            // Returns deck.gl's {text} shape (no innerHTML → no XSS).
            getTooltip: (info: { object?: unknown }) => {
              const obj = info?.object;
              if (!obj) return null;
              const text = tooltipRef.current?.(obj);
              if (!text) return null;
              return {
                text,
                style: {
                  backgroundColor: 'rgba(26, 23, 20, 0.95)',
                  color: '#f5f2ee',
                  fontSize: '11px',
                  fontFamily: 'system-ui, sans-serif',
                  lineHeight: '1.5',
                  padding: '8px 10px',
                  borderRadius: '4px',
                  maxWidth: '240px',
                  whiteSpace: 'pre-line',
                  boxShadow: '0 2px 10px rgba(0,0,0,0.4)',
                },
              };
            },
          });
          map.addControl(overlay);
          overlayRef.current = overlay;
          setStatus('ready');
        });
      } catch (err) {
        if (cancelled) return;
        setStatus('error');
        setErrorMessage(
          sanitiseMapboxError(err instanceof Error ? err.message : null) ??
            'Failed to load map',
        );
      }
    })();

    return () => {
      cancelled = true;
      const ov = overlayRef.current as { finalize?: () => void } | null;
      ov?.finalize?.();
      overlayRef.current = null;
      const m = mapRef.current as { remove?: () => void } | null;
      m?.remove?.();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Fly to active tenant on change.
  useEffect(() => {
    if (status !== 'ready') return;
    const map = mapRef.current as
      | { flyTo: (o: { center: [number, number]; zoom: number; duration: number }) => void }
      | null;
    map?.flyTo({ center: tenant.centroid, zoom, duration: 1200 });
  }, [tenant.id, tenant.centroid, zoom, status]);

  // Push layer updates to deck.gl.
  useEffect(() => {
    if (status !== 'ready') return;
    const ov = overlayRef.current as
      | { setProps: (p: { layers: unknown[] }) => void }
      | null;
    ov?.setProps({ layers });
  }, [layers, status]);

  return (
    <div
      className="fp-map-canvas"
      role="application"
      aria-label={ariaLabel}
      style={{ height }}
    >
      <div ref={containerRef} className="map-host" />
      {status === 'no-token' && <MapTokenPlaceholder />}
      {status === 'loading' && <MapLoading />}
      {status === 'error' && (errorOverlay ?? <MapError message={errorMessage} />)}

      {legend && <div className="fp-map-legend">{legend}</div>}
      {overlay && <div className="fp-map-overlay">{overlay}</div>}
    </div>
  );
}


/** Strip Mapbox tokens out of error strings before exposing to the DOM. */
function sanitiseMapboxError(message: string | null | undefined): string | null {
  if (!message) return null;
  return message
    .replace(/access_token=[^&\s"']+/gi, 'access_token=[redacted]')
    .replace(/Bearer\s+pk\.[^\s"']+/gi, 'Bearer [redacted]');
}


function MapTokenPlaceholder() {
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

function MapLoading() {
  return <div className="map-overlay map-overlay--loading">Loading satellite layers…</div>;
}

function MapError({ message }: { message: string | null }) {
  const isFetchFailure = !!message && /failed to fetch|networkerror|load failed/i.test(message);
  return (
    <div className="map-overlay map-overlay--error">
      <div className="map-overlay-title">Map failed to load</div>
      {isFetchFailure ? (
        <div className="map-overlay-body">
          The browser could not reach <code>api.mapbox.com</code>. Likely an
          ad-blocker / privacy extension, firewall, or token URL restriction
          excluding <code>localhost:3000</code>.
        </div>
      ) : (
        message && <div className="map-overlay-body">{message}</div>
      )}
    </div>
  );
}
