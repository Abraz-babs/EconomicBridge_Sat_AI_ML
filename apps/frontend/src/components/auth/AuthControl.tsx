'use client';

import { useState } from 'react';

import { useAuth } from '@/context/AuthContext';
import { ApiException } from '@/lib/api';

/**
 * Header sign-in control. Anonymous visitors see a "Sign in" button (the public
 * dashboard works without it); signed-in users see their identity + Sign out.
 * Super-admin sign-in is what reveals the Admin Panel tab.
 */
export default function AuthControl() {
  const { user, isSuperAdmin, loading, login, logout } = useAuth();
  const [open, setOpen] = useState(false);

  if (loading) return null;

  if (user) {
    return (
      <div className="auth-control">
        <span className="auth-who" title={user.email}>
          {user.full_name || user.email}
          <span className="auth-role">{isSuperAdmin ? 'Super-admin' : user.role}</span>
        </span>
        <button type="button" className="auth-btn" onClick={() => logout()}>
          Sign out
        </button>
      </div>
    );
  }

  return (
    <>
      <button type="button" className="auth-btn" onClick={() => setOpen(true)}>
        Sign in
      </button>
      {open && <LoginModal onClose={() => setOpen(false)} login={login} />}
    </>
  );
}

function LoginModal({
  onClose,
  login,
}: {
  onClose: () => void;
  login: (email: string, password: string) => Promise<void>;
}) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
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
          Operator &amp; tenant accounts only. The public dashboard needs no sign-in.
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
