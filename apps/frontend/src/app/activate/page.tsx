'use client';

import { Suspense, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

import { useAuth } from '@/context/AuthContext';
import { ApiException } from '@/lib/api';

/**
 * Account activation — the landing page for the invite link emailed to a newly
 * registered tenant. Reads `?token=…`, lets the user set their first password,
 * activates the account (which signs them in), and sends them to the dashboard.
 */
export default function ActivatePage() {
  return (
    <Suspense fallback={<div className="activate-wrap"><div className="activate-card">Loading…</div></div>}>
      <ActivateForm />
    </Suspense>
  );
}

function ActivateForm() {
  const params = useSearchParams();
  const router = useRouter();
  const { activate } = useAuth();
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
      await activate(token, password);
      setDone(true);
      setTimeout(() => router.push('/dashboard'), 1200);
    } catch (e) {
      let msg = 'Activation failed.';
      if (e instanceof ApiException) {
        if (e.code === 'INVITE_INVALID') msg = 'This activation link is invalid or has expired. Ask your administrator to re-send it.';
        else if (e.code === 'ALREADY_ACTIVE') msg = 'This account is already active — please sign in from the dashboard.';
        else msg = e.message;
      }
      setError(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="activate-wrap">
      <div className="activate-card">
        <h1 className="activate-title">Activate your EconomicBridge account</h1>

        {!token && (
          <div className="auth-error">No activation token in the link. Please use the link from your invite email.</div>
        )}

        {done ? (
          <div className="activate-ok">Account activated — signing you in…</div>
        ) : (
          <>
            <p className="activate-sub">Choose a password to finish setting up your account.</p>
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
              {busy ? 'Activating…' : 'Activate & sign in'}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
