'use client';

import type { Tenant } from '@/data/tenants';

/**
 * Shown above a module when the active tenant is a newly-registered region with
 * no live data yet (the pilots are `active: true`; everything else is `false`).
 *
 * A freshly-provisioned tenant gets an empty schema — its tables exist but hold
 * no alerts/predictions/fires, so maps render without halos and stats read zero.
 * Rather than look broken, this explains that feeds are being provisioned.
 */
export default function EmptyRegion({ tenant }: { tenant: Tenant }) {
  return (
    <div className="empty-region" role="status">
      <div className="empty-region-icon" aria-hidden="true">🛰️</div>
      <div className="empty-region-body">
        <div className="empty-region-title">
          No live data yet for {tenant.name}
        </div>
        <p className="empty-region-text">
          {tenant.name} was recently added to EconomicBridge. Its satellite and
          alert feeds are being provisioned — events, map halos and statistics
          will appear here once ingestion runs for this region. In the meantime,
          the active pilot regions (Kebbi, Benue, Plateau…) have live data you
          can explore from the tenant selector.
        </p>
      </div>
    </div>
  );
}
