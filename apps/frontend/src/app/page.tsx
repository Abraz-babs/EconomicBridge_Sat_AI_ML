'use client';

/**
 * Front door (route `/`). The first thing a visitor sees is the Bizra Farms
 * Integrated corporate site, which presents the company and bridges into the
 * EconomicBridge platform. It lives as a self-contained static page at
 * `public/bizra.html` (its own styles + images under `public/bizra-assets/`);
 * we embed it full-bleed so editing it stays a single-file job. Its
 * "Enter Platform" buttons navigate the top window to the EconomicBridge
 * landing page (`/landing`), which in turn opens the dashboard (`/dashboard`).
 *
 * Flow: `/` (Bizra) → `/landing` (EconomicBridge) → `/dashboard` (Overview).
 */
export default function BizraFrontDoor() {
  return (
    <iframe
      src="/bizra.html"
      title="Bizra Farms Integrated — EconomicBridge"
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
