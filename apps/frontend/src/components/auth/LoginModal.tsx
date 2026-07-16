'use client';

import { useState } from 'react';

import { useAuth } from '@/context/AuthContext';
import { ApiException, apiFetch } from '@/lib/api';

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
  // Forgot-password mini-flow: 'idle' → 'form' (email input) → 'sent'.
  const [forgot, setForgot] = useState<'idle' | 'form' | 'sent'>('idle');

  async function requestReset() {
    setBusy(true);
    setError(null);
    try {
      // apiFetch stringifies the body itself — pass the raw object
      // (double-encoding sent a JSON string and the API 422'd; live bug 2026-07-17).
      await apiFetch('/auth/forgot-password', {
        method: 'POST',
        body: { email: email.trim() },
        noAuth: true,
      });
      setForgot('sent');
    } catch (e) {
      setError(
        e instanceof ApiException && e.status === 429
          ? 'Too many reset requests — please try again in a few minutes.'
          : 'Could not send the reset email. Please try again.',
      );
    } finally {
      setBusy(false);
    }
  }

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

  // ── Forgot-password views ────────────────────────────────────────────
  if (forgot !== 'idle') {
    return (
      <div className="auth-overlay" role="dialog" aria-modal="true" aria-label="Reset password" onClick={onClose}>
        <div className="auth-modal" onClick={(e) => e.stopPropagation()}>
          <h2 className="auth-modal-title">Reset password</h2>
          {forgot === 'sent' ? (
            <>
              <p className="auth-modal-sub">
                If an account exists for <strong>{email.trim()}</strong>, a reset
                link is on its way (valid for 2 hours). Check your inbox — and
                the spam folder, just in case.
              </p>
              <div className="auth-modal-actions">
                <button type="button" className="auth-btn auth-btn--go" onClick={() => setForgot('idle')}>
                  Back to sign in
                </button>
              </div>
            </>
          ) : (
            <>
              <p className="auth-modal-sub">
                Enter your account email and we&apos;ll send you a link to choose
                a new password.
              </p>
              <label className="upload-field">
                <span className="upload-field-label">Email</span>
                <input
                  type="email"
                  value={email}
                  autoFocus
                  placeholder="you@org.example"
                  onChange={(e) => setEmail(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && email.trim() && !busy && requestReset()}
                />
              </label>
              {error && <div className="auth-error">{error}</div>}
              <div className="auth-modal-actions">
                <button type="button" className="auth-btn auth-btn--ghost" onClick={() => setForgot('idle')} disabled={busy}>
                  Back
                </button>
                <button
                  type="button"
                  className="auth-btn auth-btn--go"
                  onClick={requestReset}
                  disabled={busy || !email.trim()}
                >
                  {busy ? 'Sending…' : 'Send reset link'}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    );
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
        <button
          type="button"
          onClick={() => { setError(null); setForgot('form'); }}
          style={{
            background: 'none', border: 'none', padding: 0, cursor: 'pointer',
            font: 'inherit', fontSize: '12px', color: 'var(--green, #1f8a3b)',
            textDecoration: 'underline', textAlign: 'left',
          }}
        >
          Forgot password?
        </button>
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
