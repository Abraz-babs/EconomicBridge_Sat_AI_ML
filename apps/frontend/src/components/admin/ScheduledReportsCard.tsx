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
  // Multi-select (2026-07-16): one recipient can be scheduled for SEVERAL
  // module reports at once — ticked modules each become their own
  // subscription row (the backend model is unchanged: one row per module).
  const [selectedModules, setSelectedModules] = useState<Set<string>>(
    () => new Set(['farmland']),
  );
  const [frequency, setFrequency] = useState('monthly');
  const [email, setEmail] = useState('');
  const [note, setNote] = useState<string | null>(null);

  function toggleModule(key: string) {
    setSelectedModules((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function add() {
    setNote(null);
    const tenant = tenantId || tenants[0]?.id || '';
    const picked = moduleList.filter((m) => selectedModules.has(m.key));
    let ok = 0;
    const failed: string[] = [];
    // Sequential so per-module failures are attributable, not racy.
    for (const m of picked) {
      try {
        await create.mutateAsync({
          tenant_id: tenant, module: m.key, frequency,
          recipient_email: email.trim(),
        });
        ok += 1;
      } catch {
        failed.push(m.label);
      }
    }
    if (failed.length === 0) {
      setNote(`✓ Scheduled ${ok} report${ok === 1 ? '' : 's'}.`);
      setEmail('');
    } else {
      setNote(
        `Scheduled ${ok} of ${picked.length} — failed: ${failed.join(', ')} `
        + '(already scheduled for this recipient?)',
      );
    }
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
          <div className="upload-field"><span className="upload-field-label">
              Modules (tick all to include)</span>
            <div style={{
              display: 'flex', flexWrap: 'wrap', gap: '4px 14px',
              padding: '6px 2px', fontSize: '12.5px',
            }}>
              {moduleList.map((m) => (
                <label key={m.key} style={{ display: 'flex', alignItems: 'center', gap: '5px', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={selectedModules.has(m.key)}
                    onChange={() => toggleModule(m.key)}
                  />
                  {m.label}
                </label>
              ))}
            </div>
          </div>
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
            disabled={create.isPending || !email.trim() || tenants.length === 0
              || selectedModules.size === 0}
            onClick={add}>
            {create.isPending
              ? 'Scheduling…'
              : `Schedule ${selectedModules.size} report${selectedModules.size === 1 ? '' : 's'}`}
          </button>
        </div>
        {note && <div className="sms-result">{note}</div>}
      </div>
    </div>
  );
}
