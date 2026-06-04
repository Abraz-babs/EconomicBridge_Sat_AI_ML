'use client';

import { useState } from 'react';

import { useAdminTenants, type TenantCategory } from '@/hooks/useTenantModules';
import {
  useReportModules,
  useReportSubscriptions,
  useCreateReportSubscription,
  useDeleteReportSubscription,
} from '@/hooks/useReports';

/**
 * Super-admin: schedule recurring report emails. Each subscription emails a
 * tenant+module PDF to a recipient on a cadence (monthly / quarterly). A
 * scheduled job (scripts/send_scheduled_reports.py) does the sending.
 */
export default function ScheduledReportsCard() {
  const { data: registry } = useAdminTenants();
  const { data: modules } = useReportModules();
  const { data: subs, isLoading } = useReportSubscriptions();
  const create = useCreateReportSubscription();
  const del = useDeleteReportSubscription();

  // Only GEOGRAPHIC tenants have report data.
  const geoKeys = new Set(
    (registry?.categories as TenantCategory[] | undefined ?? [])
      .filter((c) => c.geographic).map((c) => c.key),
  );
  const tenants = (registry?.tenants ?? []).filter((t) => geoKeys.has(t.tenant_type));
  const moduleList = modules ?? [];

  const [tenantId, setTenantId] = useState('');
  const [module, setModule] = useState('farmland');
  const [frequency, setFrequency] = useState('monthly');
  const [email, setEmail] = useState('');
  const [note, setNote] = useState<string | null>(null);

  function add() {
    setNote(null);
    create.mutate(
      { tenant_id: tenantId || tenants[0]?.id || '', module, frequency, recipient_email: email.trim() },
      {
        onSuccess: () => { setNote('✓ Scheduled.'); setEmail(''); },
        onError: (e) => setNote(`Failed: ${e.message}`),
      },
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Scheduled Reports</span>
        <span className="panel-meta">{subs?.length ?? 0} subscriptions · emailed PDF</span>
      </div>
      <div className="upload-body">
        <p className="upload-desc">
          Email a tenant&apos;s module report (PDF, with charts) to a recipient on a
          schedule. Sending runs from <code>scripts.send_scheduled_reports</code> (an
          ECS scheduled task in production).
        </p>

        {isLoading && <div className="fp-alert-empty">Loading…</div>}

        {subs && subs.length > 0 && (
          <div className="tr-matrix-wrap">
            <table className="tr-matrix">
              <thead>
                <tr><th>Tenant</th><th>Module</th><th>Cadence</th><th>Recipient</th><th>Last sent</th><th></th></tr>
              </thead>
              <tbody>
                {subs.map((s) => (
                  <tr key={s.id}>
                    <td>{s.tenant_id}</td>
                    <td>{moduleList.find((m) => m.key === s.module)?.label ?? s.module}</td>
                    <td>{s.frequency}</td>
                    <td className="srep-email">{s.recipient_email}</td>
                    <td>{s.last_sent_at ? new Date(s.last_sent_at).toLocaleDateString() : '—'}</td>
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
          <label className="upload-field"><span className="upload-field-label">Tenant</span>
            <select value={tenantId} onChange={(e) => setTenantId(e.target.value)}>
              {tenants.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select></label>
          <label className="upload-field"><span className="upload-field-label">Module</span>
            <select value={module} onChange={(e) => setModule(e.target.value)}>
              {moduleList.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
            </select></label>
          <label className="upload-field"><span className="upload-field-label">Cadence</span>
            <select value={frequency} onChange={(e) => setFrequency(e.target.value)}>
              <option value="monthly">Monthly</option>
              <option value="quarterly">Quarterly</option>
            </select></label>
          <label className="upload-field upload-field--grow"><span className="upload-field-label">Recipient email</span>
            <input type="email" value={email} placeholder="lead@partner.org"
              onChange={(e) => setEmail(e.target.value)} /></label>
        </div>
        <div className="sms-demo-actions">
          <button type="button" className="sms-btn sms-btn--go"
            disabled={create.isPending || !email.trim() || tenants.length === 0}
            onClick={add}>
            {create.isPending ? 'Scheduling…' : 'Schedule report'}
          </button>
        </div>
        {note && <div className="sms-result">{note}</div>}
      </div>
    </div>
  );
}
