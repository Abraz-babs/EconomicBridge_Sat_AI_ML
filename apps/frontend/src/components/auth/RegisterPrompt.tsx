'use client';

import { useState } from 'react';

import LoginModal from '@/components/auth/LoginModal';

/**
 * Shown when an anonymous visitor tries to open a gated module. The overview is
 * open-access; every other module needs a registered account. There's no
 * self-serve signup (tenants are provisioned by the EconomicBridge team after an
 * MoU/subscription), so this offers Sign in for existing accounts + a "request
 * access" path for everyone else.
 */
export default function RegisterPrompt({
  moduleLabel,
  onClose,
}: {
  moduleLabel: string;
  onClose: () => void;
}) {
  const [showLogin, setShowLogin] = useState(false);

  if (showLogin) {
    return <LoginModal onClose={onClose} onSuccess={onClose} />;
  }

  return (
    <div className="auth-overlay" role="dialog" aria-modal="true" aria-label="Registration required" onClick={onClose}>
      <div className="auth-modal" onClick={(e) => e.stopPropagation()}>
        <h2 className="auth-modal-title">Registration required</h2>
        <p className="auth-modal-sub">
          The <strong>{moduleLabel}</strong> module is available to registered
          organisations. The public overview stays open — sign in to continue, or
          request access for your organisation.
        </p>
        <div className="auth-modal-actions">
          <a
            className="auth-btn auth-btn--ghost"
            href="mailto:hello@economicbridge.app?subject=EconomicBridge%20access%20request"
          >
            Request access
          </a>
          <button type="button" className="auth-btn auth-btn--go" onClick={() => setShowLogin(true)}>
            Sign in
          </button>
        </div>
      </div>
    </div>
  );
}
