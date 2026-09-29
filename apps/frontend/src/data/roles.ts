/**
 * Access profiles — what the signed-in account really is and can really do.
 *
 * Replaced 2026-09-29 (operator: "make anything fake become real"). This file
 * used to hold a "View as" demo: four personas named after real organisations
 * (CARE International, the Federal Ministry, OCHA, MIT's Poverty Action Lab),
 * each with invented headline figures ("8.1M households mapped", "34 countries
 * monitored") and an access matrix nothing enforced. Now the header, banner
 * and access panel are computed from the real account (context/RoleContext):
 *
 *   visitor  — not signed in: the Overview is open; modules need an account.
 *   partner  — a signed-in organisation: the modules its plan includes, and
 *              reports on them. Downloads are prepared by EconomicBridge.
 *   operator — the platform operator (super-admin): everything, including
 *              downloads and the Admin panel.
 *
 * Every rule here is the one the API enforces: module access is the
 * tenant_modules middleware, downloads are require_super_admin.
 */

export type AccessKind = 'visitor' | 'partner' | 'operator';

export interface AccessProfile {
  kind: AccessKind;
  /** Organisation shown in the header pill — the real one, or "Public view". */
  label: string;
  access: string;
  dot: string;
  pillBg: string;
  banner: { text: string; bg: string; color: string };
  navLocked: string[];
}

const STYLE: Record<AccessKind, { dot: string; pillBg: string; bg: string; color: string; access: string }> = {
  visitor: { dot: '#8a8278', pillBg: '#f4f2ee', bg: '#f4f2ee', color: '#4a453e', access: 'PUBLIC VIEW' },
  partner: { dot: '#52b788', pillBg: '#f0faf4', bg: '#f0faf4', color: '#2d6a4f', access: 'PARTNER ACCESS' },
  operator: { dot: '#c97d00', pillBg: '#fdf8ee', bg: '#fdf8ee', color: '#7b4f00', access: 'PLATFORM OPERATOR' },
};

export const accentColors: Record<AccessKind, string> = {
  visitor: '#8a8278',
  partner: '#52b788',
  operator: '#c97d00',
};

export function accessProfile(kind: AccessKind, org: string | null, opts: { simulating?: boolean } = {}): AccessProfile {
  const s = STYLE[kind];
  let text: string;
  if (kind === 'visitor') {
    text = 'Public view — the Overview is open to everyone. Sign in to open the modules your organisation subscribes to.';
  } else if (opts.simulating) {
    text = `Viewing as ${org ?? 'this account'} — exactly what their account can open. Downloads stay with the platform operator.`;
  } else if (kind === 'partner') {
    text = `Signed in as ${org ?? 'your organisation'} — you can open the modules your plan includes and read their reports. Data files are prepared by EconomicBridge on request.`;
  } else {
    text = 'Platform operator — full access, including downloads and the Admin panel. Requests are audit-logged.';
  }
  return {
    kind,
    label: kind === 'visitor' ? 'Public view' : (org ?? 'Your organisation'),
    access: opts.simulating ? 'VIEWING AS' : s.access,
    dot: s.dot,
    pillBg: s.pillBg,
    banner: { text, bg: s.bg, color: s.color },
    navLocked: kind === 'operator' && !opts.simulating ? [] : ['navAdmin'],
  };
}

/** Modules in the access panel, keyed like the dashboard tabs and tenant_modules. */
export const ACCESS_MODULES: { key: string; label: string }[] = [
  { key: 'economic-visibility', label: 'Poverty Mapping (Economic Visibility)' },
  { key: 'aid-coordination', label: 'Aid Coordination Bridge' },
  { key: 'farmland', label: 'Farmland Protection' },
  { key: 'cropguard', label: 'Agriculture (CropGuard)' },
  { key: 'shockguard', label: 'Disaster Relief (ShockGuard)' },
  { key: 'mobility-compass', label: 'Mobility Compass' },
  { key: 'skillsbridge', label: 'SkillsBridge' },
];

export const matrixHeaders = ['Module', 'View', 'Reports', 'Download'];
