'use client';

import { useState } from 'react';

import {
  useAdminTenants,
  useRegisterTenant,
  useSetTenantModules,
  type RegisteredTenant,
} from '@/hooks/useTenantModules';

const TYPES = ['ng_state', 'ng_fct', 'ecowas_country'];
const TIERS = ['standard', 'premium', 'pilot'];

/**
 * Super-admin: register tenants (after MoU/subscription) and control which
 * modules each can access. The module matrix toggles drive both the dashboard
 * nav and the API access middleware.
 */
export default function TenantRegistryCard() {
  const { data, isLoading, isError } = useAdminTenants();
  const setModules = useSetTenantModules();

  const catalog = data?.catalog ?? [];
  const tenants = data?.tenants ?? [];

  function toggle(tenant: RegisteredTenant, key: string, next: boolean) {
    const enabled = new Set(tenant.modules.filter((m) => m.enabled).map((m) => m.key));
    if (next) enabled.add(key); else enabled.delete(key);
    setModules.mutate({ tenantId: tenant.id, enabledKeys: [...enabled] });
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Tenant Registry &amp; Module Access</span>
        <span className="panel-meta">
          {isError ? 'API unreachable' : `${tenants.length} tenants · super-admin`}
        </span>
      </div>
      <div className="upload-body">
        <p className="upload-desc">
          Tenants are <strong>provisioned by super-admin</strong> after an MoU /
          subscription — they don&apos;t self-register. Toggle a module to grant or
          revoke a tenant&apos;s access (enforced in the nav <em>and</em> the API).
        </p>

        {isLoading && <div className="fp-alert-empty">Loading registry…</div>}

        {tenants.length > 0 && (
          <div className="tr-matrix-wrap">
            <table className="tr-matrix">
              <thead>
                <tr>
                  <th className="tr-sticky">Tenant</th>
                  {catalog.map((m) => (
                    <th key={m.key} title={m.label}>{shortLabel(m.label)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tenants.map((t) => (
                  <tr key={t.id}>
                    <td className="tr-sticky">
                      <span className="tr-name">{t.name}</span>
                      <span className="tr-sub">{t.tenant_type} · {t.status}</span>
                    </td>
                    {catalog.map((m) => {
                      const on = t.modules.find((x) => x.key === m.key)?.enabled ?? false;
                      return (
                        <td key={m.key} className="tr-cell">
                          <input
                            type="checkbox"
                            checked={on}
                            disabled={setModules.isPending}
                            aria-label={`${t.name} – ${m.label}`}
                            onChange={(e) => toggle(t, m.key, e.target.checked)}
                          />
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <RegisterTenantForm catalog={catalog} />
      </div>
    </div>
  );
}

function shortLabel(label: string): string {
  // "Agriculture (CropGuard)" -> "CropGuard"; else first word(s).
  const paren = label.match(/\(([^)]+)\)/);
  if (paren) return paren[1];
  return label.split(' ')[0];
}

function RegisterTenantForm({ catalog }: { catalog: { key: string; label: string }[] }) {
  const register = useRegisterTenant();
  const [id, setId] = useState('');
  const [name, setName] = useState('');
  const [type, setType] = useState(TYPES[0]);
  const [country, setCountry] = useState('nigeria');
  const [tier, setTier] = useState(TIERS[0]);
  const [mou, setMou] = useState('');
  const [enabled, setEnabled] = useState<Set<string>>(new Set(catalog.map((m) => m.key)));
  const [note, setNote] = useState<string | null>(null);

  function submit() {
    setNote(null);
    register.mutate(
      {
        id: id.trim().toLowerCase(),
        name: name.trim(),
        tenant_type: type,
        country,
        subscription_tier: tier,
        mou_reference: mou.trim() || null,
        enabled_keys: [...enabled],
      },
      {
        onSuccess: (t) => { setNote(`✓ Registered ${t.name} with ${t.modules.filter((m) => m.enabled).length} modules.`); setId(''); setName(''); setMou(''); },
        onError: (e) => setNote(`Failed: ${e.message}`),
      },
    );
  }

  return (
    <details className="tr-register">
      <summary>Register a new tenant</summary>
      <div className="tr-form">
        <label className="upload-field"><span className="upload-field-label">Tenant id (slug)</span>
          <input value={id} placeholder="e.g. kano" onChange={(e) => setId(e.target.value)} /></label>
        <label className="upload-field"><span className="upload-field-label">Name</span>
          <input value={name} placeholder="Kano State" onChange={(e) => setName(e.target.value)} /></label>
        <label className="upload-field"><span className="upload-field-label">Type</span>
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select></label>
        <label className="upload-field"><span className="upload-field-label">Country</span>
          <input value={country} onChange={(e) => setCountry(e.target.value)} /></label>
        <label className="upload-field"><span className="upload-field-label">Tier</span>
          <select value={tier} onChange={(e) => setTier(e.target.value)}>
            {TIERS.map((t) => <option key={t} value={t}>{t}</option>)}
          </select></label>
        <label className="upload-field upload-field--grow"><span className="upload-field-label">MoU reference</span>
          <input value={mou} placeholder="MoU-2026-KN-001" onChange={(e) => setMou(e.target.value)} /></label>
      </div>
      <div className="tr-modpick">
        {catalog.map((m) => (
          <label key={m.key} className="tr-modpick-item">
            <input type="checkbox" checked={enabled.has(m.key)}
              onChange={(e) => {
                const next = new Set(enabled);
                if (e.target.checked) next.add(m.key); else next.delete(m.key);
                setEnabled(next);
              }} />
            {shortLabel(m.label)}
          </label>
        ))}
      </div>
      <div className="sms-demo-actions">
        <button type="button" className="sms-btn sms-btn--go"
          disabled={register.isPending || !id.trim() || !name.trim()} onClick={submit}>
          {register.isPending ? 'Registering…' : 'Register tenant'}
        </button>
      </div>
      {note && <div className="sms-result">{note}</div>}
      <p className="tr-note">
        Note: this records the registry + module entitlements. Provisioning a brand-new
        tenant&apos;s data schema (CREATE SCHEMA + migrate + seed) is a Phase-2 step —
        existing pilot schemas work immediately.
      </p>
    </details>
  );
}
