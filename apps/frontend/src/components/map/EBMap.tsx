'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { StyleSpecification } from 'mapbox-gl';

import FullViewButton, { useAwayFromFullView } from '@/components/map/FullViewButton';
import {
  flyToTenant, jumpToTenant, recalledCamera, rememberCamera, type Camera,
} from '@/components/map/tenantCamera';
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
  /** Zoom for `focus` flights without their own zoom, and the tenant view when
   *  `tenantView` is 'centroid' (default 6). */
  zoom?: number;
  /** 'bounds' (default): frame the whole state and fly there when it changes.
   *  'centroid': the state's centre at `zoom` — for close-up tools such as the
   *  Farm Check pin drop. */
  tenantView?: 'bounds' | 'centroid';
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
  /**
   * Opt-in click handler — when provided, clicking the map calls this with
   * the clicked (lng, lat) and the cursor becomes a crosshair. Used by the
   * CropGuard Farm Check "drop a pin" flow; other modules omit it (no change).
   */
  onMapClick?: (lng: number, lat: number) => void;
  /** Override the map style (default: minimal dark). Accepts a Mapbox style URL
   *  (string) OR a full style object — the latter lets a module drop in a raster
   *  basemap (e.g. the Esri ArcGIS World Imagery service) without a Mapbox style.
   *  Farm Check uses a labelled satellite style so place names and land show. */
  mapStyle?: string | StyleSpecification;
  /** When set/changed, fly the map to this point + zoom (e.g. after a Farm
   *  Check, to centre the pin + analysed-area box on the exact coordinate). */
  focus?: { lng: number; lat: number; zoom?: number } | null;
  /** "Back to full map" was pressed — lets the caller drop its focus, so
   *  showing the same point again flies there again. */
  onResetView?: () => void;
  /** A card pinned to a map point (a clicked halo's detail). It follows the
   *  point as the map pans and zooms, and opens beside the point where it
   *  fits, otherwise above or below it. */
  card?: { lng: number; lat: number; node: ReactNode } | null;
}

/** Pinned-card width, and a first-frame height estimate before it is measured. */
const CARD_W = 340;
const CARD_H_EST = 380;


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
    overlay, legend, errorOverlay, getTooltip, onMapClick,
    mapStyle = MAPBOX_STYLE, focus, onResetView, card,
    tenantView = 'bounds',
  } = props;
  const byBounds = tenantView === 'bounds';

  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<unknown>(null);
  const overlayRef = useRef<unknown>(null);
  // Latest click handler via ref so the one-time init effect never re-runs.
  const clickRef = useRef<EBMapProps['onMapClick']>(onMapClick);
  useEffect(() => { clickRef.current = onMapClick; }, [onMapClick]);
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

  // The state the camera is framing, the view "Back to full map" returns to,
  // and a flag for a map that had no size to frame with (a closed <details>).
  const tenantRef = useRef(tenant);
  useEffect(() => { tenantRef.current = tenant; }, [tenant]);
  const framedRef = useRef<string | null>(null);
  const needsFitRef = useRef(false);
  const [fullView, setFullView] = useState<Camera>({ center: tenant.centroid, zoom });
  const [flyingTo, setFlyingTo] = useState<string | null>(null);

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
        // A map mounting for a different state than the reader last saw starts
        // where they were and flies over once loaded.
        const recalled = byBounds ? recalledCamera(tenant.id) : null;
        const start = recalled ?? { center: tenant.centroid, zoom };
        const map = new mapboxgl.Map({
          container: containerRef.current,
          // mapbox-gl's MapOptions narrows `style` to string, but the constructor
          // accepts a full style object at runtime (used for the Esri raster
          // basemap). Cast the union down to satisfy the type only.
          style: mapStyle as string,
          center: start.center,
          zoom: start.zoom,
          attributionControl: false,
          // Let the browser release WebGL framebuffers under memory pressure.
          // The CSS compositing layer keeps scroll repainting isolated without
          // forcing every map to retain a full drawing buffer.
          preserveDrawingBuffer: false,
        });
        mapRef.current = map;

        // Opt-in "drop a pin" — only does anything when a caller passed
        // onMapClick. Crosshair cursor signals the map is clickable.
        map.on('click', (e: { lngLat: { lng: number; lat: number } }) => {
          clickRef.current?.(e.lngLat.lng, e.lngLat.lat);
        });
        if (clickRef.current) {
          map.getCanvas().style.cursor = 'crosshair';
        }

        map.on('error', (e) => {
          if (cancelled) return;
          setStatus('error');
          setErrorMessage(sanitiseMapboxError(e?.error?.message) ?? 'Mapbox error');
        });

        map.on('moveend', () => {
          if (cancelled) return;
          rememberCamera(map, tenantRef.current.id);
          setFlyingTo(null);
        });
        // A map that first measured 0 × 0 frames its state once it has a size.
        map.on('resize', () => {
          if (cancelled || !needsFitRef.current) return;
          const cam = jumpToTenant(map, tenantRef.current);
          if (cam) { needsFitRef.current = false; setFullView(cam); }
        });

        map.on('load', () => {
          if (cancelled) return;
          if (byBounds) {
            const t = tenantRef.current;
            const cam = recalled ? flyToTenant(map, t) : jumpToTenant(map, t);
            if (cam) setFullView(cam); else needsFitRef.current = true;
            if (cam && recalled) setFlyingTo(t.name);
          }
          framedRef.current = tenantRef.current.id;
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

  // Fly to the whole state when it changes. Keyed on the id only — never on a
  // layer or an array made during render (the pulse maps re-render every 120 ms).
  useEffect(() => {
    if (status !== 'ready' || framedRef.current === tenant.id) return;
    framedRef.current = tenant.id;
    const map = mapRef.current;
    if (!map) return;
    if (byBounds) {
      const cam = flyToTenant(map, tenant);
      if (cam) { setFullView(cam); setFlyingTo(tenant.name); } else needsFitRef.current = true;
    } else {
      (map as { flyTo: (o: Record<string, unknown>) => void }).flyTo({ center: tenant.centroid, zoom, duration: 1200 });
      setFullView({ center: tenant.centroid, zoom });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenant.id, status]);

  // Explicit fly-to-focus (e.g. centre on a Farm Check result).
  useEffect(() => {
    if (!focus || status !== 'ready') return;
    const map = mapRef.current as
      | { flyTo: (o: { center: [number, number]; zoom: number; duration: number }) => void }
      | null;
    map?.flyTo({ center: [focus.lng, focus.lat], zoom: focus.zoom ?? zoom, duration: 1200 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus, status]);

  // The way back to the tenant's full view after a focus or a manual zoom.
  const awayFromFullView = useAwayFromFullView(mapRef, status === 'ready', fullView.center, fullView.zoom);
  const backToFullView = () => {
    const map = mapRef.current;
    if (map && byBounds) {
      const cam = flyToTenant(map, tenant);
      if (cam) setFullView(cam);
    } else {
      (map as { flyTo?: (o: Record<string, unknown>) => void } | null)?.flyTo?.({ center: tenant.centroid, zoom, duration: 1200 });
    }
    onResetView?.();
  };

  // Switch map style in place (Satellite / Dark / Light). The deck.gl overlay
  // is its own canvas, so data layers survive the swap untouched.
  const styleRef = useRef(mapStyle);
  useEffect(() => {
    if (status !== 'ready' || styleRef.current === mapStyle) return;
    styleRef.current = mapStyle;
    const map = mapRef.current as { setStyle?: (s: unknown) => void } | null;
    map?.setStyle?.(mapStyle);
  }, [mapStyle, status]);

  // Keep a pinned card next to its point while the map moves.
  const [cardPos, setCardPos] = useState<{ left: number; top: number } | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const cardMounted = cardPos !== null;
  const cardLng = card?.lng;
  const cardLat = card?.lat;
  useEffect(() => {
    if (status !== 'ready' || cardLng == null || cardLat == null) return;
    const map = mapRef.current as {
      project: (ll: [number, number]) => { x: number; y: number };
      on: (e: string, f: () => void) => void;
      off: (e: string, f: () => void) => void;
    } | null;
    const host = containerRef.current;
    if (!map || !host) return;
    const place = () => {
      const p = map.project([cardLng, cardLat]);
      const W = host.clientWidth;
      const H = host.clientHeight;
      // The card's real height once rendered; the estimate only for frame one.
      const CARD_H = Math.min(cardRef.current?.offsetHeight || CARD_H_EST, H - 16);
      let left: number;
      let top: number;
      if (p.x + 22 + CARD_W <= W - 8) {
        left = p.x + 22;
        top = Math.max(8, Math.min(p.y - 40, H - CARD_H - 8));
      } else if (p.x - 22 - CARD_W >= 8) {
        left = p.x - 22 - CARD_W;
        top = Math.max(8, Math.min(p.y - 40, H - CARD_H - 8));
      } else {
        left = Math.max(8, Math.min(W - CARD_W - 8, p.x - CARD_W / 2));
        top = p.y + 26 + CARD_H <= H ? p.y + 26 : Math.max(8, p.y - 26 - CARD_H);
      }
      setCardPos({ left, top });
    };
    // First placement on the next frame, then follow every move and every
    // change in the card's own size (content arriving, a different point).
    const raf = requestAnimationFrame(place);
    map.on('move', place);
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => place()) : null;
    if (ro && cardRef.current) ro.observe(cardRef.current);
    return () => {
      cancelAnimationFrame(raf);
      map.off('move', place);
      ro?.disconnect();
    };
    // Re-run once the card has mounted, so its real height is observed.
  }, [status, cardLng, cardLat, cardMounted]);

  // Push layer updates to deck.gl.
  useEffect(() => {
    if (status !== 'ready') return;
    const ov = overlayRef.current as
      | { setProps: (p: { layers: unknown[] }) => void }
      | null;
    const pushLayers = () => {
      const shouldRelease = document.visibilityState === 'hidden';
      ov?.setProps({ layers: shouldRelease ? [] : layers });
    };
    pushLayers();
    document.addEventListener('visibilitychange', pushLayers);
    return () => document.removeEventListener('visibilitychange', pushLayers);
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
      {flyingTo && <div className="eb-map-flying" aria-live="polite">{flyingTo}</div>}
      {status === 'ready' && awayFromFullView && !flyingTo && (
        <FullViewButton areaName={tenant.name} onClick={backToFullView} />
      )}
      {card && cardPos && (
        <div ref={cardRef} className="mm-card-anchor" style={{ left: cardPos.left, top: cardPos.top, width: CARD_W }}>
          {card.node}
        </div>
      )}
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
