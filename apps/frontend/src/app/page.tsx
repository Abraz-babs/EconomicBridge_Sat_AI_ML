'use client';

/**
 * Front door (route `/`). The EconomicBridge front page (`public/home.html`,
 * chosen 2026-09-25: the Night Survey village map as the face) is embedded
 * full-bleed so editing it stays a single-file job. Its platform buttons
 * navigate the top window to the EconomicBridge landing page (`/landing`),
 * which in turn opens the dashboard (`/dashboard`). The Bizra Farms company
 * page stays at `/bizra.html`, linked from the front page.
 *
 * To go back to the previous front door, set src to "/bizra.html".
 *
 * Flow: `/` (front page) → `/landing` (EconomicBridge) → `/dashboard` (Overview).
 */
export default function FrontDoor() {
  return (
    <iframe
      src="/home.html"
      title="EconomicBridge by Bizra Farms Integrated"
      className="frame-fullbleed"
    />
  );
}
