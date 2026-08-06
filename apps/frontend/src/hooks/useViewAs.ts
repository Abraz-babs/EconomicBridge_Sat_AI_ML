'use client';

import { useSyncExternalStore } from 'react';

const STORAGE_KEY = 'eb.viewAs';

export interface ViewAsTarget {
  /** tenant_registry id of the account's organisation (e.g. "nasrda"). */
  orgSlug: string;
  /** What to show in the banner — the org's display name. */
  label: string;
}

/**
 * "View as" — lets the super-admin see the dashboard the way a given account
 * sees it, so a support complaint can be reproduced rather than guessed at.
 *
 * The super-admin can already *read* every tenant's data (the API's tenant
 * middleware exempts them), so the data is never the difference. What differs
 * is entitlement: a super-admin is never padlocked, so modules an account
 * cannot open still look open to the operator. This carries the account's
 * organisation so the nav and dashboard apply that org's plan instead.
 *
 * It is a DISPLAY simulation only — it changes no headers and grants no
 * rights. It cannot show more than the operator could already see, and it
 * never lets the operator act as the account.
 *
 * Backed by sessionStorage rather than localStorage: a simulated view should
 * not still be running silently in a tab opened next week. Read through
 * `useSyncExternalStore` so the server renders "not simulating" and the
 * stored value is picked up on hydration without a cascading setState.
 */

let current: ViewAsTarget | null = null;
let hydrated = false;
const listeners = new Set<() => void>();

function emit(): void {
  for (const l of listeners) l();
}

function hydrate(): void {
  hydrated = true;
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (raw) {
      current = JSON.parse(raw) as ViewAsTarget;
      emit();
    }
  } catch {
    // Corrupt or unavailable storage just means no simulation — never fatal.
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (!hydrated) hydrate();
  return () => { listeners.delete(listener); };
}

// Referentially stable between changes, which useSyncExternalStore requires.
function getSnapshot(): ViewAsTarget | null { return current; }
function getServerSnapshot(): ViewAsTarget | null { return null; }

export function setViewAs(target: ViewAsTarget): void {
  current = target;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(target));
  } catch { /* private mode — the simulation still works for this session */ }
  emit();
}

export function clearViewAs(): void {
  current = null;
  try { window.sessionStorage.removeItem(STORAGE_KEY); } catch { /* as above */ }
  emit();
}

/** The account currently being simulated, or null. */
export function useViewAs(): ViewAsTarget | null {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
