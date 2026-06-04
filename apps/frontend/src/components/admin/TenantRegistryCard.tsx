'use client';

import { useState } from 'react';

import {
  useAdminTenants,
  useInviteTenant,
  useRegisterTenant,
  useSetTenantModules,
  type RegisteredTenant,
  type TenantCategory,
} from '@/hooks/useTenantModules';

const TIERS = ['standard', 'premium', 'pilot'];

/**
 * Super-admin: register tenants (after MoU/subscription) and control which
 * modules each can access. The module matrix toggles drive both the dashboard
 * nav and the API access middleware.
 */
export default function TenantRegistryCard() {
  const { data, isLoading, isError } = useAdminTenants();
  const setModules = useSetTenantModules();
  const [inviting, setInviting] = useState<RegisteredTenant | null>(null);

  const catalog = data?.catalog ?? [];
  const tenants = data?.tenants ?? [];
  const categories = data?.categories ?? [];

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
                      <span className="tr-account">
                        {t.admin_email
                          ? <span className="tr-account-email" title={t.admin_email}>✉ {t.admin_email}</span>
                          : <span className="tr-account-none">no account yet</span>}
                        <button
                          type="button"
                          className="tr-invite-btn"
                          onClick={() => setInviting(t)}
                        >
                          {t.admin_email ? 'Re-invite' : 'Invite'}
                        </button>
                      </span>
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

        <RegisterTenantForm catalog={catalog} categories={categories} />
      </div>

      {inviting && (
        <InviteModal tenant={inviting} onClose={() => setInviting(null)} />
      )}
    </div>
  );
}

function InviteModal({ tenant, onClose }: { tenant: RegisteredTenant; onClose: () => void }) {
  const invite = useInviteTenant();
  const [email, setEmail] = useState(tenant.admin_email ?? '');
  const [name, setName] = useState('');
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  function submit() {
    setNote(null);
    setInviteUrl(null);
    invite.mutate(
      { tenantId: tenant.id, admin_email: email.trim(), admin_name: name.trim() || null },
      {
        onSuccess: (t) => {
          setInviteUrl(t.invite_url ?? null);
          setNote(
            t.invite_url
              ? `Invite ready for ${t.admin_email}. In dev the link isn’t emailed — copy it below.`
              : `Invite sent to ${t.admin_email}.`,
          );
        },
        onError: (e) => setNote(`Failed: ${e.message}`),
      },
    );
  }

  return (
    <div className="auth-overlay" role="dialog" aria-modal="true" aria-label="Invite tenant admin" onClick={onClose}>
      <div className="auth-modal" onClick={(e) => e.stopPropagation()}>
        <h2 className="auth-modal-title">
          {tenant.admin_email ? 'Re-invite' : 'Invite'} — {tenant.name}
        </h2>
        <p className="auth-modal-sub">
          Send an activation link so this partner can set a password and sign in
          with the access you’ve granted. No data setup needed — they’re a viewer.
        </p>
        <label className="upload-field">
          <span className="upload-field-label">Admin email</span>
          <input type="email" value={email} autoFocus placeholder="liaison@partner.org"
            onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="upload-field">
          <span className="upload-field-label">Admin name (optional)</span>
          <input value={name} placeholder="Full name" onChange={(e) => setName(e.target.value)} />
        </label>
        {note && <div className="sms-result">{note}</div>}
        {inviteUrl && (
          <div className="tr-invite">
            <span className="tr-invite-label">Dev activation link (copy &amp; share):</span>
            <code className="tr-invite-url">{inviteUrl}</code>
          </div>
        )}
        <div className="auth-modal-actions">
          <button type="button" className="auth-btn auth-btn--ghost" onClick={onClose} disabled={invite.isPending}>
            Close
          </button>
          <button type="button" className="auth-btn auth-btn--go" onClick={submit}
            disabled={invite.isPending || !email.trim()}>
            {invite.isPending ? 'Sending…' : 'Send invite'}
          </button>
        </div>
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

function RegisterTenantForm(
  { catalog, categories }: {
    catalog: { key: string; label: string }[];
    categories: TenantCategory[];
  },
) {
  const register = useRegisterTenant();
  const groups = [...new Set(categories.map((c) => c.group))];
  const [id, setId] = useState('');
  const [name, setName] = useState('');
  const [type, setType] = useState(categories[0]?.key ?? 'ng_state');
  const [country, setCountry] = useState('nigeria');
  const [tier, setTier] = useState(TIERS[0]);
  const [mou, setMou] = useState('');
  const [adminEmail, setAdminEmail] = useState('');
  const [adminName, setAdminName] = useState('');
  const [enabled, setEnabled] = useState<Set<string>>(new Set(catalog.map((m) => m.key)));
  const [note, setNote] = useState<string | null>(null);
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);

  function submit() {
    setNote(null);
    setInviteUrl(null);
    register.mutate(
      {
        id: id.trim().toLowerCase(),
        name: name.trim(),
        tenant_type: type,
        country,
        subscription_tier: tier,
        mou_reference: mou.trim() || null,
        admin_email: adminEmail.trim() || null,
        admin_name: adminName.trim() || null,
        enabled_keys: [...enabled],
      },
      {
        onSuccess: (t) => {
          const n = t.modules.filter((m) => m.enabled).length;
          setNote(
            t.admin_email
              ? `✓ Registered ${t.name} (${n} modules). Activation invite sent to ${t.admin_email}.`
              : `✓ Registered ${t.name} (${n} modules).`,
          );
          setInviteUrl(t.invite_url ?? null);
          setId(''); setName(''); setMou(''); setAdminEmail(''); setAdminName('');
        },
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
        <label className="upload-field"><span className="upload-field-label">Category</span>
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {groups.map((g) => (
              <optgroup key={g} label={g}>
                {categories.filter((c) => c.group === g).map((c) => (
                  <option key={c.key} value={c.key}>
                    {c.label}{c.geographic ? '' : ' (access only)'}
                  </option>
                ))}
              </optgroup>
            ))}
          </select></label>
        <label className="upload-field"><span className="upload-field-label">Country</span>
          <input value={country} onChange={(e) => setCountry(e.target.value)} /></label>
        <label className="upload-field"><span className="upload-field-label">Tier</span>
          <select value={tier} onChange={(e) => setTier(e.target.value)}>
            {TIERS.map((t) => <option key={t} value={t}>{t}</option>)}
          </select></label>
        <label className="upload-field"><span className="upload-field-label">MoU reference</span>
          <input value={mou} placeholder="MoU-2026-KN-001" onChange={(e) => setMou(e.target.value)} /></label>
        <label className="upload-field"><span className="upload-field-label">Admin email (gets activation invite)</span>
          <input type="email" value={adminEmail} placeholder="lead@kano.gov.ng" onChange={(e) => setAdminEmail(e.target.value)} /></label>
        <label className="upload-field"><span className="upload-field-label">Admin name</span>
          <input value={adminName} placeholder="Aisha Bello" onChange={(e) => setAdminName(e.target.value)} /></label>
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
      {inviteUrl && (
        <div className="tr-invite">
          <span className="tr-invite-label">Dev activation link (email not sent in dev — copy &amp; share):</span>
          <code className="tr-invite-url">{inviteUrl}</code>
        </div>
      )}
      <p className="tr-note">
        Registering creates the tenant&apos;s account and emails an activation invite to
        the admin email so they can set their password. Geographic tenants (State / FCT /
        Country) also get a data schema provisioned automatically; organisation tenants
        (NGO / Research / Funder) are access-only. In dev, the activation link is shown
        above instead of emailed.
      </p>
    </details>
  );
}
