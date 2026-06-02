'use client';

import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';

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

// Demo-only org with a signed DPA across all pilots (see scripts/seed_demo_dpa.py).
// The dispatch endpoint is DPA-gated; this authorises the dashboard demo. In dev
// the gateway is the mock (no real SMS is sent).
const DEMO_ORG_ID =
  process.env.NEXT_PUBLIC_DEMO_ORG_ID ?? '025a16c3-4c64-4115-b320-f5dbd8d8bc03';

interface SmsPreview {
  language: string;
  verified: boolean;
  body: string;
  chars: number;
}

interface DispatchSummary {
  subscriber_id: string;
  phone_e164: string;
  provider: string;
  status: string;
}
interface NotifyResult {
  matched_subscribers: number;
  dispatched: number;
  skipped_duplicate: number;
  failed: number;
  provider_chosen: string;
  dispatches: DispatchSummary[];
}

interface OutboxRow {
  language: string;
  status: string;
  provider: string;
  severity: string | null;
  alert_type: string | null;
  phone_masked: string;
  message: string;
  queued_at: string;
}

export default function SmsLanguagePreviewCard() {
  const { activeTenantId } = useTenant();
  const [lang, setLang] = useState('ha');
  const [severity, setSeverity] = useState('critical');
  const [alertType, setAlertType] = useState('conflict');
  const [lga, setLga] = useState('');
  const [phone, setPhone] = useState('+2348000000001');
  const [note, setNote] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const params = new URLSearchParams({
    lang, tenant_id: activeTenantId, severity, alert_type: alertType,
  });
  if (lga.trim()) params.set('lga', lga.trim());

  const preview = useQuery<SmsPreview, ApiException>({
    queryKey: ['sms-preview', lang, activeTenantId, severity, alertType, lga.trim()],
    staleTime: 30 * 1000,
    queryFn: ({ signal }) =>
      notifyFetch<SmsPreview>(`/notify/preview?${params.toString()}`, { signal }),
  });

  const createSub = useMutation<{ id: string }, ApiException>({
    mutationFn: () =>
      notifyFetch<{ id: string }>('/subscribers', {
        method: 'POST',
        tenantId: activeTenantId,
        body: {
          full_name: 'Demo Farmer',
          phone_e164: phone.trim(),
          language: lang,
          lga: lga.trim() || null,
          severity_threshold: 'all',
          channel: 'sms',
        },
      }),
    onSuccess: () => {
      setNote(`✓ Test subscriber created in ${lang.toUpperCase()} (threshold: all).`);
      setRefreshKey((k) => k + 1);
    },
    onError: (e) => setNote(`Create failed: ${e.message}`),
  });

  const dispatch = useMutation<NotifyResult, ApiException>({
    mutationFn: () =>
      notifyFetch<NotifyResult>('/notify/conflict', {
        method: 'POST',
        tenantId: activeTenantId,
        headers: { 'X-Organisation-Id': DEMO_ORG_ID },
        body: {
          tenant_id: activeTenantId,
          severity,
          alert_type: alertType,
          lga: lga.trim() || null,
          eta_hours: 18,
          affected_area_ha: 120,
        },
      }),
    onSuccess: (r) => {
      setNote(
        `✓ Dispatched via ${r.provider_chosen}: matched ${r.matched_subscribers}, ` +
          `queued/sent ${r.dispatched}, skipped ${r.skipped_duplicate}, failed ${r.failed}. ` +
          `Each subscriber gets the message in their own language.`,
      );
      setRefreshKey((k) => k + 1);
    },
    onError: (e) => setNote(`Dispatch failed: ${e.message}`),
  });

  const outbox = useQuery<{ rows: OutboxRow[] }, ApiException>({
    queryKey: ['sms-outbox', activeTenantId, refreshKey],
    staleTime: 10 * 1000,
    queryFn: ({ signal }) =>
      notifyFetch<{ rows: OutboxRow[] }>('/notify/outbox?limit=6', {
        tenantId: activeTenantId,
        headers: { 'X-Organisation-Id': DEMO_ORG_ID },
        signal,
      }),
  });

  const busy = createSub.isPending || dispatch.isPending;

  return (
    <div className="panel anim a1">
      <div className="panel-header">
        <span className="panel-title">Farmer SMS · Language Preview + Test Queue</span>
        <span className="panel-meta">Free-tier · 6 languages · live render</span>
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
          <span>Alert type</span>
          <select value={alertType} onChange={(e) => setAlertType(e.target.value)}>
            {ALERT_TYPES.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
        <label className="sms-ctl">
          <span>LGA (optional)</span>
          <input type="text" value={lga} placeholder="e.g. Logo"
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
                <span className="sms-badge sms-badge--ok">REVIEW-READY</span>
              ) : (
                <span className="sms-badge sms-badge--draft">DRAFT · needs native review</span>
              )}
            </div>
          </>
        )}
      </div>

      <div className="sms-demo-actions">
        <label className="sms-ctl">
          <span>Test phone (E.164)</span>
          <input type="text" value={phone} onChange={(e) => setPhone(e.target.value)} />
        </label>
        <button type="button" className="sms-btn" disabled={busy} onClick={() => { setNote(null); createSub.mutate(); }}>
          {createSub.isPending ? 'Creating…' : '1 · Create test subscriber'}
        </button>
        <button type="button" className="sms-btn sms-btn--go" disabled={busy} onClick={() => { setNote(null); dispatch.mutate(); }}>
          {dispatch.isPending ? 'Dispatching…' : '2 · Send test alert → queue'}
        </button>
      </div>

      {note && <div className="sms-result">{note}</div>}

      {outbox.data && outbox.data.rows.length > 0 && (
        <div className="sms-outbox">
          <div className="sms-outbox-title">
            Recent queue · sms_outbox ({activeTenantId})
          </div>
          {outbox.data.rows.map((r, i) => (
            <div key={i} className="sms-outbox-row">
              <span className={`sms-dot sms-dot--${r.status}`} />
              <span className="sms-outbox-lang">{r.language.toUpperCase()}</span>
              <span className="sms-outbox-phone">{r.phone_masked}</span>
              <span className="sms-outbox-msg">{r.message}</span>
            </div>
          ))}
        </div>
      )}

      <div className="admin-footer">
        End-to-end demo: create a farmer subscriber in the chosen language, then
        dispatch an alert — the queue (sms_outbox) gets the message rendered in
        each subscriber&apos;s language via the mock gateway (no real SMS in dev).
        EN/FR/PT are review-ready; HA/YO/IG are drafts pending native-speaker
        sign-off before production sends.
      </div>
    </div>
  );
}
