'use client';

import type { Tenant } from '@/data/tenants';

/**
 * Shown when the active tenant isn't entitled to the module being viewed. The
 * API enforces this with a 403 (MODULE_NOT_SUBSCRIBED); we check the tenant's
 * entitlement list up front and render this instead of the module, so the user
 * never sees a raw "API unreachable"-style error. The nav also hides
 * unsubscribed module tabs — this covers the case where the tenant is switched
 * while a module is already open.
 */
export default function NotSubscribed({
  tenant,
  moduleLabel,
  isSuperAdmin,
}: {
  tenant: Tenant;
  moduleLabel: string;
  isSuperAdmin: boolean;
}) {
  return (
    <div className="not-subscribed" role="status">
      <div className="not-subscribed-icon" aria-hidden="true">🔒</div>
      <div>
        <div className="not-subscribed-title">
          {tenant.name} isn’t subscribed to {moduleLabel}
        </div>
        <p className="not-subscribed-text">
          This region’s plan doesn’t include the {moduleLabel} module.{' '}
          {isSuperAdmin ? (
            <>You can enable it in <strong>Admin Panel → Tenant Registry</strong> by
            toggling {moduleLabel} on for {tenant.name}.</>
          ) : (
            <>Contact the EconomicBridge team to add it to this region’s subscription.</>
          )}
        </p>
      </div>
    </div>
  );
}
