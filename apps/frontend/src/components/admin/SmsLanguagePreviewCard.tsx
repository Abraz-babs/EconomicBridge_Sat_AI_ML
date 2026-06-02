'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { ApiException, notifyFetch } from '@/lib/api';
import { useTenant } from '@/context/TenantContext';

/** Free-tier farmer SMS languages. EN/FR/PT are review-ready; HA/YO/IG are
 *  DRAFT pending native-speaker review (flagged by the server's `verified`). */
const LANGUAGES: { code: string; label: string }[] = [
  { code: 'en', label: 'English' },
  { code: 'fr', label: 'Français' },
  { code: 'pt', label: 'Português' },
  { code: 'ha', label: 'Hausa' },
  { code: 'yo', label: 'Yorùbá' },
  { code: 'ig', label: 'Igbo' },
];
const SEVERITIES = ['critical', 'high', 'medium', 'low'];
const ALERT_TYPES = ['conflict', 'flood', 'drought', 'fire'];

interface SmsPreview {
  language: string;
  verified: boolean;
  body: string;
  chars: number;
}

/**
 * Demo card: pick a farmer's SMS language and see the exact message the
 * platform would send, rendered by the real notifications renderer
 * (/notify/preview). Makes the multilingual free-tier SMS visible.
 */
export default function SmsLanguagePreviewCard() {
  const { activeTenantId } = useTenant();
  const [lang, setLang] = useState('ha');
  const [severity, setSeverity] = useState('critical');
  const [alertType, setAlertType] = useState('conflict');
  const [lga, setLga] = useState('');

  const params = new URLSearchParams({
    lang,
    tenant_id: activeTenantId,
    severity,
    alert_type: alertType,
  });
  if (lga.trim()) params.set('lga', lga.trim());

  const { data, isLoading, isError, error } = useQuery<SmsPreview, ApiException>({
    queryKey: ['sms-preview', lang, activeTenantId, severity, alertType, lga.trim()],
    staleTime: 30 * 1000,
    queryFn: ({ signal }) =>
      notifyFetch<SmsPreview>(`/notify/preview?${params.toString()}`, { signal }),
  });

  return (
    <div className="panel anim a1">
      <div className="panel-header">
        <span className="panel-title">Farmer SMS · Language Preview</span>
        <span className="panel-meta">Free-tier · 6 languages · live render</span>
      </div>

      <div className="sms-preview-controls">
        <label className="sms-ctl">
          <span>Language</span>
          <select value={lang} onChange={(e) => setLang(e.target.value)}>
            {LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>{l.label}</option>
            ))}
          </select>
        </label>
        <label className="sms-ctl">
          <span>Severity</span>
          <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
            {SEVERITIES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label className="sms-ctl">
          <span>Alert type</span>
          <select value={alertType} onChange={(e) => setAlertType(e.target.value)}>
            {ALERT_TYPES.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
        <label className="sms-ctl">
          <span>LGA (optional)</span>
          <input
            type="text"
            value={lga}
            placeholder="e.g. Logo"
            onChange={(e) => setLga(e.target.value)}
          />
        </label>
      </div>

      <div className="sms-preview-phone">
        {isLoading && <div className="sms-preview-body">Rendering…</div>}
        {isError && (
          <div className="sms-preview-body sms-preview-body--err">
            Notifications service unreachable ({error?.message ?? 'error'}).
          </div>
        )}
        {data && !isError && (
          <>
            <div className="sms-preview-body">{data.body}</div>
            <div className="sms-preview-meta">
              <span>{data.chars} chars · {data.chars <= 160 ? '1 SMS segment' : `${Math.ceil(data.chars / 153)} segments`}</span>
              {data.verified ? (
                <span className="sms-badge sms-badge--ok">REVIEW-READY</span>
              ) : (
                <span className="sms-badge sms-badge--draft">DRAFT · needs native review</span>
              )}
            </div>
          </>
        )}
      </div>

      <div className="admin-footer">
        Push-only free-tier alerts to farmers (no app, no signup). Numbers sourced
        via partner agencies. English/French/Portuguese are review-ready; Hausa,
        Yorùbá and Igbo are draft translations pending native-speaker sign-off
        before production sends.
      </div>
    </div>
  );
}
