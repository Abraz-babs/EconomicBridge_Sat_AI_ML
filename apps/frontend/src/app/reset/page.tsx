'use client';

import { Suspense, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

import { ApiException, apiFetch } from '@/lib/api';

/**
 * Password reset — the landing page for the reset link emailed by
 * POST /auth/forgot-password. Reads `?token=…`, lets the user choose a new
 * password, then sends them to the dashboard to SIGN IN (no auto-login by
 * design: a reset also revokes every existing session).
 */
export default function ResetPage() {
  return (
    <Suspense fallback={<div className="activate-wrap"><div className="activate-card">Loading…</div></div>}>
      <ResetForm />
    </Suspense>
  );
}

function ResetForm() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get('token') ?? '';

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const tooShort = password.length > 0 && password.length < 8;
  const mismatch = confirm.length > 0 && confirm !== password;
  const canSubmit = token && password.length >= 8 && password === confirm && !busy;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      // apiFetch stringifies the body itself — pass the raw object.
      await apiFetch('/auth/reset-password', {
        method: 'POST',
        body: { token, password },
        noAuth: true,
      });
      setDone(true);
      setTimeout(() => router.push('/dashboard'), 1800);
    } catch (e) {
      let msg = 'Password reset failed.';
      if (e instanceof ApiException) {
        msg = e.code === 'RESET_INVALID'
          ? 'This reset link is invalid or has expired — request a new one from the sign-in screen.'
          : e.message;
      }
      setError(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="activate-wrap">
      <div className="activate-card">
        <h1 className="activate-title">Reset your EconomicBridge password</h1>

        {!token && (
          <div className="auth-error">
            No reset token in the link. Please use the link from your reset email,
            or request a new one from the sign-in screen.
          </div>
        )}

        {done ? (
          <div className="activate-ok">
            Password updated — sign in with your new password. Taking you to the dashboard…
          </div>
        ) : (
          <>
            <p className="activate-sub">Choose a new password for your account.</p>
            <label className="upload-field">
              <span className="upload-field-label">New password (min 8 characters)</span>
              <input type="password" value={password} disabled={!token}
                onChange={(e) => setPassword(e.target.value)} />
            </label>
            <label className="upload-field">
              <span className="upload-field-label">Confirm password</span>
              <input type="password" value={confirm} disabled={!token}
                onChange={(e) => setConfirm(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && canSubmit && submit()} />
            </label>
            {tooShort && <div className="auth-hint">Password must be at least 8 characters.</div>}
            {mismatch && <div className="auth-hint">Passwords don&apos;t match.</div>}
            {error && <div className="auth-error">{error}</div>}
            <button type="button" className="auth-btn auth-btn--go activate-submit"
              onClick={submit} disabled={!canSubmit}>
              {busy ? 'Updating…' : 'Set new password'}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
