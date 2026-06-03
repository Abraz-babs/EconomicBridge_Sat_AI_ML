'use client';

import { useState } from 'react';

import { useAuth } from '@/context/AuthContext';
import { ApiException } from '@/lib/api';

/**
 * Reusable sign-in modal. Used by the header AuthControl and by the
 * "registration required" prompt when an anonymous visitor opens a module.
 */
export default function LoginModal({
  onClose,
  onSuccess,
}: {
  onClose: () => void;
  onSuccess?: () => void;
}) {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
      onSuccess?.();
      onClose();
    } catch (e) {
      const msg =
        e instanceof ApiException && e.status === 401
          ? 'Invalid email or password.'
          : e instanceof Error
            ? e.message
            : 'Sign-in failed.';
      setError(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-overlay" role="dialog" aria-modal="true" aria-label="Sign in" onClick={onClose}>
      <div className="auth-modal" onClick={(e) => e.stopPropagation()}>
        <h2 className="auth-modal-title">Sign in</h2>
        <p className="auth-modal-sub">
          Operator &amp; tenant accounts only. The public overview needs no sign-in.
        </p>
        <label className="upload-field">
          <span className="upload-field-label">Email</span>
          <input
            type="email"
            value={email}
            autoFocus
            placeholder="you@org.example"
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
          />
        </label>
        <label className="upload-field">
          <span className="upload-field-label">Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
          />
        </label>
        {error && <div className="auth-error">{error}</div>}
        <div className="auth-modal-actions">
          <button type="button" className="auth-btn auth-btn--ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="button"
            className="auth-btn auth-btn--go"
            onClick={submit}
            disabled={busy || !email.trim() || !password}
          >
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </div>
      </div>
    </div>
  );
}
