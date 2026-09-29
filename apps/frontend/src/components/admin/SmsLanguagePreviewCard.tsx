'use client';

/**
 * Farmer SMS — see exactly what a farmer receives, in each language. Preview
 * only: nothing is created and nothing is sent.
 *
 * Until 2026-09-29 this card was an end-to-end demo: it created a "Demo
 * Farmer" subscriber and could dispatch a sample CONFLICT alert (with an
 * invented "ETA 18 h, 120 ha") to every matching subscriber in the tenant —
 * in production that included the real Kebbi cooperative leaders, and
 * conflict alerts are never sent to farmers. It also borrowed a demo
 * organisation's DPA to read the queue. All of that is gone; the preview
 * renders the one farmer SMS that is live, the rainfall advisory, with the
 * same renderer the sender uses.
 */

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { ApiException, notifyFetch } from '@/lib/api';
import { useTenant } from '@/context/TenantContext';

const LANGUAGES: { code: string; label: string }[] = [
  { code: 'ha', label: 'Hausa' },
  { code: 'en', label: 'English' },
  { code: 'fr', label: 'Français' },
  { code: 'pt', label: 'Português' },
  { code: 'yo', label: 'Yorùbá' },
  { code: 'ig', label: 'Igbo' },
];
const SEVERITIES = ['critical', 'high', 'medium'];

interface SmsPreview {
  language: string;
  verified: boolean;
  body: string;
  chars: number;
}

export default function SmsLanguagePreviewCard() {
  const { activeTenantId } = useTenant();
  const [lang, setLang] = useState('ha');
  const [severity, setSeverity] = useState('high');
  const [lga, setLga] = useState('');

  const params = new URLSearchParams({
    lang, tenant_id: activeTenantId, severity, alert_type: 'rainfall',
  });
  if (lga.trim()) params.set('lga', lga.trim());

  const preview = useQuery<SmsPreview, ApiException>({
    queryKey: ['sms-preview', lang, activeTenantId, severity, lga.trim()],
    staleTime: 30 * 1000,
    queryFn: ({ signal }) =>
      notifyFetch<SmsPreview>(`/notify/preview?${params.toString()}`, { signal }),
  });

  return (
    <div className="panel anim a1">
      <div className="panel-header">
        <span className="panel-title">Farmer SMS · Message Preview</span>
        <span className="panel-meta">Rainfall advisory · preview only, nothing is sent</span>
      </div>

      <div className="sms-preview-controls">
        <label className="sms-ctl">
          <span>Language</span>
          <select value={lang} onChange={(e) => setLang(e.target.value)}>
            {LANGUAGES.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
          </select>
        </label>
        <label className="sms-ctl">
          <span>Severity</span>
          <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
            {SEVERITIES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label className="sms-ctl">
          <span>LGA (optional)</span>
          <input type="text" value={lga} placeholder="e.g. Argungu"
            onChange={(e) => setLga(e.target.value)} />
        </label>
      </div>

      <div className="sms-preview-phone">
        {preview.isLoading && <div className="sms-preview-body">Rendering…</div>}
        {preview.isError && (
          <div className="sms-preview-body sms-preview-body--err">
            Notifications service unreachable ({preview.error?.message ?? 'error'}).
          </div>
        )}
        {preview.data && !preview.isError && (
          <>
            <div className="sms-preview-body">{preview.data.body}</div>
            <div className="sms-preview-meta">
              <span>{preview.data.chars} chars · {preview.data.chars <= 160 ? '1 SMS segment' : `${Math.ceil(preview.data.chars / 153)} segments`}</span>
              {preview.data.verified ? (
                <span className="sms-badge sms-badge--ok">REVIEWED</span>
              ) : (
                <span className="sms-badge sms-badge--draft">DRAFT · needs native review</span>
              )}
            </div>
          </>
        )}
      </div>

      <div className="admin-footer">
        The rainfall advisory is the only SMS sent to farmers, automatically, one a day at most.
        Conflict and land-disturbance alerts are never sent to farmers. Subscribers are added
        only through partner agencies (Subscriber upload, above).
      </div>
    </div>
  );
}
