'use client';

import { useAuth } from '@/context/AuthContext';
import { useViewAs } from '@/hooks/useViewAs';
import { useAdminTenants, useMyModules } from '@/hooks/useTenantModules';

export interface EffectiveModules {
  /** Module keys the current view is entitled to, or undefined while loading. */
  modules: string[] | undefined;
  /** True when entitlement should be enforced in the UI (padlocks shown). */
  enforce: boolean;
  /** Label of the account being simulated, when one is. */
  simulating: string | null;
}

/**
 * The entitlements the dashboard should *display* right now.
 *
 * Three cases, in order:
 *   1. Super-admin simulating an account → that organisation's plan, enforced.
 *      This is what makes "show me what they see" truthful rather than a guess.
 *   2. Super-admin normally → no enforcement; they administer plans, not buy them.
 *   3. Everyone else → their own plan via /auth/my-modules.
 *
 * `undefined` modules means "still loading" and callers fail open, matching the
 * existing behaviour — a padlock that flickers on during load is worse than one
 * that appears a beat late.
 */
export function useEffectiveModules(): EffectiveModules {
  const { user, isSuperAdmin } = useAuth();
  const viewAs = useViewAs();
  const simulating = isSuperAdmin ? viewAs : null;

  const { data: ownModules } = useMyModules(Boolean(user) && !isSuperAdmin);
  // Only fetched when actually simulating — the registry is a super-admin call
  // and there is no reason to make it on every ordinary dashboard load.
  const { data: registry } = useAdminTenants(Boolean(simulating));

  if (!simulating) {
    return {
      modules: isSuperAdmin ? undefined : ownModules,
      enforce: !isSuperAdmin,
      simulating: null,
    };
  }

  const target = registry?.tenants.find((t) => t.id === simulating.orgSlug);
  return {
    modules: target
      ? target.modules.filter((m) => m.enabled).map((m) => m.key)
      : undefined,
    enforce: true,
    simulating: simulating.label,
  };
}
