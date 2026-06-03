'use client';

import { useRole } from '@/context/RoleContext';
import { useState, useEffect } from 'react';
import AuthControl from '@/components/auth/AuthControl';

export default function Header() {
  const { roleConfig } = useRole();
  const [time, setTime] = useState('');

  useEffect(() => {
    const tick = () => {
      setTime(new Date().toUTCString().replace(' GMT', '') + ' UTC');
    };
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header role="banner">
      <div className="logo">
        <h1 className="logo-word">EconomicBridge</h1>
        <span className="logo-tagline">
          AI &amp; Satellite Mapping for Aid Delivery Optimization · Bizra Farms
        </span>
      </div>
      <div className="header-right">
        <div className="org-pill" style={{ background: roleConfig.pillBg }} aria-label={`Current organisation: ${roleConfig.label}`}>
          <div className="org-dot" style={{ background: roleConfig.dot }} aria-hidden="true" />
          <span>{roleConfig.label}</span>
        </div>
        <div
          className="access-level"
          style={{
            background: roleConfig.pillBg,
            color: roleConfig.dot,
          }}
          aria-label={`Access level: ${roleConfig.access}`}
        >
          {roleConfig.access}
        </div>
        <time className="clock" aria-label="Current UTC time" suppressHydrationWarning>
          {time || '—'}
        </time>
        <AuthControl />
      </div>
    </header>
  );
}
