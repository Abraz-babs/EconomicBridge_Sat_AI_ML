'use client';

/**
 * Front door (route `/`). Shows the marketing/landing page — the first thing a
 * visitor sees. The landing itself lives as a self-contained static page at
 * `public/landing.html` (its own Mapbox globe + animations); we embed it
 * full-bleed here so editing the landing stays a single-file job. Its "Explore"
 * button navigates the top window into the dashboard (`/dashboard`).
 */
export default function LandingPage() {
  return (
    <iframe
      src="/landing.html"
      title="EconomicBridge"
      style={{
        position: 'fixed',
        inset: 0,
        width: '100%',
        height: '100%',
        border: 0,
      }}
    />
  );
}
