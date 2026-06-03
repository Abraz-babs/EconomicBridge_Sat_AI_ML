'use client';

import { useState } from 'react';

import { useAuth } from '@/context/AuthContext';
import LoginModal from '@/components/auth/LoginModal';

/**
 * Header sign-in control. Anonymous visitors see a "Sign in" button (the public
 * overview works without it); signed-in users see their identity + Sign out.
 * Super-admin sign-in is what reveals the Admin Panel tab.
 */
export default function AuthControl() {
  const { user, isSuperAdmin, loading, logout } = useAuth();
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
      {open && <LoginModal onClose={() => setOpen(false)} />}
    </>
  );
}
