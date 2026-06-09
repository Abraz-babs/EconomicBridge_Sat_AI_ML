'use client';

/**
 * EconomicBridge landing page (route `/landing`). Second step in the front-door
 * flow: the Bizra Farms site at `/` links here, and this page's "Explore"
 * button opens the dashboard Overview (`/dashboard?tab=overview`).
 *
 * Flow: `/` (Bizra) → `/landing` (EconomicBridge) → `/dashboard` (Overview).
 *
 * The landing itself is the self-contained static page at `public/landing.html`
 * (its own Mapbox globe + animations); we embed it full-bleed so editing the
 * landing stays a single-file job.
 */
export default function EconomicBridgeLanding() {
  return (
    <iframe
      src="/landing.html"
      title="EconomicBridge"
      className="frame-fullbleed"
    />
  );
}
