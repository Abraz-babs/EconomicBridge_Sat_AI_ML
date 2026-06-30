'use client';

import { useState } from 'react';

import { useAdminTenants, type TenantCategory } from '@/hooks/useTenantModules';
import {
  useAgencySubscriptions,
  useCreateAgencySubscription,
  useDeleteAgencySubscription,
  useSendAgencyDigests,
} from '@/hooks/useAgencyAlerts';

// Module → the agency duty it serves. Drives the picker + the helper line.
const MODULES = [
  { key: 'shockguard', label: 'ShockGuard — flood / drought (NEMA · SEMA)' },
  { key: 'farmland', label: 'Farmland — encroachment / land-disturbance (security · agric)' },
  { key: 'cropguard', label: 'CropGuard — crop stress (agriculture)' },
];

const SEVERITIES = [
  { key: 'critical', label: 'Critical only' },
  { key: 'high', label: 'High & above' },
  { key: 'medium', label: 'Medium & above' },
  { key: 'all', label: 'All alerts' },
];

/**
 * Super-admin: subscribe a responsible government agency (by email) to the
 * alerts relevant to its duty for a tenant + module. A digest of NEW alerts is
 * emailed in English (on-demand here, or via scripts.send_agency_alerts on a
 * schedule). SMS is a separate, deferred channel.
 */
export default function AgencyAlertsCard() {
  const { data: registry } = useAdminTenants();
  const { data: subs, isLoading } = useAgencySubscriptions();
  const create = useCreateAgencySubscription();
  const del = useDeleteAgencySubscription();
  const send = useSendAgencyDigests();

  // Only GEOGRAPHIC tenants (states/countries) emit map alerts.
  const geoKeys = new Set(
    (registry?.categories as TenantCategory[] | undefined ?? [])
      .filter((c) => c.geographic).map((c) => c.key),
  );
  const tenants = (registry?.tenants ?? []).filter((t) => geoKeys.has(t.tenant_type));

  const [tenantId, setTenantId] = useState('');
  const [module, setModule] = useState('shockguard');
  const [severity, setSeverity] = useState('high');
  const [agency, setAgency] = useState('');
  const [email, setEmail] = useState('');
  const [note, setNote] = useState<string | null>(null);

  function add() {
    setNote(null);
    create.mutate(
      {
        agency_name: agency.trim(),
        recipient_email: email.trim(),
        tenant_id: tenantId || tenants[0]?.id || '',
        module,
        severity_threshold: severity,
      },
      {
        onSuccess: () => { setNote('✓ Agency subscribed.'); setAgency(''); setEmail(''); },
        onError: (e) => setNote(`Failed: ${e.message}`),
      },
    );
  }

  function sendNow(force: boolean) {
    setNote(null);
    send.mutate({ force }, {
      onSuccess: (results) => {
        const emailed = results.filter((r) => r.emailed).length;
        const found = results.reduce((s, r) => s + r.new_alerts, 0);
        setNote(`✓ Ran ${results.length} subscription(s) · ${found} new alert(s) · ${emailed} email(s) sent.`);
      },
      onError: (e) => setNote(`Failed: ${e.message}`),
    });
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Agency Email Alerts</span>
        <span className="panel-meta">{subs?.length ?? 0} subscriptions · English email digest</span>
      </div>
      <div className="upload-body">
        <p className="upload-desc">
          Email a responsible government agency the NEW alerts relevant to its duty
          (e.g. NEMA → ShockGuard flood/drought). Digests are sent in English, on
          demand here or on a schedule via <code>scripts.send_agency_alerts</code>.
          Each agency only receives alerts at or above its chosen severity.
        </p>

        {isLoading && <div className="fp-alert-empty">Loading…</div>}

        {subs && subs.length > 0 && (
          <div className="tr-matrix-wrap">
            <table className="tr-matrix">
              <thead>
                <tr><th>Agency</th><th>Tenant</th><th>Module</th><th>Severity</th><th>Recipient</th><th>Last sent</th><th></th></tr>
              </thead>
              <tbody>
                {subs.map((s) => (
                  <tr key={s.id} style={{ opacity: s.is_active ? 1 : 0.4 }}>
                    <td>{s.agency_name}</td>
                    <td>{s.tenant_id}</td>
                    <td>{s.module}</td>
                    <td>{s.severity_threshold}</td>
                    <td className="srep-email">{s.recipient_email}</td>
                    <td>{s.last_notified_at ? new Date(s.last_notified_at).toLocaleDateString() : '—'}</td>
                    <td>
                      <button type="button" className="tr-invite-btn" disabled={del.isPending}
                        onClick={() => del.mutate(s.id)}>Remove</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="tr-form srep-form">
          <label className="upload-field upload-field--grow"><span className="upload-field-label">Agency name</span>
            <input type="text" value={agency} placeholder="National Emergency Management Agency (NEMA)"
              onChange={(e) => setAgency(e.target.value)} /></label>
          <label className="upload-field upload-field--grow"><span className="upload-field-label">Recipient email</span>
            <input type="email" value={email} placeholder="ops@nema.gov.ng"
              onChange={(e) => setEmail(e.target.value)} /></label>
          <label className="upload-field"><span className="upload-field-label">Tenant</span>
            <select value={tenantId} onChange={(e) => setTenantId(e.target.value)}>
              {tenants.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select></label>
          <label className="upload-field"><span className="upload-field-label">Module / duty</span>
            <select value={module} onChange={(e) => setModule(e.target.value)}>
              {MODULES.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
            </select></label>
          <label className="upload-field"><span className="upload-field-label">Severity</span>
            <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
              {SEVERITIES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select></label>
        </div>
        <div className="sms-demo-actions">
          <button type="button" className="sms-btn sms-btn--go"
            disabled={create.isPending || !agency.trim() || !email.trim() || tenants.length === 0}
            onClick={add}>
            {create.isPending ? 'Subscribing…' : 'Subscribe agency'}
          </button>
          <button type="button" className="sms-btn"
            disabled={send.isPending || !subs?.length}
            onClick={() => sendNow(false)}>
            {send.isPending ? 'Sending…' : 'Send new alerts now'}
          </button>
          <button type="button" className="sms-btn"
            disabled={send.isPending || !subs?.length}
            onClick={() => sendNow(true)}>
            Send test digest (force)
          </button>
        </div>
        {note && <div className="sms-result">{note}</div>}
      </div>
    </div>
  );
}
